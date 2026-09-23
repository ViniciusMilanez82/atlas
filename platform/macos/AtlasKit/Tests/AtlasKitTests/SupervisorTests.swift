import Foundation
import XCTest
@testable import AtlasKit

/// Real processes on the macOS runner: Keychain service + Python atlas-core started by the Supervisor.
/// Requires ATLAS_PYTHON (interpreter with requirements installed), ATLAS_REPO and ATLAS_KEYCHAIN_AGENT.
final class SupervisorTests: XCTestCase {
    private func config() throws -> SupervisorConfig {
        let env = ProcessInfo.processInfo.environment
        guard let py = env["ATLAS_PYTHON"], let repo = env["ATLAS_REPO"], let agent = env["ATLAS_KEYCHAIN_AGENT"]
        else { throw XCTSkip("NAO EXECUTADO: set ATLAS_PYTHON, ATLAS_REPO and ATLAS_KEYCHAIN_AGENT") }
        let base = URL(fileURLWithPath: "/tmp/asv-\(UUID().uuidString.prefix(8))")
        return SupervisorConfig(python: URL(fileURLWithPath: py), coreRoot: URL(fileURLWithPath: repo),
                                keychainAgent: URL(fileURLWithPath: agent),
                                dataDir: base.appendingPathComponent("data"), ipcDir: base.appendingPathComponent("ipc"),
                                keychainService: "com.atlas.tests.sup.\(UUID().uuidString)",
                                openAIBaseURL: "http://127.0.0.1:9/v1")
    }

    func testStartTalkRestartAfterCrashAndStop() throws {
        let cfg = try config()
        let sup = Supervisor(config: cfg)
        defer {
            sup.stop()
            try? FileManager.default.removeItem(at: cfg.dataDir.deletingLastPathComponent())
        }
        try sup.start()
        XCTAssertTrue(sup.isRunning)
        let perms = try FileManager.default.attributesOfItem(atPath: cfg.ipcDir.path)[.posixPermissions] as? Int
        XCTAssertEqual(perms, 0o700)

        var s = try sup.session()
        var client = try IPCClient(socketPath: s.socketPath)
        try client.hello(token: s.ownerToken)
        let ident = try client.call("identity.get", params: [:])
        XCTAssertEqual((ident["result"] as? [String: Any])?["name"] as? String, "Atlas")

        // Crash the core: the Supervisor must bring it back with a fresh session.
        let oldPid = try XCTUnwrap(sup.coreProcessId)
        kill(oldPid, SIGKILL)
        let restarted = expectation(description: "core restarted")
        DispatchQueue.global().async {
            for _ in 0..<200 {
                if let pid = sup.coreProcessId, pid != oldPid, sup.isRunning,
                   (try? sup.session()) != nil { restarted.fulfill(); return }
                Thread.sleep(forTimeInterval: 0.1)
            }
        }
        wait(for: [restarted], timeout: 25)
        s = try sup.session()
        client = try IPCClient(socketPath: s.socketPath)
        try client.hello(token: s.ownerToken)
        let health = try client.call("system.health", params: [:])
        XCTAssertEqual((health["result"] as? [String: Any])?["status"] as? String, "ok")

        // "Encerrar serviços" really stops both processes.
        let corePid = try XCTUnwrap(sup.coreProcessId)
        sup.stop()
        XCTAssertFalse(sup.isRunning)
        XCTAssertNotEqual(kill(corePid, 0), 0)  // process is gone
    }
}
