import asyncio
import concurrent.futures
import re
import time
from typing import Any

import pyperclip
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import config as config_module
from .audio import Recorder
from .polish import polish, GROQ_URL
from .streaming import StreamingConfig, StreamingTranscriber
from .transcribe import transcribe, transcribe_groq
from .vad import trim_silence

app = FastAPI(title="murmur", version="0.1.0")

# Process-level state. Single-user tool, so one recorder is fine.
_recorder: Recorder | None = None
_cfg: dict[str, Any] = config_module.load()
# Reference to the currently running /stop_recording task. Lets /cancel and
# subsequent /stop_recording calls abort an in-flight transcribe + polish job
# instead of letting it run to completion and ghost-paste later.
_active_stop: asyncio.Task | None = None
# Active streaming transcription session (only populated in "streaming" mode
# with Groq backend + key configured). Lives from /start_recording through
# /stop_recording's finalize.
_streaming: StreamingTranscriber | None = None

# Single-worker pool for mlx-whisper. mlx talks to Metal, which crashes hard
# (SIGABRT in the GPU command encoder) if two threads issue compute commands
# concurrently. Serialising at the executor level guarantees only one transcribe
# is ever in flight.
#
# Threads can't be killed in Python. If mlx-whisper hangs inside Metal (seen
# after macOS sleep/wake or a corrupt Metal context), the worker thread stays
# busy and every subsequent transcribe queues behind it forever. We can't kill
# it, but we CAN swap the pool: shutdown(wait=False) detaches the old pool
# (zombie keeps running in the background until process exit), and a fresh
# pool gives the next request a clean worker. _last_transcribe_future tracks
# the in-flight future so we can detect "previous one is still running" on
# entry and on cancellation paths.
_transcribe_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="transcribe"
)
_last_transcribe_future: concurrent.futures.Future | None = None
# Hard ceiling for a single transcribe. Less than the Swift URLSession timeout
# (30s) so we return a proper 504 with a recycled pool instead of letting the
# HTTP connection black-hole.
_TRANSCRIBE_TIMEOUT_S = 25.0


def _recycle_transcribe_pool(reason: str) -> None:
    """Replace the transcribe pool. The previous pool's worker thread may still
    be wedged inside mlx-whisper / Metal; we can't kill it, but we can detach
    the pool and start fresh. The zombie completes on its own time (or never)
    and is reclaimed at process exit."""
    global _transcribe_pool, _last_transcribe_future
    print(f"[murmur] recycling transcribe pool — reason: {reason}")
    old = _transcribe_pool
    _transcribe_pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="transcribe"
    )
    _last_transcribe_future = None
    # wait=False is essential: don't block on the zombie.
    old.shutdown(wait=False)


class TranscriptResponse(BaseModel):
    raw: str
    polished: str
    elapsed_ms: dict[str, int]


class StopRequest(BaseModel):
    # Optional snippet from the user's clipboard at recording time. Used to bias
    # Whisper and the polish LLM toward proper nouns the user is currently writing
    # about. Body is optional so existing flows posting empty bodies still work.
    context: str | None = None
    # Frontmost app at recording time. Fed into the polish prompt so the LLM can
    # adapt register (casual for Slack, formal for Mail, technical for editors).
    app_bundle_id: str | None = None
    app_name: str | None = None


_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-zA-Z]{2,}\b")
# Drop sentence-initial common words that match the regex but aren't proper nouns.
_PROPER_NOUN_STOPWORDS = {
    "the", "and", "but", "for", "with", "from", "this", "that", "these", "those",
    "when", "where", "what", "which", "while", "after", "before", "into", "over",
    "you", "your", "they", "their", "there", "then", "than", "have", "has", "had",
    "will", "would", "could", "should", "may", "might", "must", "can", "yes", "no",
    "hi", "hello", "hey", "thanks", "thank", "best", "regards", "dear", "subject",
}


def _extract_proper_nouns(context: str | None, max_items: int = 30) -> list[str]:
    if not context:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for word in _PROPER_NOUN_RE.findall(context):
        key = word.lower()
        if key in _PROPER_NOUN_STOPWORDS or key in seen:
            continue
        seen.add(key)
        out.append(word)
        if len(out) >= max_items:
            break
    return out


class SettingsPatch(BaseModel):
    whisper_model: str | None = None
    openrouter_api_key: str | None = None
    groq_api_key: str | None = None
    polishing_model: str | None = None
    polishing_prompt: str | None = None
    auto_paste: bool | None = None
    hotkey: str | None = None
    sample_rate: int | None = None
    input_gain: float | None = None
    language: str | None = None
    vocabulary: list[str] | None = None
    substitutions: dict[str, str] | None = None
    polish_min_chars: int | None = None
    use_clipboard_context: bool | None = None
    context_max_chars: int | None = None
    transcription_backend: str | None = None
    polishing_backend: str | None = None
    transcription_mode: str | None = None  # "batch" or "streaming"
    stream_chunk_interval_s: float | None = None
    stream_max_concurrent: int | None = None


