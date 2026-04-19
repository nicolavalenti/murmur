import AppKit
import ApplicationServices

/// Simulates ⌘V in the currently focused app. Requires Accessibility permission
/// — macOS prompts on first use. After granting, the user must fully quit and
/// relaunch murmur for the permission to take effect.
enum Paster {
    /// Returns true if the OS believes we already have Accessibility permission.
    /// We use the non-prompting variant so we don't fire a dialog on every call;
    /// the real prompt happens when we post the CGEvent below.
    static var isTrusted: Bool {
        AXIsProcessTrusted()
    }

    /// Opens the System Settings pane where the user can enable Accessibility.
    static func requestPermission() {
        let prompt = "AXTrustedCheckOptionPrompt" as CFString
        let opts = [prompt: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(opts)
    }

    static func pasteCommandV() {
        let src = CGEventSource(stateID: .combinedSessionState)
        let vKey: CGKeyCode = 0x09  // ANSI 'v'

        let down = CGEvent(keyboardEventSource: src, virtualKey: vKey, keyDown: true)
        down?.flags = .maskCommand
        let up = CGEvent(keyboardEventSource: src, virtualKey: vKey, keyDown: false)
        up?.flags = .maskCommand

        // .cghidEventTap posts at the lowest system level so it reaches
        // whichever app currently has focus — same layer real keystrokes use.
        down?.post(tap: .cghidEventTap)
        up?.post(tap: .cghidEventTap)
    }
}
