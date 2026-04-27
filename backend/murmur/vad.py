import numpy as np


def trim_silence(audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    """Trim leading and trailing silence from a mono float32 array.

    Cuts dead air at the start (between hotkey press and speech) and end
    (between speech and hotkey release) so Whisper transcribes less audio.
    Pure numpy — no dependencies, ~1ms on a 10s clip.

    Strategy: split into 50ms windows, compute RMS energy per window, mark any
    window above an adaptive threshold as "speech," keep everything from the
    first to the last speech window plus 200ms padding on each side.

    Threshold is adaptive (5% of the loudest window) so it tracks the user's
    actual speech level instead of assuming a fixed dB floor — robust across
    quiet rooms, loud rooms, low gain, high gain. An absolute floor of 0.005
    catches the all-silence case where adaptive would mark the loudest piece
    of background hum as 'speech.'
    """
    if audio.size == 0:
        return audio

    window_size = sample_rate // 20  # 50ms
    if audio.size < window_size * 2:
        return audio  # under 100ms — nothing to gain

    n_windows = audio.size // window_size
    usable_len = n_windows * window_size
    windows = audio[:usable_len].reshape(n_windows, window_size)
    rms = np.sqrt(np.mean(windows.astype(np.float32) ** 2, axis=1))

    threshold = max(0.005, float(rms.max()) * 0.05)
    speech = np.where(rms > threshold)[0]
    if speech.size == 0:
        return np.zeros(0, dtype=np.float32)  # entirely silent

    pad = 4  # 4 windows = 200ms padding so we don't clip first/last phoneme
    start = max(0, int(speech[0]) - pad) * window_size
    end = min(n_windows, int(speech[-1]) + 1 + pad) * window_size
    return audio[start:end]
