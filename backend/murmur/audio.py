import threading
import numpy as np
import sounddevice as sd

_MAX_RECORDING_SECONDS = 600  # safety limit — releases mic if client disappears (10 min)


class Recorder:
    """Push-to-talk audio recorder. Captures to an in-memory float32 buffer at
    the configured sample rate, mono. Call start() then stop() to retrieve
    a single 1-D numpy array suitable for mlx-whisper."""

    def __init__(self, sample_rate: int = 16000, gain: float = 1.0):
        self.sample_rate = sample_rate
        self._gain = max(0.1, gain)
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._watchdog: threading.Timer | None = None

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"[audio] status: {status}")
        with self._lock:
            amplified = np.clip(indata * self._gain, -1.0, 1.0)
            self._frames.append(amplified.reshape(-1))

    def start(self) -> None:
        if self._stream is not None:
            raise RuntimeError("recorder already running")
        self._frames = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        self._watchdog = threading.Timer(_MAX_RECORDING_SECONDS, self._timeout)
        self._watchdog.daemon = True
        self._watchdog.start()

    def _timeout(self) -> None:
        print(f"[audio] recording exceeded {_MAX_RECORDING_SECONDS}s — auto-stopping to release mic")
        self._close_stream()

    def _close_stream(self) -> None:
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def stop(self) -> np.ndarray:
        if self._stream is None and not self._frames:
            raise RuntimeError("recorder not running")
        self._close_stream()
        with self._lock:
            if not self._frames:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(self._frames, axis=0)

    def __del__(self) -> None:
        self._close_stream()

    @property
    def is_running(self) -> bool:
        return self._stream is not None

    def current_level(self) -> float:
        """RMS of the most recent ~100ms of captured audio, 0.0 if nothing yet.

        Cheap enough to poll at 20Hz. We read only the tail of the frame list
        to keep this O(recent) instead of O(whole recording)."""
        with self._lock:
            if not self._frames:
                return 0.0
            # sounddevice callback buffer is ~1024 samples @ 16kHz = 64ms;
            # taking the last ~3 chunks gives a stable ~200ms window.
            tail = self._frames[-3:]
        recent = np.concatenate(tail).astype(np.float32, copy=False)
        if recent.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(recent * recent)))
