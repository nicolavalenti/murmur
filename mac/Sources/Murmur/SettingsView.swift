import SwiftUI
import AppKit
import HotKey

struct SettingsView: View {
    @ObservedObject var store: SettingsStore

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Welcome to Murmur")
                    .font(.system(size: 22, weight: .semibold))
                Text("Hold your hotkey, speak, release. Text lands wherever your cursor is.")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }

            Divider()

            VStack(alignment: .leading, spacing: 6) {
                Text("Polishing model")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.secondary)
                Text(store.polishingModel)
                    .font(.system(.body, design: .monospaced))
                    .textSelection(.enabled)
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("Hotkey")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.secondary)
                HotkeyRecorderView(store: store)
                Text("Click the button, then press any key or key combination.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("Input gain")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(String(format: "%.1f×", store.inputGain))
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
                Slider(value: $store.inputGain, in: 1.0...5.0, step: 0.5)
                Text("Boost microphone sensitivity. Useful if you're not close to your Mac.")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 0)
        }
        .padding(24)
        .frame(width: 420, height: 380)
        .onAppear { store.refreshModel() }
    }
}

/// Click to enter recording mode, press any key/combo, done.
/// Supports bare keys (F5), combos (⌥Space), modifier-only (fn, ⌥), including the FN key.
@MainActor
struct HotkeyRecorderView: View {
    @ObservedObject var store: SettingsStore
    @State private var isRecording = false
    @State private var localMonitor: Any?
    @State private var globalMonitor: Any?
    @State private var pendingModifiers: NSEvent.ModifierFlags = []

    var body: some View {
        Button(action: toggleRecording) {
            HStack(spacing: 8) {
                Image(systemName: isRecording ? "record.circle.fill" : "keyboard")
                    .foregroundStyle(isRecording ? .red : .secondary)
                Text(isRecording ? "Press any key…" : hotkeyLabel)
                    .frame(minWidth: 120, alignment: .leading)
                if isRecording {
                    Text("Esc to cancel")
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background(isRecording ? Color.red.opacity(0.07) : Color.secondary.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay(
                RoundedRectangle(cornerRadius: 7)
                    .stroke(isRecording ? Color.red.opacity(0.35) : Color.secondary.opacity(0.2), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }

    private var hotkeyLabel: String {
        var parts: [String] = []
        if store.modifiers.contains(.function) { parts.append("fn") }
        if store.modifiers.contains(.control)  { parts.append("⌃") }
        if store.modifiers.contains(.option)   { parts.append("⌥") }
        if store.modifiers.contains(.shift)    { parts.append("⇧") }
        if store.modifiers.contains(.command)  { parts.append("⌘") }
        if let key = store.hotkeyKey {
            parts.append(HotkeyKeyOption.from(key: key).rawValue)
        }
        return parts.isEmpty ? "—" : parts.joined(separator: " ")
    }

    private func toggleRecording() {
        if isRecording { stopRecording(); return }
        isRecording = true
        pendingModifiers = []

        // Local monitor: fires when our Settings window has focus
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .flagsChanged]) { event in
            Task { @MainActor in self.handleEvent(event) }
            return nil  // swallow so the key doesn't type into any field
        }
        // Global monitor: fires when another app has focus
        globalMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.keyDown, .flagsChanged]) { event in
            Task { @MainActor in self.handleEvent(event) }
        }
    }

    private func handleEvent(_ event: NSEvent) {
        guard isRecording else { return }

        if event.type == .keyDown {
            if event.keyCode == 53 { stopRecording(); return }  // Escape = cancel
            let mods = event.modifierFlags.intersection([.control, .option, .shift, .command, .function])
            if let key = Key(carbonKeyCode: UInt32(event.keyCode)) {
                store.hotkeyKey = key
                store.modifiers = mods
            }
            pendingModifiers = []
            stopRecording()
        } else if event.type == .flagsChanged {
            let mods = event.modifierFlags.intersection([.control, .option, .shift, .command, .function])
            if !mods.isEmpty {
                // Modifier pressed — remember it in case no key follows
                pendingModifiers = mods
            } else if !pendingModifiers.isEmpty {
                // All modifiers released with no key pressed → modifier-only hotkey
                store.hotkeyKey = nil
                store.modifiers = pendingModifiers
                pendingModifiers = []
                stopRecording()
            }
        }
    }

    private func stopRecording() {
        isRecording = false
        pendingModifiers = []
        if let m = localMonitor  { NSEvent.removeMonitor(m); localMonitor = nil }
        if let m = globalMonitor { NSEvent.removeMonitor(m); globalMonitor = nil }
    }
}
