# murmur — macOS frontend

Menu-bar SwiftUI app that drives the Python backend via a global hotkey.

## Requirements

- macOS 13+ (Ventura) on Apple Silicon
- Xcode command line tools (`xcode-select --install`)
- Python backend installed at `~/Projects/murmur/backend` with a working `.venv` (see `../backend/README.md`)

## Install as a .app (recommended)

From `mac/`:

```bash
./build-app.sh
mv build/Murmur.app /Applications/
```

Then double-click **Murmur** in `/Applications` (or use Spotlight). The app:
- Auto-starts the Python backend as a child process
- Shows a `waveform` icon in the menu bar (no Dock icon)
- Auto-terminates the backend when you quit

### First-launch permissions

macOS will prompt for two permissions on first use:

1. **Microphone** — granted to the backend Python process on first record
2. **Accessibility** — needed for auto-paste (simulating ⌘V). Grant in System Settings → Privacy & Security → Accessibility, then fully quit and relaunch Murmur

### Where the backend lives

The app expects your venv at `~/Projects/murmur/backend/.venv`. If your repo is elsewhere, set `MURMUR_BACKEND_DIR` in your environment before launching.

## Dev build (no bundle)

For quick iteration without rebuilding the .app:

```bash
# Terminal 1: backend
cd ../backend && source .venv/bin/activate && murmur-server

# Terminal 2: frontend
swift run
```

## Usage

**Hold** `⌃⌥Space` (Control + Option + Space). Pill slides up from the bottom of your screen, shows a waveform + timer. **Release** to stop. After processing (~1–4s), polished text is pasted into the focused app.

## Quitting

Menu-bar icon → Quit. The backend process shuts down with the app.

## Changing the hotkey

Edit `Sources/Murmur/HotkeyManager.swift`:

```swift
hotkey = HotKey(key: .space, modifiers: [.control, .option])
```

`.space` can be any `Key` (e.g. `.return`, `.f13`). Modifiers combine `.control` `.option` `.command` `.shift`.

## Gotchas

- **Backend venv must exist** at `~/Projects/murmur/backend/.venv` or Murmur can't start the server. Set `MURMUR_BACKEND_DIR` to override.
- **Accessibility permission** must be granted AND the app must be fully relaunched for auto-paste to start working.
- If the `.app` refuses to launch with "damaged", re-run `./build-app.sh` — ad-hoc codesigning happens during the build step.