def _apply_substitutions(text: str, subs: dict[str, str] | None) -> str:
    """Whole-word, case-insensitive replacement. \\b boundaries mean 'slash' in
    'slashing' is left alone. Longest keys first so multi-word entries (e.g.
    'forward slash') win over their shorter prefixes."""
    if not subs or not text:
        return text
    for word in sorted(subs.keys(), key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(word)}\b", subs[word], text, flags=re.IGNORECASE)
    return text


@app.get("/status")
async def status() -> dict[str, Any]:
    return {
        "ok": True,
        "recording": _recorder is not None and _recorder.is_running,
        "whisper_model": _cfg["whisper_model"],
        "polishing_model": _cfg["polishing_model"],
    }


@app.get("/level")
async def level() -> dict[str, float]:
    """Current audio RMS while recording. Returns 0.0 when idle.
    Polled by the Swift UI to drive the reactive waveform."""
    if _recorder is None or not _recorder.is_running:
        return {"level": 0.0}
    return {"level": _recorder.current_level()}


@app.get("/settings")
async def get_settings() -> dict[str, Any]:
    safe = dict(_cfg)
    if safe.get("openrouter_api_key"):
        safe["openrouter_api_key"] = "sk-or-***"
    if safe.get("groq_api_key"):
        safe["groq_api_key"] = "gsk-***"
    return safe


@app.post("/settings")
async def update_settings(patch: SettingsPatch) -> dict[str, Any]:
    global _cfg
    updates = {k: v for k, v in patch.model_dump().items() if v is not None}
    _cfg = {**_cfg, **updates}
    config_module.save(_cfg)
    return await get_settings()


def _streaming_eligible() -> bool:
    """Streaming requires Groq transcription with a key. Anything else falls
    back to batch silently — the setting is best-effort, not a hard switch."""
    return (
        _cfg.get("transcription_mode") == "streaming"
        and _cfg.get("transcription_backend") == "groq"
        and bool(_cfg.get("groq_api_key"))
    )


@app.post("/start_recording")
async def start_recording() -> dict[str, Any]:
    global _recorder, _active_stop, _streaming
    # If a stop is still in flight (slow polish), abort it. The user has already
    # decided to start fresh — we don't want the dying stop to fight us for state.
    if _active_stop is not None and not _active_stop.done():
        _active_stop.cancel()
    if _streaming is not None:
        await _streaming.abort()
        _streaming = None
    if _recorder is not None and _recorder.is_running:
        _recorder.stop()  # force-clear a ghost recording (e.g. after app crash)
        _recorder = None
    _recorder = Recorder(sample_rate=_cfg["sample_rate"], gain=_cfg.get("input_gain", 1.0))
    _recorder.start()
    if _streaming_eligible():
        stream_cfg = StreamingConfig(
            chunk_interval_s=float(_cfg.get("stream_chunk_interval_s", 2.0)),
            max_concurrent=int(_cfg.get("stream_max_concurrent", 3)),
            sample_rate=_cfg["sample_rate"],
            language=_cfg.get("language", "en"),
        )
        _streaming = StreamingTranscriber(
            recorder=_recorder,
            api_key=_cfg["groq_api_key"],
            config=stream_cfg,
            vocabulary=_cfg.get("vocabulary") or None,
        )
        await _streaming.start()
        print(f"[murmur] streaming mode active (interval={stream_cfg.chunk_interval_s}s, concurrent={stream_cfg.max_concurrent})")
    return {"recording": True, "started_at": time.time(), "streaming": _streaming is not None}


@app.post("/cancel")
async def cancel() -> dict[str, bool]:
    """Abort an in-flight /stop_recording (transcribe + polish). Used by the
    Swift app when the user presses the hotkey during the processing state."""
    global _active_stop, _streaming
    cancelled = False
    if _active_stop is not None and not _active_stop.done():
        _active_stop.cancel()
        cancelled = True
    if _streaming is not None:
        # No active /stop_recording but a streaming session is still chunking
        # (recording-in-progress cancel). Abort it so background HTTP requests
        # stop firing.
        await _streaming.abort()
        _streaming = None
        cancelled = True
    return {"cancelled": cancelled}


