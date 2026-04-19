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
        // Retry a few times on connection failure — backend may still be starting up.
        let delays: [UInt64] = [0, 500, 1000, 2000]
        var lastError: Error?
        for delay in delays {
            if delay > 0 { try await Task.sleep(nanoseconds: delay * 1_000_000) }
            do {
                _ = try await post(path: "start_recording")
                return
            } catch let error as NSError where error.code == NSURLErrorCannotConnectToHost
                                              || error.code == NSURLErrorNetworkConnectionLost {
                lastError = error
            }
        }
        throw lastError!
    }

    func stopRecording() async throws -> TranscriptResponse {
        var req = URLRequest(url: base.appendingPathComponent("stop_recording"))
        req.httpMethod = "POST"
        req.timeoutInterval = 30.0  // backend crash shouldn't freeze the app for 60s
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
