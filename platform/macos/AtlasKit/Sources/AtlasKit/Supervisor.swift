import Foundation

/// Supervisor (spec 5.1, ADR-012): starts the Keychain service and atlas-core as separate processes,
/// wires them with 0600 token files in 0700 directories, restarts atlas-core after a crash (bounded),
/// and stops both for real on shutdown. Closing the app window does not call `stop()`; quitting the
/// services does. Login-item registration (SMAppService) is a separate step validated on a real Mac.
public struct SupervisorConfig {
    public var python: URL
    public var coreRoot: URL  // folder containing the `core`, `runtime`, ... packages
    public var extraPythonPath: [URL]  // bundled site-packages
    public var keychainAgent: URL
    public var dataDir: URL
    public var ipcDir: URL
    public var keychainService: String
    public var openAIBaseURL: String?
    public var maxRestarts: Int

    public init(python: URL, coreRoot: URL, extraPythonPath: [URL] = [], keychainAgent: URL, dataDir: URL,
                ipcDir: URL, keychainService: String = "com.atlas.vault", openAIBaseURL: String? = nil,
                maxRestarts: Int = 3) {
        self.python = python
        self.coreRoot = coreRoot
        self.extraPythonPath = extraPythonPath
        self.keychainAgent = keychainAgent
        self.dataDir = dataDir
        self.ipcDir = ipcDir
        self.keychainService = keychainService
        self.openAIBaseURL = openAIBaseURL
        self.maxRestarts = maxRestarts
    }

    /// Default layout for the signed-in user: ~/Library/Application Support/Atlas.
    public static func defaultDirectories() -> (data: URL, ipc: URL) {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Atlas", isDirectory: true)
        return (base.appendingPathComponent("data"), base.appendingPathComponent("ipc"))
    }
}

public struct SessionInfo: Equatable {
    public let socketPath: String
    public let ownerToken: String
    public let employeeId: String
}

public enum SupervisorError: Error, Equatable {
    case startFailed(String)
    case notRunning
}

public final class Supervisor {
    public let config: SupervisorConfig
    private var keychain: Process?
    private var core: Process?
    private var restarts = 0
    private var stopping = false
    private let lock = NSLock()
    public private(set) var lastEvent = "stopped"

    public init(config: SupervisorConfig) {
        self.config = config
    }

    private var keychainDir: URL { config.ipcDir.deletingLastPathComponent().appendingPathComponent("kc") }

    private static func privateDir(_ url: URL) throws {
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: url.path)
    }

    private static func writePrivate(_ text: String, to url: URL) throws {
        FileManager.default.createFile(atPath: url.path, contents: Data(text.utf8),
                                       attributes: [.posixPermissions: 0o600])
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }

    private static func waitFor(_ timeout: TimeInterval, _ condition: () -> Bool) -> Bool {
        let end = Date().addingTimeInterval(timeout)
        while Date() < end {
            if condition() { return true }
            Thread.sleep(forTimeInterval: 0.05)
        }
        return condition()
    }

    public func start() throws {
        lock.lock()
        defer { lock.unlock() }
        stopping = false
        try Supervisor.privateDir(config.dataDir)
        try Supervisor.privateDir(config.ipcDir)
        try Supervisor.privateDir(keychainDir)
        let tokenFile = keychainDir.appendingPathComponent("token")
        try Supervisor.writePrivate(UUID().uuidString + UUID().uuidString, to: tokenFile)
        let kcSocket = keychainDir.appendingPathComponent("kc.sock")
        try? FileManager.default.removeItem(at: kcSocket)

        let kc = Process()
        kc.executableURL = config.keychainAgent
        kc.arguments = [kcSocket.path, tokenFile.path, config.keychainService]
        try kc.run()
        keychain = kc
        guard Supervisor.waitFor(5, { FileManager.default.fileExists(atPath: kcSocket.path) }) else {
            kc.terminate()
            throw SupervisorError.startFailed("keychain service did not start")
        }
        try launchCore(kcSocket: kcSocket, tokenFile: tokenFile)
    }

    private func launchCore(kcSocket: URL, tokenFile: URL) throws {
        let session = config.ipcDir.appendingPathComponent("session.json")
        try? FileManager.default.removeItem(at: session)
        let p = Process()
        p.executableURL = config.python
        var args = ["-m", "core", "--data-dir", config.dataDir.path, "--ipc-dir", config.ipcDir.path]
        if let url = config.openAIBaseURL { args += ["--openai-base-url", url] }
        p.arguments = args
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = ([config.coreRoot] + config.extraPythonPath).map(\.path).joined(separator: ":")
        env["PYTHONNOUSERSITE"] = "1"
        env["ATLAS_KEYCHAIN_SOCKET"] = kcSocket.path
        env["ATLAS_KEYCHAIN_TOKEN_FILE"] = tokenFile.path
        p.environment = env
        p.currentDirectoryURL = config.coreRoot
        p.standardOutput = FileHandle.nullDevice
        p.terminationHandler = { [weak self] proc in self?.coreExited(proc, kcSocket: kcSocket, tokenFile: tokenFile) }
        try p.run()
        core = p
        guard Supervisor.waitFor(20, { FileManager.default.fileExists(atPath: session.path) }) else {
            p.terminate()
            throw SupervisorError.startFailed("atlas-core did not become ready")
        }
        lastEvent = "running"
    }

    private func coreExited(_ proc: Process, kcSocket: URL, tokenFile: URL) {
        lock.lock()
        defer { lock.unlock() }
        guard !stopping, proc === core else { return }
        lastEvent = "core exited with status \(proc.terminationStatus)"
        guard restarts < config.maxRestarts else {
            lastEvent = "core stopped after \(restarts) restarts; see diagnostics"
            return
        }
        restarts += 1
        Thread.sleep(forTimeInterval: min(Double(restarts), 3.0))  // bounded backoff
        try? launchCore(kcSocket: kcSocket, tokenFile: tokenFile)
    }

    public var isRunning: Bool { core?.isRunning ?? false }
    public var coreProcessId: Int32? { core?.processIdentifier }

    public func session() throws -> SessionInfo {
        let url = config.ipcDir.appendingPathComponent("session.json")
        guard let data = try? Data(contentsOf: url),
              let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let sock = obj["socket"] as? String, let token = obj["owner_token"] as? String,
              let emp = obj["employee_id"] as? String else { throw SupervisorError.notRunning }
        return SessionInfo(socketPath: sock, ownerToken: token, employeeId: emp)
    }

    /// Stops both services for real (the "Encerrar serviços" operation, spec 3.4).
    public func stop() {
        lock.lock()
        stopping = true
        let c = core
        let k = keychain
        lock.unlock()
        if let c, c.isRunning {
            c.terminate()
            c.waitUntilExit()
        }
        if let k, k.isRunning {
            k.terminate()
            k.waitUntilExit()
        }
        lastEvent = "stopped"
    }
}