@app.post("/stop_recording", response_model=TranscriptResponse)
async def stop_recording(body: StopRequest | None = None) -> TranscriptResponse:
    global _recorder, _active_stop, _streaming
    if _recorder is None:
        raise HTTPException(status_code=409, detail="not recording")
    # If a previous stop is still running (rare — slow polish + rapid hotkey
    # taps), cancel it so this new request takes precedence.
    if _active_stop is not None and not _active_stop.done():
        _active_stop.cancel()
    _active_stop = asyncio.current_task()
    # recorder may have been auto-stopped by the watchdog (max duration exceeded)
    # but frames are still in memory — proceed to transcribe what was captured

    t0 = time.perf_counter()
    # Capture the streaming session BEFORE stopping the recorder. finalize()
    # reads tail audio from the live recorder, so we must wait until that's
    # done before releasing the mic.
    streaming_session = _streaming
    _streaming = None

    streamed_text: str | None = None
    stream_metrics: dict | None = None
    stream_error: str | None = None

    if streaming_session is not None:
        try:
            streamed_text, stream_metrics = await asyncio.wait_for(
                streaming_session.finalize(),
                timeout=_TRANSCRIBE_TIMEOUT_S,
            )
            print(
                f"[murmur] streaming finalize — chunks: {stream_metrics['chunks']}  "
                f"failed: {stream_metrics['failed_chunks']}  "
                f"latencies_ms: {stream_metrics['chunk_latencies_ms']}"
            )
        except (asyncio.TimeoutError, Exception) as e:
            stream_error = str(e)
            print(f"[murmur] streaming failed, falling back to batch: {e}")
            # Clean up any lingering tasks; finalize might have left some.
            await streaming_session.abort()

    audio = _recorder.stop()
    _recorder = None
    t_stop = time.perf_counter()

    original_samples = audio.size
    audio = trim_silence(audio, sample_rate=_cfg["sample_rate"])
    trim_ratio = audio.size / max(1, original_samples)
    t_vad = time.perf_counter()

    use_ctx = bool(_cfg.get("use_clipboard_context", True))
    max_chars = int(_cfg.get("context_max_chars", 4000) or 0)
    raw_context = (body.context if body else None) if use_ctx else None
    if raw_context and max_chars > 0:
        raw_context = raw_context[:max_chars]
    context_nouns = _extract_proper_nouns(raw_context)
    app_bundle_id = body.app_bundle_id if body else None
    app_name = body.app_name if body else None
    if app_name or app_bundle_id:
        print(f"[murmur] app context — name: {app_name!r}  bundle: {app_bundle_id!r}")

    try:
        tb = _cfg.get("transcription_backend", "local")
        if streamed_text is not None:
            # Streaming finalize succeeded — skip the batch transcribe entirely.
            raw = streamed_text
        elif tb == "groq":
            # Groq Whisper API: async network call, no Metal — runs directly on
            # the event loop without blocking it. No need for run_in_executor.
            raw = await transcribe_groq(
                audio,
                api_key=_cfg.get("groq_api_key", ""),
                sample_rate=_cfg["sample_rate"],
                language=_cfg.get("language", "en"),
                vocabulary=_cfg.get("vocabulary") or None,
                extra_vocabulary=context_nouns or None,
            )
        else:
            # mlx-whisper is CPU/GPU bound and synchronous. Dispatch to the
            # dedicated single-worker pool so concurrent calls serialise instead
            # of stomping each other in Metal (which SIGABRTs).
            global _last_transcribe_future
            # If a previous transcribe is still running, the pool's single
            # worker is wedged (mlx hung inside Metal). Swap to a fresh pool
            # before submitting so this request doesn't queue forever behind
            # the zombie.
            if (
                _last_transcribe_future is not None
                and not _last_transcribe_future.done()
            ):
                _recycle_transcribe_pool(
                    reason="previous transcribe still running on entry"
                )
            cf_future = _transcribe_pool.submit(
                lambda: transcribe(
                    audio,
                    model=_cfg["whisper_model"],
                    sample_rate=_cfg["sample_rate"],
                    language=_cfg.get("language", "en"),
                    vocabulary=_cfg.get("vocabulary") or None,
                    extra_vocabulary=context_nouns or None,
                )
            )
            _last_transcribe_future = cf_future
            try:
                raw = await asyncio.wait_for(
                    asyncio.wrap_future(cf_future),
                    timeout=_TRANSCRIBE_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                _recycle_transcribe_pool(
                    reason=f"transcribe exceeded {_TRANSCRIBE_TIMEOUT_S:.0f}s"
                )
                raise HTTPException(
                    status_code=504,
                    detail=f"transcribe timed out after {int(_TRANSCRIBE_TIMEOUT_S)}s",
                )
        t_trans = time.perf_counter()

        polish_min_chars = int(_cfg.get("polish_min_chars", 0) or 0)
        pb = _cfg.get("polishing_backend", "auto")
        polish_skipped = len(raw.strip()) < polish_min_chars or pb == "off"
        if polish_skipped:
            polished = raw
        else:
            groq_key = _cfg.get("groq_api_key", "")
            or_key = _cfg.get("openrouter_api_key", "")
            if pb == "groq":
                polish_key, polish_url = groq_key, GROQ_URL
            elif pb == "openrouter":
                polish_key, polish_url = or_key, None
            else:  # "auto": prefer Groq if key present, else OpenRouter
                polish_key = groq_key if groq_key else or_key
                polish_url = GROQ_URL if groq_key else None
            polished = await polish(
                raw,
                model=_cfg.get("polishing_model") or None,
                api_key=polish_key,
                prompt=_cfg["polishing_prompt"],
                context_snippet=raw_context,
                app_bundle_id=app_bundle_id,
                app_name=app_name,
                **{"url": polish_url} if polish_url else {},
            )
        # Substitutions go after polish so the LLM never sees raw symbols (which
        # could confuse small models) and can't undo our replacements.
        polished = _apply_substitutions(polished, _cfg.get("substitutions"))
        # Strip the terminal period on short, single-sentence outputs. Small
        # polish models have a strong training-data prior to add a period to
        # every output, and prompt instructions can't always override it. This
        # is the deterministic backstop: when there is exactly one period
        # (counting only the trailing one), the output is short enough to be a
        # casual line, and there are no line breaks (so it's not a list),
        # drop the trailing period. Skips longer prose where periods are
        # load-bearing, and abbreviations like "U.S." (count > 1).
        if (
            polished
            and len(polished) <= 100
            and polished.count(".") == 1
            and polished.endswith(".")
            and "\n" not in polished
        ):
            polished = polished[:-1]
        # Trailing space so the user's next dictation or keystrokes continue
        # naturally without requiring manual spacing. Skip when the output is
        # empty or already whitespace-terminated (e.g. list output ending in a
        # newline).
        if polished and not polished[-1].isspace():
            polished = polished + " "
        t_polish = time.perf_counter()

        try:
            pyperclip.copy(polished)
        except Exception:
            pass  # clipboard is set by the Swift app; this is best-effort only
        t_clip = time.perf_counter()

        elapsed = {
            "stop": int((t_stop - t0) * 1000),
            "vad": int((t_vad - t_stop) * 1000),
            "transcribe": int((t_trans - t_vad) * 1000),
            "polish": int((t_polish - t_trans) * 1000),
            "clipboard": int((t_clip - t_polish) * 1000),
            "total": int((t_clip - t0) * 1000),
        }
        polish_label = f"polish: {elapsed['polish']}ms" + (" (skipped)" if polish_skipped else "")
        transcribe_label = f"transcribe: {elapsed['transcribe']}ms"
        if streamed_text is not None:
            transcribe_label += f" (streamed, {stream_metrics['chunks']} chunks)"
        elif stream_error is not None:
            transcribe_label += f" (stream-fallback: {stream_error[:40]})"
        log_line = (
            f"vad: {elapsed['vad']}ms (kept {trim_ratio*100:.0f}%)  "
            f"{transcribe_label}  "
            f"{polish_label}  "
            f"total: {elapsed['total']}ms\n"
        )
        print(f"[murmur] timing — {log_line}", end="")
        try:
            import pathlib
            log_path = pathlib.Path.home() / ".murmur" / "timing.log"
            with log_path.open("a") as f:
                f.write(log_line)
        except Exception:
            pass
        return TranscriptResponse(raw=raw, polished=polished, elapsed_ms=elapsed)
    except asyncio.CancelledError:
        # Triggered by /cancel or by another /stop_recording / /start_recording
        # superseding this one. Bubble up so FastAPI closes the connection cleanly.
        print("[murmur] stop_recording cancelled mid-flight")
        # If the local transcribe was still running, the worker thread is now
        # an unkillable zombie holding the pool's only slot. Recycle so the
        # next request gets a clean worker.
        if (
            _last_transcribe_future is not None
            and not _last_transcribe_future.done()
        ):
            _recycle_transcribe_pool(reason="cancelled while transcribing")
        raise
    finally:
        # Only clear if we're still the registered active task. A newer stop may
        # have already replaced us — don't stomp its registration.
        if _active_stop is asyncio.current_task():
            _active_stop = None


def main() -> None:
    import uvicorn
    uvicorn.run("murmur.server:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
