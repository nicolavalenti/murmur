import time
from typing import Any

import pyperclip
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import config as config_module
from .audio import Recorder
from .polish import polish
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
        raise HTTPException(status_code=409, detail="already recording")
    _recorder = Recorder(sample_rate=_cfg["sample_rate"], gain=_cfg.get("input_gain", 1.0))
    _recorder.start()
    return {"recording": True, "started_at": time.time()}


@app.post("/stop_recording", response_model=TranscriptResponse)
def stop_recording() -> TranscriptResponse:
    global _recorder
    if _recorder is None or not _recorder.is_running:
        raise HTTPException(status_code=409, detail="not recording")

    t0 = time.perf_counter()
    audio = _recorder.stop()
    _recorder = None
    t_stop = time.perf_counter()

    raw = transcribe(audio, model=_cfg["whisper_model"], sample_rate=_cfg["sample_rate"])
    t_trans = time.perf_counter()

    polished = polish(
        raw,
        model=_cfg.get("polishing_model") or None,
        api_key=_cfg.get("openrouter_api_key", ""),
        prompt=_cfg["polishing_prompt"],
    )
    t_polish = time.perf_counter()

    pyperclip.copy(polished)
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
