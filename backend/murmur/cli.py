"""Standalone CLI harness for testing the pipeline without the Swift frontend.

Press Enter to start recording. Press Enter again to stop. Polished text is
printed and copied to the clipboard.
"""
import sys
import time

import pyperclip

from . import config as config_module
from .audio import Recorder
from .polish import polish
from .transcribe import transcribe


def run_once(cfg: dict) -> None:
    rec = Recorder(sample_rate=cfg["sample_rate"])

    input("→ press Enter to START recording... ")
    rec.start()
    print("● recording... press Enter to STOP", end="", flush=True)
    input()

    t0 = time.perf_counter()
    audio = rec.stop()
    print(f"captured {len(audio) / cfg['sample_rate']:.1f}s of audio")

    print("… transcribing (first run may load the model for 5-15s)")
    t1 = time.perf_counter()
    raw = transcribe(audio, model=cfg["whisper_model"], sample_rate=cfg["sample_rate"])
    t2 = time.perf_counter()
    print(f"  raw ({int((t2 - t1) * 1000)}ms): {raw!r}")

    if cfg.get("polishing_model") and cfg.get("openrouter_api_key"):
        print("… polishing via OpenRouter")
        polished = polish(
            raw,
            model=cfg["polishing_model"],
            api_key=cfg["openrouter_api_key"],
            prompt=cfg["polishing_prompt"],
        )
    else:
        print("  (skipping polish — no model or API key set)")
        polished = raw
    t3 = time.perf_counter()

    pyperclip.copy(polished)
    print(f"\n✓ polished ({int((t3 - t2) * 1000)}ms): {polished}")
    print(f"✓ copied to clipboard · total {int((t3 - t0) * 1000)}ms")


def main() -> None:
    cfg = config_module.load()
    if not cfg.get("openrouter_api_key"):
        print("! OPENROUTER_API_KEY not set — polish step will be skipped.", file=sys.stderr)
        print(f"  Edit {config_module.CONFIG_PATH} or export OPENROUTER_API_KEY.\n", file=sys.stderr)
    try:
        while True:
            run_once(cfg)
            print("\n--- next round (Ctrl+C to quit) ---\n")
    except KeyboardInterrupt:
        print("\nbye.")


if __name__ == "__main__":
    main()
