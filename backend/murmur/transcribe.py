import io
import wave

import numpy as np

_LOADED: dict[str, object] = {}

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_GROQ_MODEL = "whisper-large-v3"


def _build_initial_prompt(
    vocabulary: list[str] | None,
    extra_vocabulary: list[str] | None,
) -> str | None:
    merged: list[str] = []
    seen: set[str] = set()
    for word in (vocabulary or []) + (extra_vocabulary or []):
        key = word.lower()
        if key not in seen:
            seen.add(key)
            merged.append(word)
    return ("Vocabulary includes: " + ", ".join(merged) + ".") if merged else None


async def transcribe_groq(
    audio: np.ndarray,
    api_key: str,
    sample_rate: int = 16000,
    language: str = "en",
    vocabulary: list[str] | None = None,
    extra_vocabulary: list[str] | None = None,
) -> str:
    import httpx  # already a dependency via polish.py

    if not api_key:
        raise RuntimeError("Groq API key not configured for transcription")
    if audio.size < 1600:
        return ""

    audio = audio.astype(np.float32, copy=False)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        wf.writeframes(pcm.tobytes())
    wav_bytes = buf.getvalue()

    form: dict = {"model": _GROQ_MODEL, "language": language}
    prompt = _build_initial_prompt(vocabulary, extra_vocabulary)
    if prompt:
        form["prompt"] = prompt

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            GROQ_TRANSCRIPTION_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            data=form,
        )
    if not resp.is_success:
        raise RuntimeError(f"Groq transcription {resp.status_code}: {resp.text}")
    return (resp.json().get("text") or "").strip()


def transcribe(
    audio: np.ndarray,
    model: str,
    sample_rate: int = 16000,
    language: str = "en",
    vocabulary: list[str] | None = None,
    extra_vocabulary: list[str] | None = None,
) -> str:
    """Run mlx-whisper on an in-memory float32 mono array.

    mlx-whisper expects 16kHz mono float32. We assume the recorder already
    captured at 16kHz; if that ever changes, resample here before calling.
    """
    import mlx_whisper  # imported lazily so the server starts fast

    if sample_rate != 16000:
        raise ValueError("mlx-whisper expects 16kHz audio")

    if audio.size < 1600:  # less than 100ms at 16kHz — nothing to transcribe
        return ""

    audio = audio.astype(np.float32, copy=False)
    kwargs: dict = {"path_or_hf_repo": model, "language": language}
    prompt = _build_initial_prompt(vocabulary, extra_vocabulary)
    if prompt:
        # initial_prompt seeds Whisper's decoder context. The model treats it as
        # "what was said just before this audio," which biases spelling and word
        # choice without forcing it. Phrased as a sentence so it parses naturally.
        kwargs["initial_prompt"] = prompt
    result = mlx_whisper.transcribe(audio, **kwargs)
    return (result.get("text") or "").strip()
