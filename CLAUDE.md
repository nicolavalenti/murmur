# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (Python)

```bash
cd backend
source .venv/bin/activate

# Run the server directly (normally started automatically by the Swift app)
murmur-server

# One-shot CLI transcription (microphone → stdout)
murmur-cli

# Reinstall after dependency changes
pip install -e .
```

### Mac app (Swift)

All commands run from `mac/`:

```bash
# Build release binary + assemble .app bundle + sign
./build-app.sh

# Install (quit the running app first)
rm -rf /Applications/Murmur.app && cp -R build/Murmur.app /Applications/

# Compile only (faster, no bundle)
swift build -c release

# Debug build
swift build
```

There are no automated tests in either component.

## Architecture

Murmur is two separate processes: a Python FastAPI server and a SwiftUI menu-bar app. They communicate over localhost HTTP.

### Flow

```
hold hotkey → startRecording() → POST /start_recording
speak       → GET /level (polled 20Hz) → waveform amplitude
release     → POST /stop_recording → transcribe (mlx-whisper) → polish (OpenRouter) → JSON
             Swift sets clipboard (NSPasteboard) → reactivates original app → simulates ⌘V
```

### Python backend (`backend/murmur/`)

- `server.py` — FastAPI app. Single-user; all state is module-level (`_recorder`, `_cfg`). Endpoints: `/start_recording`, `/stop_recording`, `/level`, `/settings` (GET/POST), `/status`.
- `audio.py` — `Recorder` class wrapping sounddevice; records float32 mono at 16kHz into a list of numpy arrays.
- `transcribe.py` — thin wrapper around `mlx_whisper.transcribe`. Lazy-imports mlx_whisper so server startup is fast. Expects 16kHz audio.
- `polish.py` — sends raw transcript to OpenRouter via httpx. Skipped if `model` is falsy.
- `config.py` — loads/saves `~/.murmur/config.json`. Falls back to env vars.

Config file lives at `~/.murmur/config.json`. Override backend dir with `MURMUR_BACKEND_DIR` env var (default: `~/Projects/murmur/backend`).

### Swift app (`mac/Sources/Murmur/`)

- `AppDelegate.swift` — wires everything together. Starts `BackendProcess`, creates `PillController` and `HotkeyManager`, owns `SettingsStore` and `SettingsWindowController`.
- `BackendProcess.swift` — spawns `murmur-server` via `/bin/zsh -lc` (login shell for PATH). Uses `exec` so SIGTERM on app quit reaches uvicorn directly.
- `PillController.swift` — state machine (`hidden → recording → processing → done/error → hidden`). Owns the floating pill window. Captures `frontmostApplication` before recording, reactivates it before pasting.
- `HotkeyManager.swift` — wraps the HotKey package (Carbon RegisterEventHotKey). Reconfigurable at runtime via `reload(key:modifiers:)` — replacing the `HotKey` instance unregisters the old Carbon binding.
- `SettingsStore.swift` — `@MainActor ObservableObject`. Holds hotkey config (persisted to UserDefaults) and polishing model name (fetched from `/settings`). Changing key/modifiers publishes to Combine, debounced 150ms before HotkeyManager reload.
- `BackendClient.swift` — `actor` wrapping URLSession. All HTTP calls to the backend.
- `Paster.swift` — CGEvent simulation of ⌘V at `.cghidEventTap` level. Requires Accessibility permission.
- `PillView.swift` / `Waveform.swift` — SwiftUI floating indicator. Window is borderless, `level = .floating`, `hasShadow = false` (shadow is drawn inside SwiftUI to follow the pill shape).

### Key constraints

- **Accessibility permission** is tied to the app's code signature. Rebuilding with ad-hoc signing (`--sign -`) revokes it every time. Use the `Murmur Dev` self-signed cert in Keychain Access. The build script auto-detects it.
- **Clipboard must be set from Swift** (NSPasteboard), not from Python. pyperclip can't reach the macOS pasteboard when Python runs as a child process of a `.app`.
- **`LSUIElement = true`** in Info.plist makes this a menu-bar-only app (no Dock icon). `applicationShouldHandleReopen` is the only way back in when the app is already running.
- The Swift app is an SPM executable (`main.swift` with top-level code), not a `@main` struct — this allows setting `activationPolicy(.accessory)` before the run loop starts.
