import json
import os
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".murmur"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS: dict[str, Any] = {
    "whisper_model": "mlx-community/whisper-large-v3-turbo",
    "openrouter_api_key": os.environ.get("OPENROUTER_API_KEY", ""),
    "polishing_model": "google/gemini-2.0-flash-001",
    "polishing_prompt": (
        "Clean up this voice transcript. Fix punctuation and capitalization. "
        "Remove filler words like \"um\", \"uh\", \"like\" when used as filler. "
        "Preserve the exact meaning and tone. Do not summarize or rephrase. "
        "Return only the cleaned text with no preamble."
    ),
    "auto_paste": False,
    "hotkey": "fn",
    "sample_rate": 16000,
    "input_gain": 1.0,
}


def load() -> dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save(DEFAULTS)
        return dict(DEFAULTS)
    with CONFIG_PATH.open() as f:
        stored = json.load(f)
    return {**DEFAULTS, **stored}


def save(cfg: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w") as f:
        json.dump(cfg, f, indent=2)
