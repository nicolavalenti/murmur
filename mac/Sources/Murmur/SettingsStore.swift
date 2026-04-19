import AppKit
import Combine
import HotKey

/// User-visible settings. Hotkey is Swift-side only (UserDefaults).
/// Polishing model is read from the backend's /settings endpoint.
@MainActor
final class SettingsStore: ObservableObject {
    /// nil means modifier-only mode (no key required).
    @Published var hotkeyKey: Key? {
        didSet {
            let stored = hotkeyKey.map { Int($0.carbonKeyCode) } ?? -1
            UserDefaults.standard.set(stored, forKey: "hotkey.keyCode")
        }
    }
    @Published var modifiers: NSEvent.ModifierFlags {
        didSet { UserDefaults.standard.set(Int(modifiers.rawValue), forKey: "hotkey.modifiers") }
    }
    @Published var polishingModel: String = "—"
    @Published var inputGain: Double {
        didSet {
            UserDefaults.standard.set(inputGain, forKey: "input.gain")
            Task { try? await backend.updateGain(inputGain) }
        }
    }

    private let backend = BackendClient()

    init() {
        let defaults = UserDefaults.standard
        let storedCode = defaults.object(forKey: "hotkey.keyCode") as? Int
        if let storedCode, storedCode == -1 {
            self.hotkeyKey = nil  // modifier-only
        } else if let storedCode, storedCode >= 0, let k = Key(carbonKeyCode: UInt32(storedCode)) {
            self.hotkeyKey = k
        } else {
            self.hotkeyKey = .space
        }
        if let raw = defaults.object(forKey: "hotkey.modifiers") as? Int {
            self.modifiers = NSEvent.ModifierFlags(rawValue: UInt(raw))
        } else {
            self.modifiers = [.control, .option]
        }
        self.inputGain = defaults.object(forKey: "input.gain") as? Double ?? 1.0
    }

    func refreshModel() {
        Task { [weak self] in
            guard let self else { return }
            // Retry for up to ~15 seconds — the backend process needs a moment
            // to start uvicorn after the app launches.
            let delays: [UInt64] = [500, 1000, 2000, 3000, 4000, 5000]
            for (i, delay) in delays.enumerated() {
                do {
                    let s = try await self.backend.getSettings()
                    self.polishingModel = s.polishing_model ?? "—"
                    if let gain = s.input_gain { self.inputGain = gain }
                    return
                } catch {
                    if i == delays.count - 1 {
                        self.polishingModel = "(backend not ready)"
                    } else {
                        try? await Task.sleep(nanoseconds: delay * 1_000_000)
                    }
                }
            }
        }
    }
}

/// Keys we offer in the picker. Keep it short — full keyboard would be noise.
/// `.none` means modifier-only mode (no key required — hold modifier to record).
enum HotkeyKeyOption: String, CaseIterable, Identifiable {
    case none = "Modifier only"
    case space = "Space"
    case f1 = "F1"
    case f2 = "F2"
    case f3 = "F3"
    case f4 = "F4"
    case f5 = "F5"
    case f6 = "F6"
    case f7 = "F7"
    case f8 = "F8"
    case f9 = "F9"
    case f10 = "F10"
    case f11 = "F11"
    case f12 = "F12"
    case backtick = "`"

    var id: String { rawValue }

    var key: Key? {
        switch self {
        case .none: return nil
        case .space: return .space
        case .f1: return .f1
        case .f2: return .f2
        case .f3: return .f3
        case .f4: return .f4
        case .f5: return .f5
        case .f6: return .f6
        case .f7: return .f7
        case .f8: return .f8
        case .f9: return .f9
        case .f10: return .f10
        case .f11: return .f11
        case .f12: return .f12
        case .backtick: return .grave
        }
    }

    static func from(key: Key?) -> HotkeyKeyOption {
        guard let key else { return .none }
        return allCases.first { $0.key == key } ?? .space
    }
}
