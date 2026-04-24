import time
from typing import Any

import pyperclip
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import config as config_module
from .audio import Recorder
from .polish import polish, GROQ_URL
from .transcribe import transcribe

app = FastAPI(title="murmur", version="0.1.0")

# Process-level state. Single-user tool, so one recorder is fine.
_recorder: Recorder | None = None
_cfg: dict[str, Any] = config_module.load()


class TranscriptResponse(BaseModel):
    raw: str
    polished: str
    elapsed_ms: dict[str, int]


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


@app.get("/status")
def status() -> dict[str, Any]:
    return {
        "ok": True,
        "recording": _recorder is not None and _recorder.is_running,
        "whisper_model": _cfg["whisper_model"],
        "polishing_model": _cfg["polishing_model"],
    }


@app.get("/level")
def level() -> dict[str, float]:
    """Current audio RMS while recording. Returns 0.0 when idle.
    Polled by the Swift UI to drive the reactive waveform."""
    if _recorder is None or not _recorder.is_running:
        return {"level": 0.0}
    return {"level": _recorder.current_level()}


@app.get("/settings")
def get_settings() -> dict[str, Any]:
    safe = dict(_cfg)
    if safe.get("openrouter_api_key"):
        safe["openrouter_api_key"] = "sk-or-***"
    if safe.get("groq_api_key"):
        safe["groq_api_key"] = "gsk-***"
    return safe


@app.post("/settings")
def update_settings(patch: SettingsPatch) -> dict[str, Any]:
    global _cfg
    updates = {k: v for k, v in patch.model_dump().items() if v is not None}
    _cfg = {**_cfg, **updates}
    config_module.save(_cfg)
    return get_settings()


@app.post("/start_recording")
def start_recording() -> dict[str, Any]:
    global _recorder
    if _recorder is not None and _recorder.is_running:
        _recorder.stop()  # force-clear a ghost recording (e.g. after app crash)
        _recorder = None
    _recorder = Recorder(sample_rate=_cfg["sample_rate"], gain=_cfg.get("input_gain", 1.0))
    _recorder.start()
    return {"recording": True, "started_at": time.time()}


@app.post("/stop_recording", response_model=TranscriptResponse)
def stop_recording() -> TranscriptResponse:
    global _recorder
    if _recorder is None:
        raise HTTPException(status_code=409, detail="not recording")
    # recorder may have been auto-stopped by the watchdog (max duration exceeded)
    # but frames are still in memory — proceed to transcribe what was captured

    t0 = time.perf_counter()
    audio = _recorder.stop()
    _recorder = None
    t_stop = time.perf_counter()

    # Skip transcription for very short clips — Whisper hallucinates on < 0.5s of audio
    sample_rate = _cfg["sample_rate"]
    audio_duration_s = len(audio) / sample_rate if len(audio) > 0 else 0
    if audio_duration_s < 0.5:
        return TranscriptResponse(raw="", polished="", elapsed_ms={"stop": 0, "transcribe": 0, "polish": 0, "clipboard": 0, "total": 0})

    raw = transcribe(audio, model=_cfg["whisper_model"], sample_rate=_cfg["sample_rate"])
    t_trans = time.perf_counter()

    # Sanity check: Whisper hallucinates long text from short audio.
    # If transcript has far more words than the audio duration could contain, discard it.
    max_plausible_words = int(audio_duration_s * 4)  # ~240 wpm upper bound
    if len(raw.split()) > max_plausible_words:
        raw = ""

    groq_key = _cfg.get("groq_api_key", "")
    polish_key = groq_key if groq_key else _cfg.get("openrouter_api_key", "")
    polish_url = GROQ_URL if groq_key else None
    polished = polish(
        raw,
        model=_cfg.get("polishing_model") or None,
        api_key=polish_key,
        prompt=_cfg["polishing_prompt"],
        **{"url": polish_url} if polish_url else {},
    )
    t_polish = time.perf_counter()

    try:
        pyperclip.copy(polished)
    except Exception:
        pass  # clipboard is set by the Swift app; this is best-effort only
    t_clip = time.perf_counter()

    elapsed = {
        "stop": int((t_stop - t0) * 1000),
        "transcribe": int((t_trans - t_stop) * 1000),
        "polish": int((t_polish - t_trans) * 1000),
        "clipboard": int((t_clip - t_polish) * 1000),
        "total": int((t_clip - t0) * 1000),
    }
    log_line = (
        f"transcribe: {elapsed['transcribe']}ms  "
        f"polish: {elapsed['polish']}ms  "
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


def main() -> None:
    import uvicorn
    uvicorn.run("murmur.server:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
