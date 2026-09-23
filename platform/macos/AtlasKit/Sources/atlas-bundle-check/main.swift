import AtlasKit
import Foundation

// Headless verification of a built Atlas.app: starts the Supervisor with the bundle's embedded Python,
// core sources and Keychain service (no system Python), talks to atlas-core, then stops the services.
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
defer {
    supervisor.stop()
    try? FileManager.default.removeItem(at: base)
}
do {
    try supervisor.start()
    let api = try AtlasAPI(session: try supervisor.session())
    let identity = try api.identity()
    let health = try api.health()
    let created = try api.delegate(objective: "Verificação do pacote")
    let out: [String: Any] = ["identity": identity, "health": health, "created": created]
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: out, options: [.sortedKeys]))
} catch {
    FileHandle.standardError.write(Data("bundle check failed: \(error)\n".utf8))
    supervisor.stop()
    exit(1)
}
