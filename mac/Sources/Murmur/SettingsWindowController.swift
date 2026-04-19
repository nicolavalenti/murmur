import AppKit
import SwiftUI

/// Manages the single Settings window. Reusing one window means clicking
/// the app / choosing Settings repeatedly just brings the existing window
/// forward instead of stacking duplicates.
@MainActor
final class SettingsWindowController {
    private var window: NSWindow?
    private let store: SettingsStore

    init(store: SettingsStore) {
        self.store = store
    }

    func show() {
        if window == nil {
            let view = SettingsView(store: store)
            let hosting = NSHostingController(rootView: view)
            let win = NSWindow(contentViewController: hosting)
            win.title = "Murmur"
            win.styleMask = [.titled, .closable]
            win.isReleasedWhenClosed = false
            win.center()
            window = win
        }
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
        store.refreshModel()
    }
}
