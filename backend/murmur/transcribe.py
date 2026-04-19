import numpy as np

_LOADED: dict[str, object] = {}


def transcribe(audio: np.ndarray, model: str, sample_rate: int = 16000) -> str:
    """Run mlx-whisper on an in-memory float32 mono array.

    mlx-whisper expects 16kHz mono float32. We assume the recorder already
    captured at 16kHz; if that ever changes, resample here before calling.
    """
    import mlx_whisper  # imported lazily so the server starts fast

    if sample_rate != 16000:
        raise ValueError("mlx-whisper expects 16kHz audio")

    audio = audio.astype(np.float32, copy=False)
    result = mlx_whisper.transcribe(audio, path_or_hf_repo=model)
    return (result.get("text") or "").strip()
