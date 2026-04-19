import AppKit
import Combine

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var pillController: PillController!
    private var hotkeyManager: HotkeyManager!
    private var statusItem: NSStatusItem!
    private let backend = BackendProcess()
    private let settingsStore = SettingsStore()
    private lazy var settingsWindow = SettingsWindowController(store: settingsStore)
    private var cancellables = Set<AnyCancellable>()

    func applicationDidFinishLaunching(_ notification: Notification) {
        backend.start()
        settingsStore.refreshModel()

        pillController = PillController()

        hotkeyManager = HotkeyManager(
            key: settingsStore.hotkeyKey,
            modifiers: settingsStore.modifiers,
            onPress: { [weak self] in
                Task { @MainActor in self?.pillController.startRecording() }
            },
            onRelease: { [weak self] in
                Task { @MainActor in self?.pillController.stopRecording() }
            }
        )

        // Re-register the Carbon hotkey whenever the user picks a new key or
        // toggles modifiers. Debounce so toggling several checkboxes at once
        // doesn't register/unregister in a tight loop.
        Publishers.CombineLatest(
            settingsStore.$hotkeyKey,
            settingsStore.$modifiers
        )
        .dropFirst()
        .debounce(for: .milliseconds(150), scheduler: DispatchQueue.main)
        .sink { [weak self] key, mods in
            self?.hotkeyManager.reload(key: key, modifiers: mods)
        }
        .store(in: &cancellables)

        setupMenuBar()

        if !Paster.isTrusted {
            showAccessibilityAlert()
        }

        print("murmur ready. Hold hotkey to dictate.")
    }

    func applicationWillTerminate(_ notification: Notification) {
        backend.stop()
    }

    /// Clicking Murmur in Finder/Dock/Spotlight while already running lands here.
    /// Without this, a `.accessory` app does nothing on reopen.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        settingsWindow.show()
        return true
    }

    private func showAccessibilityAlert() {
        let alert = NSAlert()
        alert.messageText = "Accessibility permission required"
        alert.informativeText = "Murmur needs Accessibility access to paste transcribed text into other apps.\n\nClick OK to open System Settings → Privacy & Security → Accessibility, enable Murmur, then quit and relaunch it."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Open Settings")
        alert.addButton(withTitle: "Later")
        if alert.runModal() == .alertFirstButtonReturn {
            Paster.requestPermission()
        }
    }

    private func setupMenuBar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            let icon = NSImage(named: "murmur_menubar") ?? NSImage(systemSymbolName: "waveform", accessibilityDescription: "murmur")
            icon?.isTemplate = true
            button.image = icon
        }
        let menu = NSMenu()
        menu.addItem(withTitle: "murmur", action: nil, keyEquivalent: "")
        menu.addItem(.separator())

        let settingsItem = NSMenuItem(title: "Settings…", action: #selector(openSettings), keyEquivalent: ",")
        settingsItem.target = self
        menu.addItem(settingsItem)

        if !Paster.isTrusted {
            menu.addItem(.separator())
            let item = NSMenuItem(title: "⚠️ Accessibility not granted", action: #selector(openAccessibilitySettings), keyEquivalent: "")
            item.target = self
            menu.addItem(item)
        }
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let forceQuitItem = NSMenuItem(title: "Force Quit", action: #selector(forceQuit), keyEquivalent: "")
        forceQuitItem.target = self
        menu.addItem(forceQuitItem)
        statusItem.menu = menu
    }

    @objc private func openSettings() {
        settingsWindow.show()
    }

    @objc private func openAccessibilitySettings() {
        Paster.requestPermission()
    }

    @objc private func forceQuit() {
        backend.stop()
        exit(0)
    }
}
