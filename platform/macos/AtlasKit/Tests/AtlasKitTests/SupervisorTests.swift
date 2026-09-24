import Foundation
import XCTest
@testable import AtlasKit

/// Real processes on the macOS runner: Keychain service + Python atlas-core started by the Supervisor.
/// Requires ATLAS_PYTHON (interpreter with requirements installed), ATLAS_REPO and ATLAS_KEYCHAIN_AGENT.
final class SupervisorTests: XCTestCase {
    private func config(maxRestarts: Int = 3) throws -> SupervisorConfig {
        let env = ProcessInfo.processInfo.environment
        guard let py = env["ATLAS_PYTHON"], let repo = env["ATLAS_REPO"], let agent = env["ATLAS_KEYCHAIN_AGENT"]
        else { throw XCTSkip("NAO EXECUTADO: set ATLAS_PYTHON, ATLAS_REPO and ATLAS_KEYCHAIN_AGENT") }
        let base = URL(fileURLWithPath: "/tmp/asv-\(UUID().uuidString.prefix(8))")
        return SupervisorConfig(python: URL(fileURLWithPath: py), coreRoot: URL(fileURLWithPath: repo),
                                keychainAgent: URL(fileURLWithPath: agent),
                                dataDir: base.appendingPathComponent("data"), ipcDir: base.appendingPathComponent("ipc"),
                                keychainService: "com.atlas.tests.sup.\(UUID().uuidString)",
                                openAIBaseURL: "http://127.0.0.1:9/v1", maxRestarts: maxRestarts)
    }

    private func waitForNewCore(_ sup: Supervisor, oldPid: Int32, timeout: TimeInterval = 25) -> Bool {
        let end = Date().addingTimeInterval(timeout)
        while Date() < end {
            if let pid = sup.coreProcessId, pid != oldPid, sup.isRunning, (try? sup.session()) != nil { return true }
            Thread.sleep(forTimeInterval: 0.1)
        }
        return false
    }

    /// Review A3/1C: the SAME connection object (as held by the open window) survives a core crash:
    /// it re-reads the new session, handshakes again and continues; mutations are never replayed.
    func testSameConnectionSurvivesCoreCrash() async throws {
        let cfg = try config()
        let sup = Supervisor(config: cfg)
        defer {
            sup.stop()
            try? FileManager.default.removeItem(at: cfg.dataDir.deletingLastPathComponent())
        }
        try sup.start()
        let api = AtlasAPI(transport: AtlasConnection(timeout: 10, maxReconnects: 12, backoff: 0.25) {
            try sup.session()
        })
        let conv = try await api.currentConversation()
        _ = try await api.send(conversationId: conv, text: "Oi", clientMessageId: UUID().uuidString.lowercased())
        let oldPid = try XCTUnwrap(sup.coreProcessId)
        kill(oldPid, SIGKILL)
        let health = try await api.health()  // retry-safe: waits for the Supervisor's restart
        XCTAssertEqual(health["status"] as? String, "ok")
        XCTAssertNotEqual(sup.coreProcessId, oldPid)
        let page = try await api.history(conversationId: conv)  // persisted across the crash
        XCTAssertEqual(page.messages.first?["content"] as? String, "Oi")
    }

    func testRestartLimitIsReportedAndManualRestartRecovers() async throws {
        let cfg = try config(maxRestarts: 1)
        let sup = Supervisor(config: cfg)
        defer {
            sup.stop()
            try? FileManager.default.removeItem(at: cfg.dataDir.deletingLastPathComponent())
        }
        try sup.start()
        let first = try XCTUnwrap(sup.coreProcessId)
        kill(first, SIGKILL)
        XCTAssertTrue(waitForNewCore(sup, oldPid: first))
        let second = try XCTUnwrap(sup.coreProcessId)
        kill(second, SIGKILL)
        Thread.sleep(forTimeInterval: 2)
        XCTAssertFalse(sup.isRunning)
        XCTAssertTrue(sup.lastEvent.contains("stopped after 1 restarts"), sup.lastEvent)
        let conn = AtlasConnection(timeout: 2, maxReconnects: 2, backoff: 0.05) { try sup.session() }
        do {
            _ = try await conn.call("system.health", [:], retrySafe: true)
            XCTFail("the core is down; the call must fail visibly")
        } catch let e as AtlasAPIError {
            XCTAssertEqual(e.code, AtlasAPIError.unavailableCode)
        }
        try sup.restart()  // "Reiniciar serviços"
        let health = try await conn.call("system.health", [:], retrySafe: true)
        XCTAssertEqual(health["status"] as? String, "ok")
        XCTAssertEqual(sup.restartCount, 0)
    }

    func testKeychainServiceFailureIsReported() throws {
        var cfg = try config()
        cfg.keychainAgent = URL(fileURLWithPath: "/nonexistent/atlas-keychain-agent")
        let sup = Supervisor(config: cfg)
        defer { try? FileManager.default.removeItem(at: cfg.dataDir.deletingLastPathComponent()) }
        XCTAssertThrowsError(try sup.start())
        XCTAssertFalse(sup.isRunning)
        XCTAssertThrowsError(try sup.session())
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
