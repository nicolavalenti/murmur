"""Benchmark transcription time with and without VAD trim.

Records one ~32s clip from the default mic, slices it into nominal 10/20/30s
subclips (each carrying the silence padding from the original), and times
mlx-whisper on each — once on the raw audio, once on VAD-trimmed audio.

Run:
    cd ~/Projects/murmur/backend
    source .venv/bin/activate
    python bench_vad.py
"""

import time
import numpy as np
import sounddevice as sd

from murmur import config as config_module
from murmur.transcribe import transcribe
from murmur.vad import trim_silence

SR = 16000
RECORD_SECONDS = 32

cfg = config_module.load()
print(f"Whisper model: {cfg['whisper_model']}")
print()
print("INSTRUCTIONS:")
print("  1. Press ENTER")
print("  2. Stay silent for ~3 seconds (this is the pre-roll silence VAD will trim)")
print("  3. Read aloud for ~25 seconds (any English text — paragraph from a book is fine)")
print("  4. Stop talking, stay silent for ~3 seconds (post-roll)")
print()
input("Press ENTER when ready...")

print(f"Recording {RECORD_SECONDS}s — speak now (after the silence pre-roll)...")
audio = sd.rec(RECORD_SECONDS * SR, samplerate=SR, channels=1, dtype="float32", blocking=True).flatten()
print(f"Captured {audio.size / SR:.1f}s\n")

# Warm-up: first transcribe loads the mlx-whisper model from disk, which is slow
# and would distort all subsequent measurements. Throwaway call on a short slice.
print("Warming up mlx-whisper (loading model)...")
t0 = time.perf_counter()
_ = transcribe(audio[: 2 * SR], model=cfg["whisper_model"], sample_rate=SR, language="en")
print(f"Warm-up done in {(time.perf_counter() - t0)*1000:.0f}ms\n")

results = []
for nominal in [10, 20, 30]:
    clip = audio[: nominal * SR]

    t0 = time.perf_counter()
    txt_raw = transcribe(clip, model=cfg["whisper_model"], sample_rate=SR, language="en")
    t_raw = time.perf_counter() - t0

    trimmed = trim_silence(clip, sample_rate=SR)
    kept_pct = trimmed.size / clip.size * 100

    t0 = time.perf_counter()
    txt_trim = transcribe(trimmed, model=cfg["whisper_model"], sample_rate=SR, language="en")
    t_trim = time.perf_counter() - t0

    saved_ms = int((t_raw - t_trim) * 1000)
    saved_pct = (t_raw - t_trim) / t_raw * 100 if t_raw > 0 else 0
    results.append((nominal, kept_pct, t_raw, t_trim, saved_ms, saved_pct))

    print(f"--- {nominal}s clip ---")
    print(f"  raw audio: {t_raw*1000:.0f}ms transcribe")
    print(f"  trimmed ({kept_pct:.0f}% kept): {t_trim*1000:.0f}ms transcribe")
    print(f"  saved: {saved_ms}ms ({saved_pct:.0f}%)")
    print(f"  raw text:     {txt_raw[:80]!r}")
    print(f"  trimmed text: {txt_trim[:80]!r}")
    print()

print("\n=== SUMMARY ===")
print(f"{'len':>5} {'kept':>6} {'raw':>9} {'trim':>9} {'saved':>14}")
print("-" * 50)
for nominal, kept_pct, t_raw, t_trim, saved_ms, saved_pct in results:
    print(f"{nominal:>3}s   {kept_pct:>5.0f}%  {t_raw*1000:>6.0f}ms  {t_trim*1000:>6.0f}ms   {saved_ms:>5d}ms ({saved_pct:>3.0f}%)")
