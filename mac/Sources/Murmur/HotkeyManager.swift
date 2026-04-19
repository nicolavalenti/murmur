import AppKit
import HotKey

/// Registers a configurable push-to-talk hotkey and fires onPress/onRelease.
///
/// Supports three modes:
///   - Key + modifiers  e.g. ⌥Space, ⌃⌥F5
///   - Bare key          e.g. F5 alone (no modifier required)
///   - Modifier-only     e.g. just Option held down (pass key: nil)
///
/// Uses NSEvent global monitors so all three modes work without Carbon's
/// requirement for at least one modifier. The app already holds Accessibility
/// permission (needed for ⌘V simulation), which covers global key monitoring.
final class HotkeyManager {
    private var monitors: [Any] = []
    private var isPressed = false
    private let onPress: () -> Void
    private let onRelease: () -> Void

    init(key: Key?, modifiers: NSEvent.ModifierFlags,
         onPress: @escaping () -> Void, onRelease: @escaping () -> Void) {
        self.onPress = onPress
        self.onRelease = onRelease
        reload(key: key, modifiers: modifiers)
    }

    func reload(key: Key?, modifiers: NSEvent.ModifierFlags) {
        for m in monitors { NSEvent.removeMonitor(m) }
        monitors = []
        isPressed = false

        let relevantMods = modifiers.intersection([.control, .option, .shift, .command, .function])

        if let key {
            // Key (+ optional modifiers) — match keyDown/keyUp by hardware key code
            let keyCode = UInt16(key.carbonKeyCode)

            let down = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] event in
                guard let self, !self.isPressed, event.keyCode == keyCode else { return }
                // If modifiers are required, all of them must be held; no extras allowed.
                let flags = event.modifierFlags.intersection([.control, .option, .shift, .command, .function])
                guard flags == relevantMods else { return }
                self.isPressed = true
                self.onPress()
            }
            let up = NSEvent.addGlobalMonitorForEvents(matching: .keyUp) { [weak self] event in
                guard let self, self.isPressed, event.keyCode == keyCode else { return }
                self.isPressed = false
                self.onRelease()
            }
            [down, up].compactMap { $0 }.forEach { monitors.append($0) }
        } else {
            // Modifier-only mode — fire when the chosen modifier(s) are all held down
            guard !relevantMods.isEmpty else { return }

            let monitor = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged) { [weak self] event in
                guard let self else { return }
                let active = event.modifierFlags.intersection([.control, .option, .shift, .command, .function])
                let allHeld = relevantMods.isSubset(of: active)
                if allHeld && !self.isPressed {
                    self.isPressed = true
                    self.onPress()
                } else if !allHeld && self.isPressed {
                    self.isPressed = false
                    self.onRelease()
                }
            }
            if let monitor { monitors.append(monitor) }
        }
    }

    deinit {
        for m in monitors { NSEvent.removeMonitor(m) }
    }
}
