import AtlasKit
import Foundation

// Headless verification of a built Atlas.app: starts the Supervisor with the bundle's embedded Python,
// core sources and Keychain service (no system Python), talks to atlas-core through the same async
// connection the app uses, sends a conversation message, then stops the services.
// usage: atlas-bundle-check <path/to/Atlas.app>

let args = CommandLine.arguments
 guard args.count == 2 else {
    FileHandle.standardError.write(Data("usage: atlas-bundle-check <Atlas.app>\n".utf8))
    exit(2)
}
let app = URL(fileURLWithPath: args[1])
let res = app.appendingPathComponent("Contents/Resources")
let base = URL(fileURLWithPath: "/tmp/abc-\(UUID().uuidString.prefix(8))")
let config = SupervisorConfig(
    python: res.appendingPathComponent("python/bin/python3"),
    coreRoot: res.appendingPathComponent("core-src"),
    extraPythonPath: [res.appendingPathComponent("site-packages")],
    keychainAgent: app.appendingPathComponent("Contents/MacOS/atlas-keychain-agent"),
    dataDir: base.appendingPathComponent("data"),
    ipcDir: base.appendingPathComponent("ipc"),
    keychainService: "com.atlas.bundlecheck.\(UUID().uuidString)",
    openAIBaseURL: "http://127.0.0.1:9/v1")
let supervisor = Supervisor(config: config)

func finish(_ code: Int32) -> Never {
    supervisor.stop()
    try? FileManager.default.removeItem(at: base)
    exit(code)
}

do {
    try supervisor.start()
    let api = AtlasAPI(transport: AtlasConnection(timeout: 20) { try supervisor.session() })
    let identity = try await api.identity()
    var health = try await api.health()
    for _ in 0..<20 {
        if (health["components"] as? [String: Any])?["worker"] as? String == "ok" { break }
        try await Task.sleep(nanoseconds: 100_000_000)
        health = try await api.health()
    }
    guard let builtBundle = Bundle(url: app) else {
        throw AtlasAPIError(code: "BUNDLE_INVALID", message: "Bundle metadata missing")
    }
    let readiness = MacTestReport.evaluate(environment: .inspect(bundle: builtBundle), health: health, attempted: true)
    guard readiness.localPrerequisitesPass && !readiness.mayAttemptConversation else {
        throw AtlasAPIError(code: "READINESS_FAILED", message: "Local prerequisites or no-credential expectation failed")
    }
    let conversation = try await api.currentConversation()
    let sent = try await api.send(conversationId: conversation, text: "Oi", clientMessageId: UUID().uuidString.lowercased())
    let out: [String: Any] = ["identity": identity, "health": health, "conversation_reply": sent["reply"] ?? NSNull(),
                              "test_readiness": try JSONSerialization.jsonObject(with: readiness.json())]
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]))
    finish(0)
} catch {
    FileHandle.standardError.write(Data("bundle check failed: \(error)\n".utf8))
    finish(1)
}
