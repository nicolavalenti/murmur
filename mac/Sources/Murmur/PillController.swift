import AppKit
import SwiftUI

enum PillState: Equatable {
    case hidden
    case recording(since: Date)
    case processing
    case done
    case error(String)
}

@MainActor
final class PillController: ObservableObject {
    @Published var state: PillState = .hidden
    /// 0.0 when silent, roughly 1.0 on loud speech. Drives waveform amplitude.
    @Published var level: Double = 0.0

    private var window: NSWindow?
    private let backend = BackendClient()
    private var stopTask: Task<Void, Never>?
    private var levelPoller: Task<Void, Never>?
    private var watchdog: Task<Void, Never>?
    private var targetApp: NSRunningApplication?

    func startRecording() {
        stopTask?.cancel()
        level = 0.0
        // Capture which app the user was in before we show the pill.
        targetApp = NSWorkspace.shared.frontmostApplication
        state = .recording(since: Date())
        show()
        Task {
            do { try await backend.startRecording() }
            catch { setError("start failed: \(error.localizedDescription)"); return }
            startLevelPolling()
        }
    }

    func stopRecording() {
        guard case .recording = state else { return }
        levelPoller?.cancel()
        state = .processing
        // Safety net: if the backend crashes and never responds, reset after 35s
        // (slightly longer than the 30s network timeout so the error surfaces first).
        watchdog = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 35_000_000_000)
            guard let self, !Task.isCancelled else { return }
            if case .processing = self.state { self.setError("timed out") }
        }
        stopTask = Task { [weak self] in
            guard let self else { return }
            do {
                let result = try await self.backend.stopRecording()
                if let t = result.elapsed_ms {
                    print("[murmur] swift received — transcribe: \(t["transcribe"] ?? -1)ms  polish: \(t["polish"] ?? -1)ms  total: \(t["total"] ?? -1)ms")
                }
                // Set clipboard from Swift — pyperclip can't reach the
                // macOS pasteboard when Python runs as a child process of a .app.
                let pb = NSPasteboard.general
                pb.clearContents()
                pb.setString(result.polished, forType: .string)
                self.watchdog?.cancel()
                self.state = .done
                // Re-activate the app the user was in before recording.
                // Without this, focus can be anywhere after 1-4s of processing.
                self.targetApp?.activate(options: .activateIgnoringOtherApps)
                try? await Task.sleep(nanoseconds: 200_000_000)
                Paster.pasteCommandV()
                try? await Task.sleep(nanoseconds: 600_000_000)
                if !Task.isCancelled { self.hide() }
            } catch {
                self.watchdog?.cancel()
                self.setError("stop failed: \(error.localizedDescription)")
            }
        }
    }

    private func startLevelPolling() {
        levelPoller = Task { [weak self] in
            // ~20Hz. The backend's RMS window is ~200ms, so polling faster
            // than this just returns near-duplicate values.
            while !Task.isCancelled {
                guard let self else { return }
                do {
                    let lv = try await self.backend.getLevel()
                    // Map raw RMS to 0–1. Saturates at ~0.08 RMS (normal speech)
                    // so typical talking reaches full amplitude instead of hovering
                    // at 50%. Quiet speech (0.02) still reads as ~0.2 — visible.
                    let normalized = min(1.0, max(0.0, (lv - 0.005) / 0.04))
                    // Slight gamma curve makes the response feel more linear
                    // perceptually (RMS is energy, loudness is log of energy).
                    let shaped = pow(normalized, 0.7)
                    // Smooth transitions so bars don't jitter between polls.
                    self.level = self.level * 0.5 + shaped * 0.5
                } catch {
                    // Don't spam errors — levels are best-effort.
                }
                try? await Task.sleep(nanoseconds: 50_000_000)  // 50ms
            }
        }
    }

    private func setError(_ msg: String) {
        print("[murmur] \(msg)")
        levelPoller?.cancel()
        state = .error(msg)
        Task {
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            hide()
        }
    }

    private func show() {
        if window == nil { window = makeWindow() }
        positionWindow()
        window?.orderFrontRegardless()
    }

    private func hide() {
        state = .hidden
        window?.orderOut(nil)
    }

    // Window is larger than the visible pill to give the SwiftUI-drawn
    // shadow room to bleed. The pill itself renders at pillSize, centered.
    private let windowSize = CGSize(width: 220, height: 60)

    private func positionWindow() {
        guard let window, let screen = NSScreen.main else { return }
        let visible = screen.visibleFrame
        let x = visible.midX - windowSize.width / 2
        let y = visible.minY + 16
        window.setFrame(
            NSRect(x: x, y: y, width: windowSize.width, height: windowSize.height),
            display: true
        )
    }

    private func makeWindow() -> NSWindow {
        let win = NSWindow(
            contentRect: NSRect(origin: .zero, size: windowSize),
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        win.level = .floating
        win.isOpaque = false
        win.backgroundColor = .clear
        // hasShadow = false: AppKit's window shadow is rectangular and would
        // show as a visible box around the pill. SwiftUI draws the shadow
        // inside the view instead, where it follows the rounded shape.
        win.hasShadow = false
        win.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        win.ignoresMouseEvents = true

        let host = NSHostingView(rootView: PillView().environmentObject(self))
        host.wantsLayer = true
        host.layer?.backgroundColor = .clear
        win.contentView = host
        return win
    }
}
