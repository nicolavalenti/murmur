"""Pipeline-parallel transcription via the Groq Whisper API.

Why this exists: the batch transcribe path waits until /stop_recording to send
any audio. For a 10-second clip with 1-second Groq latency, the user perceives
~1s of "processing." The streaming path slices ~2-second chunks during
recording and POSTs each one in parallel. By the time the hotkey is released,
all chunks except the tail are already transcribed; only the final ~1-2s of
audio needs to finish. Perceived latency drops to roughly one chunk worth.

Design constraints:
- Only Groq is supported. mlx-whisper hangs in Metal under concurrent load
  (we just patched a related bug), so chunking against the local backend is
  too risky for the value it would deliver.
- No overlap-and-dedupe in v1. Chunk boundaries can split words, which
  produces minor stitching artifacts. If this becomes a real problem in
  practice, add overlap windowing here.
- On failure, the caller falls back to a regular full-buffer transcribe. The
  streaming session is best-effort; never the only path to a result.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import numpy as np

from .transcribe import transcribe_groq


def _stitch(prev: str, new: str, max_overlap_words: int = 12) -> str:
    """Concatenate `new` onto `prev`, trimming any prefix of `new` that
    duplicates a suffix of `prev`.

    Streaming chunks are sliced with ~0.7s of overlapping audio at the
    boundary, which Whisper transcribes in both chunks. Without dedup, that
    audio's words appear twice in the joined transcript. We look for the
    longest suffix of `prev` (up to `max_overlap_words` words) that matches a
    prefix of `new`, normalized by lowercase + stripped punctuation, and trim
    those words off `new` before joining.

    Exact-match-on-normalized-tokens is the simplest correct approach. It
    misses cases where Whisper transcribed the overlap region differently
    in the two chunks (which does happen), but those are minor and produce
    a small duplication, not a worse error than no-stitch would.
    """
    if not prev:
        return new
    if not new:
        return prev

    def norm(word: str) -> str:
        return word.lower().strip(",.!?;:\"'()[]{}")

    prev_words = prev.split()
    new_words = new.split()
    max_k = min(max_overlap_words, len(prev_words), len(new_words))
    for k in range(max_k, 0, -1):
        suffix = [norm(w) for w in prev_words[-k:]]
        prefix = [norm(w) for w in new_words[:k]]
        if suffix == prefix and all(suffix):  # all() guards against empty tokens
            trimmed = " ".join(new_words[k:])
            return f"{prev} {trimmed}".rstrip()
    return f"{prev} {new}"


@dataclass
class StreamingConfig:
    chunk_interval_s: float = 2.0
    # Below this many samples we skip the chunk (typically a sub-100ms straggler
    # after silence). 500ms @ 16kHz.
    min_chunk_samples: int = 8000
    # Cap on a single chunk's size, to keep individual Groq requests bounded.
    # 15s @ 16kHz = 240k samples. If exceeded, we slice and let the next tick
    # handle the rest.
    max_chunk_samples: int = 240_000
    # Each chunk after the first reaches back this many seconds into the
    # previous chunk's audio. Without overlap, words straddling a chunk boundary
    # get cut and mistranscribed ("should" → "show"). With overlap, Whisper
    # sees the full word in at least one chunk; the stitcher dedupes the
    # duplicate prefix at concatenation time.
    overlap_s: float = 0.7
    # The tail-flush at finalize. If we already have completed chunks AND the
    # remaining un-chunked audio is shorter than this, skip the tail — the
    # previous chunk's overlap probably covered it, and Whisper hallucinates
    # ("This", "Thanks for watching") on sub-300ms fragments.
    min_tail_samples: int = 4800  # 300ms @ 16kHz
    max_concurrent: int = 3
    sample_rate: int = 16000
    language: str = "en"


@dataclass
class _ChunkResult:
    seq: int
    text: str
    elapsed_ms: int
    error: str | None = None


class StreamingTranscriber:
    """Slices a live `Recorder` into chunks and transcribes them in parallel.

    Lifecycle:
        st = StreamingTranscriber(recorder, api_key, cfg, vocab)
        await st.start()           # begins the chunker loop
        ... user speaks ...
        text, metrics = await st.finalize()  # flushes tail, awaits all chunks

    `has_partials` tells the caller whether any chunks completed, useful when
    deciding whether to use the streaming result or fall back.
    """

    def __init__(
        self,
        recorder,  # backend.audio.Recorder; not typed to avoid an import cycle
        api_key: str,
        config: StreamingConfig,
        vocabulary: list[str] | None = None,
        extra_vocabulary: list[str] | None = None,
    ):
        self._recorder = recorder
        self._api_key = api_key
        self._cfg = config
        self._vocabulary = vocabulary
        self._extra_vocabulary = extra_vocabulary

        self._next_seq = 0
        self._next_sample = 0
        self._results: dict[int, _ChunkResult] = {}
        self._inflight: set[asyncio.Task] = set()
        self._sem = asyncio.Semaphore(config.max_concurrent)

        self._loop_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._fatal_error: Exception | None = None

    async def start(self) -> None:
        """Kick off the background chunker. Returns immediately."""
        self._loop_task = asyncio.create_task(
            self._chunker_loop(), name="murmur-streaming-chunker"
        )

    async def _chunker_loop(self) -> None:
        """Wake at chunk_interval_s, slice off any new audio, dispatch. Exits
        when stop_event fires (finalize() handles the tail)."""
        try:
            while not self._stop_event.is_set():
                try:
                    # Use wait_for on the stop event so we exit promptly when
                    # finalize() asks us to. The timeout IS the tick interval.
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._cfg.chunk_interval_s,
                    )
                    return  # stop_event fired; finalize handles the tail
                except asyncio.TimeoutError:
                    self._maybe_dispatch_chunk()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Loop bugs (not chunk transcribe errors, those are per-task) get
            # stored so finalize() can raise them to the caller.
            self._fatal_error = e

    def _maybe_dispatch_chunk(self) -> None:
        total = self._recorder.total_samples()
        available = total - self._next_sample
        if available < self._cfg.min_chunk_samples:
            return
        end = self._next_sample + min(available, self._cfg.max_chunk_samples)
        # Subsequent chunks reach back overlap_s into the previous one so
        # Whisper sees full words across the boundary. First chunk starts at 0.
        overlap_samples = int(self._cfg.overlap_s * self._cfg.sample_rate)
        start = max(0, self._next_sample - overlap_samples) if self._next_seq > 0 else 0
        chunk = self._recorder.slice(start, end)
        if chunk.size == 0:
            return
        self._next_sample = end
        self._dispatch(chunk)

    def _dispatch(self, chunk: np.ndarray) -> None:
        seq = self._next_seq
        self._next_seq += 1
        task = asyncio.create_task(
            self._transcribe_chunk(seq, chunk),
            name=f"murmur-streaming-chunk-{seq}",
        )
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _transcribe_chunk(self, seq: int, chunk: np.ndarray) -> None:
        async with self._sem:
            t0 = time.perf_counter()
            try:
                text = await transcribe_groq(
                    chunk,
                    api_key=self._api_key,
                    sample_rate=self._cfg.sample_rate,
                    language=self._cfg.language,
                    vocabulary=self._vocabulary,
                    extra_vocabulary=self._extra_vocabulary,
                )
                elapsed = int((time.perf_counter() - t0) * 1000)
                self._results[seq] = _ChunkResult(
                    seq=seq, text=text, elapsed_ms=elapsed
                )
                print(f"[murmur] stream chunk {seq} done — {elapsed}ms, {len(text)} chars")
            except Exception as e:
                elapsed = int((time.perf_counter() - t0) * 1000)
                self._results[seq] = _ChunkResult(
                    seq=seq, text="", elapsed_ms=elapsed, error=str(e)
                )
                print(f"[murmur] stream chunk {seq} failed in {elapsed}ms: {e}")

    async def finalize(self, await_timeout_s: float = 25.0) -> tuple[str, dict]:
        """Stop the chunker, flush the tail, await all in-flight chunks.

        Raises if every chunk errored, so the caller can fall back to batch.
        Otherwise returns the concatenated text plus a small metrics dict.
        """
        self._stop_event.set()
        if self._loop_task is not None:
            try:
                await asyncio.wait_for(self._loop_task, timeout=2.0)
            except asyncio.TimeoutError:
                self._loop_task.cancel()
        # Flush whatever's new since the last tick. Apply the same overlap
        # back-reach so Whisper has continuous context with the previous chunk.
        # Skip very short tails when we already have chunks — overlap from the
        # previous chunk likely covered the audio, and short fragments
        # hallucinate.
        total = self._recorder.total_samples()
        tail_size = total - self._next_sample
        have_prior = any(r.error is None for r in self._results.values())
        if tail_size > 0 and not (have_prior and tail_size < self._cfg.min_tail_samples):
            overlap_samples = int(self._cfg.overlap_s * self._cfg.sample_rate)
            start = (
                max(0, self._next_sample - overlap_samples)
                if self._next_seq > 0
                else 0
            )
            tail = self._recorder.slice(start, total)
            self._next_sample = total
            if tail.size > 0:
                self._dispatch(tail)

        if self._inflight:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*list(self._inflight), return_exceptions=True),
                    timeout=await_timeout_s,
                )
            except asyncio.TimeoutError:
                # Hard cap. Whatever finished by now is what we use.
                pass

        if self._fatal_error is not None:
            raise self._fatal_error

        ordered = sorted(self._results.values(), key=lambda r: r.seq)
        successful = [r for r in ordered if r.error is None]

        all_errored = bool(ordered) and not successful
        if all_errored:
            first_err = next((r.error for r in ordered if r.error), "unknown")
            raise RuntimeError(f"all streaming chunks failed: {first_err}")

        # Stitch chunks with overlap-dedup. Each chunk shares ~0.7s of audio
        # with its predecessor, so the start of each transcript overlaps the
        # end of the previous one. We trim the duplicate words.
        text = ""
        for r in successful:
            text = _stitch(text, r.text.strip())

        metrics = {
            "chunks": len(ordered),
            "chunk_latencies_ms": [r.elapsed_ms for r in ordered],
            "failed_chunks": sum(1 for r in ordered if r.error is not None),
        }
        return text, metrics

    @property
    def has_partials(self) -> bool:
        return any(r.error is None for r in self._results.values())

    async def abort(self) -> None:
        """Best-effort teardown without awaiting in-flight transcribes. Used
        when /start_recording arrives mid-session or on hard cancellation."""
        self._stop_event.set()
        if self._loop_task is not None and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass
        for task in list(self._inflight):
            task.cancel()
