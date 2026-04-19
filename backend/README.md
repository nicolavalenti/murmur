# murmur — backend (M1)

Python backend for the murmur dictation tool. Records audio, transcribes with `mlx-whisper`, polishes with an OpenRouter LLM, copies to clipboard.

## Setup

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

First run will download the Whisper model (~1.5GB for `large-v3-turbo`) to the Hugging Face cache.

## Configure

Config lives at `~/.murmur/config.json`. It's created with defaults on first run.

Set your OpenRouter key either in the config file or as an env var:

```bash
export OPENROUTER_API_KEY=sk-or-...
```

## Test without the Swift UI — CLI harness

```bash
murmur-cli
```

Press Enter to start recording, Enter again to stop. Polished text is printed and copied to your clipboard.

> macOS will prompt for microphone permission the first time. Grant it to your terminal (iTerm/Terminal/VS Code).

## Run the HTTP server

```bash
murmur-server
```

Listens on `http://127.0.0.1:8765`. Endpoints:

| Method | Path              | Purpose |
|--------|-------------------|---------|
| GET    | `/status`         | health check, shows current config summary |
| GET    | `/settings`       | read full config (API key redacted) |
| POST   | `/settings`       | patch config (JSON body of any subset of fields) |
| POST   | `/start_recording`| begin capture |
| POST   | `/stop_recording` | stop, transcribe, polish, copy — returns `{raw, polished, elapsed_ms}` |

Quick smoke test:

```bash
curl -X POST http://127.0.0.1:8765/start_recording
# ...speak...
curl -X POST http://127.0.0.1:8765/stop_recording
```

## What's next (M2)

SwiftUI floating pill that drives these endpoints via a global hotkey.
