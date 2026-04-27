import numpy as np

_LOADED: dict[str, object] = {}


def transcribe(
    audio: np.ndarray,
    model: str,
    sample_rate: int = 16000,
    language: str = "en",
    vocabulary: list[str] | None = None,
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
    if vocabulary:
        # initial_prompt seeds Whisper's decoder context. The model treats it as
        # "what was said just before this audio," which biases spelling and word
        # choice without forcing it. Phrased as a sentence so it parses naturally.
        kwargs["initial_prompt"] = "Vocabulary includes: " + ", ".join(vocabulary) + "."
    result = mlx_whisper.transcribe(audio, **kwargs)
    return (result.get("text") or "").strip()
