import AppKit

// SPM executables with top-level code run directly. We orchestrate NSApp
// ourselves instead of using @main so we can set activation policy BEFORE
// the run loop starts — this prevents the dock icon from ever appearing.
MainActor.assumeIsolated {
    let app = NSApplication.shared
    let delegate = AppDelegate()
    app.delegate = delegate
    app.setActivationPolicy(.accessory)
    app.run()
}
