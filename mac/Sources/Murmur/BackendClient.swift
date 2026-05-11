import Foundation

struct TranscriptResponse: Decodable {
    let raw: String
    let polished: String
    let elapsed_ms: [String: Int]?
}

struct BackendSettings: Decodable {
    let polishing_model: String?
    let whisper_model: String?
    let input_gain: Double?
    let use_clipboard_context: Bool?
    let transcription_backend: String?
    let polishing_backend: String?
}

/// Talks to the Python FastAPI backend running on localhost:8765.
actor BackendClient {
    private let base = URL(string: "http://127.0.0.1:8765")!
    private let session: URLSession = {
        let cfg = URLSessionConfiguration.default
        cfg.timeoutIntervalForRequest = 60
        return URLSession(configuration: cfg)
    }()

    func startRecording() async throws {
        // Retry on connection failures — backend may still be starting up after launch.
        let delays: [UInt64] = [0, 500, 1000, 2000]
        var lastError: Error?
        for delay in delays {
            if delay > 0 { try await Task.sleep(nanoseconds: delay * 1_000_000) }
            do {
                _ = try await post(path: "start_recording")
                return
            } catch let error as NSError
                where error.domain == NSURLErrorDomain && error.code != NSURLErrorCancelled {
                // Any URL-layer error (connection refused, network lost, timeout)
                // during startup — retry. App-level errors (4xx/5xx) fall through.
                lastError = error
            }
        }
        throw lastError ?? NSError(domain: NSURLErrorDomain, code: NSURLErrorCannotConnectToHost)
    }

    func stopRecording(
        context: String? = nil,
        appBundleID: String? = nil,
        appName: String? = nil
    ) async throws -> TranscriptResponse {
        var req = URLRequest(url: base.appendingPathComponent("stop_recording"))
        req.httpMethod = "POST"
        req.timeoutInterval = 30.0  // backend crash shouldn't freeze the app for 60s
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        // Always send a body so the backend's optional StopRequest parses cleanly.
        let payload: [String: String?] = [
            "context": context,
            "app_bundle_id": appBundleID,
            "app_name": appName,
        ]
        req.httpBody = try JSONSerialization.data(
            withJSONObject: payload.compactMapValues { $0 }
        )
        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let body = String(data: data, encoding: .utf8) ?? "<non-utf8>"
            throw NSError(domain: "BackendClient", code: (response as? HTTPURLResponse)?.statusCode ?? -1,
                          userInfo: [NSLocalizedDescriptionKey: body])
        }
        return try JSONDecoder().decode(TranscriptResponse.self, from: data)
    }

    func updateGain(_ gain: Double) async throws {
        var req = URLRequest(url: base.appendingPathComponent("settings"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONEncoder().encode(["input_gain": gain])
        _ = try await session.data(for: req)
    }

    /// Asks the backend to abort an in-flight /stop_recording. Best-effort —
    /// if no stop is running, the backend returns {"cancelled": false}.
    func cancel() async {
        var req = URLRequest(url: base.appendingPathComponent("cancel"))
        req.httpMethod = "POST"
        req.timeoutInterval = 2.0
        _ = try? await session.data(for: req)
    }

    func updateUseClipboardContext(_ enabled: Bool) async throws {
        var req = URLRequest(url: base.appendingPathComponent("settings"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONEncoder().encode(["use_clipboard_context": enabled])
        _ = try await session.data(for: req)
    }

    func updateTranscriptionBackend(_ value: String) async throws {
        var req = URLRequest(url: base.appendingPathComponent("settings"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONEncoder().encode(["transcription_backend": value])
        _ = try await session.data(for: req)
    }

    func updatePolishingBackend(_ value: String) async throws {
        var req = URLRequest(url: base.appendingPathComponent("settings"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONEncoder().encode(["polishing_backend": value])
        _ = try await session.data(for: req)
    }

    func getSettings() async throws -> BackendSettings {
        var req = URLRequest(url: base.appendingPathComponent("settings"))
        req.httpMethod = "GET"
        req.timeoutInterval = 3.0
        let (data, _) = try await session.data(for: req)
        return try JSONDecoder().decode(BackendSettings.self, from: data)
    }

    func getLevel() async throws -> Double {
        var req = URLRequest(url: base.appendingPathComponent("level"))
        req.httpMethod = "GET"
        req.timeoutInterval = 1.0  // short — we poll rapidly, don't want a backlog
        let (data, _) = try await session.data(for: req)
        struct LevelResponse: Decodable { let level: Double }
        return try JSONDecoder().decode(LevelResponse.self, from: data).level
    }

    private func post(path: String) async throws -> Data {
        var req = URLRequest(url: base.appendingPathComponent(path))
        req.httpMethod = "POST"
        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let body = String(data: data, encoding: .utf8) ?? "<non-utf8>"
            throw NSError(domain: "BackendClient", code: (response as? HTTPURLResponse)?.statusCode ?? -1,
                          userInfo: [NSLocalizedDescriptionKey: body])
        }
        return data
    }
}
