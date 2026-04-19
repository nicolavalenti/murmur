import Foundation

/// Spawns the Python backend (`murmur-server`) as a child process so the user
/// doesn't need a separate terminal. The process is tied to the app's lifecycle —
/// quitting murmur terminates uvicorn, so there are no orphaned servers.
///
/// Python and mlx-whisper are NOT bundled inside the .app. Instead we expect the
/// venv to exist on disk at a known location. Override with env var
/// `MURMUR_BACKEND_DIR` if the repo lives elsewhere.
final class BackendProcess {
    private var task: Process?
    private let backendDir: String

    init() {
        let envDir = ProcessInfo.processInfo.environment["MURMUR_BACKEND_DIR"]
        let defaultDir = NSString("~/Projects/murmur/backend").expandingTildeInPath
        self.backendDir = envDir ?? defaultDir
    }

    func start() {
        guard task == nil || task?.isRunning == false else { return }
        task = nil

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/zsh")
        // -lc: login shell so PATH/rc files load, then run our command.
        // `source .venv/bin/activate && exec murmur-server` replaces zsh with
        // uvicorn so signals (SIGTERM on app quit) reach the Python process.
        proc.arguments = [
            "-lc",
            "cd \(shellEscape(backendDir)) && source .venv/bin/activate && exec murmur-server"
        ]

        // Inherit stdout/stderr so backend logs show up when launched from Terminal,
        // and land in Console.app when launched from Finder.
        proc.standardOutput = FileHandle.standardOutput
        proc.standardError = FileHandle.standardError

        // Auto-restart if the process crashes or is killed unexpectedly.
        proc.terminationHandler = { [weak self] _ in
            guard let self else { return }
            self.task = nil
            print("[murmur] backend exited — restarting in 1s")
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                self.start()
            }
        }

        do {
            try proc.run()
            task = proc
            print("[murmur] backend started (pid \(proc.processIdentifier)) from \(backendDir)")
        } catch {
            print("[murmur] failed to start backend: \(error.localizedDescription)")
        }
    }

    func stop() {
        guard let proc = task, proc.isRunning else { return }
        proc.terminationHandler = nil  // prevent auto-restart on intentional quit
        proc.terminate()
        proc.waitUntilExit()
        task = nil
    }

    private func shellEscape(_ path: String) -> String {
        "'" + path.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}
