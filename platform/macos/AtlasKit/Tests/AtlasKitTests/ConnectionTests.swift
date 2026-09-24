import Darwin
import Foundation
import XCTest
@testable import AtlasKit

/// FAKE atlas-core speaking the real framing over a real Unix socket, so reconnection, deadlines and
/// correlation are tested without Python. It is a test double, not the core.
final class FakeCoreServer {
    enum Behavior {
        case reply([String: Any])
        case wrongId
        case close  // read the request, then drop the connection without replying
        case hang   // read the request, never reply
    }

    let path: String
    let token: String
    private var listenFd: Int32 = -1
    private var clients: [Int32] = []
    private let lock = NSLock()
    private var _received: [String] = []
    var behavior: (String) -> Behavior

    var received: [String] {
        lock.lock()
        defer { lock.unlock() }
        return _received
    }

    init(token: String = UUID().uuidString, behavior: @escaping (String) -> Behavior) throws {
        self.token = token
        self.behavior = behavior
        path = "/tmp/afc-\(UUID().uuidString.prefix(8)).sock"
        unlink(path)
        listenFd = socket(AF_UNIX, SOCK_STREAM, 0)
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        withUnsafeMutableBytes(of: &addr.sun_path) { raw in
            for (i, b) in path.utf8.enumerated() { raw[i] = b }
        }
        let rc = withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(listenFd, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        guard rc == 0, listen(listenFd, 8) == 0 else { throw IPCError.socketFailed(errno) }
        let fd = listenFd
        Thread.detachNewThread { [weak self] in
            while true {
                let c = accept(fd, nil, nil)
                if c < 0 { return }
                var one: Int32 = 1
                setsockopt(c, SOL_SOCKET, SO_NOSIGPIPE, &one, socklen_t(MemoryLayout<Int32>.size))
                guard let self else { close(c); return }
                self.lock.lock()
                self.clients.append(c)
                self.lock.unlock()
                Thread.detachNewThread { self.serve(c) }
            }
        }
    }

    private static func readExact(_ fd: Int32, _ n: Int) -> Data? {
        var buf = [UInt8](repeating: 0, count: n)
        var got = 0
        while got < n {
            let r = buf.withUnsafeMutableBytes { read(fd, $0.baseAddress! + got, n - got) }
            if r <= 0 { return nil }
            got += r
        }
        return Data(buf)
    }

    private static func frame(_ fd: Int32) -> [String: Any]? {
        guard let h = readExact(fd, 4), let n = try? Framing.decodeLength(h), let body = readExact(fd, n) else { return nil }
        return try? Framing.decodeBody(body)
    }

    private static func write(_ fd: Int32, _ obj: [String: Any]) {
        guard let data = try? Framing.encode(obj) else { return }
        _ = data.withUnsafeBytes { Darwin.write(fd, $0.baseAddress!, data.count) }
    }

    private func serve(_ c: Int32) {
        defer { close(c) }
        guard let hello = FakeCoreServer.frame(c) else { return }
        guard hello["hello"] as? String == token else {
            FakeCoreServer.write(c, ["hello": "rejected"])
            return
        }
        FakeCoreServer.write(c, ["hello": "ok"])
        while let req = FakeCoreServer.frame(c) {
            let method = req["method"] as? String ?? ""
            lock.lock()
            _received.append(method)
            lock.unlock()
            switch behavior(method) {
            case let .reply(result):
                FakeCoreServer.write(c, ["jsonrpc": "2.0", "id": req["id"] ?? NSNull(), "result": result])
            case .wrongId:
                FakeCoreServer.write(c, ["jsonrpc": "2.0", "id": "someone-else", "result": [:] as [String: Any]])
            case .close:
                return
            case .hang:
                Thread.sleep(forTimeInterval: 3)
                return
            }
        }
    }

    func stop() {
        lock.lock()
        let all = clients
        clients = []
        lock.unlock()
        for c in all { shutdown(c, SHUT_RDWR) }
        shutdown(listenFd, SHUT_RDWR)
        close(listenFd)
        unlink(path)
    }

    var session: SessionInfo { SessionInfo(socketPath: path, ownerToken: token, employeeId: "emp-1") }
}

final class ConnectionTests: XCTestCase {
    private func ok(_ method: String) -> FakeCoreServer.Behavior { .reply(["method": method]) }

    func testReconnectsAfterCoreRestartReadingTheNewSession() async throws {
        var current = try FakeCoreServer { .reply(["from": "first", "m": $0]) }
        let lock = NSLock()
        let conn = AtlasConnection(timeout: 2, maxReconnects: 5, backoff: 0.05) {
            lock.lock()
            defer { lock.unlock() }
            return current.session
        }
        let first = try await conn.call("identity.get", [:], retrySafe: true)
        XCTAssertEqual(first["from"] as? String, "first")

        // The core crashes; the Supervisor starts a new one with a NEW socket and token.
        current.stop()
        let second = try FakeCoreServer { .reply(["from": "second", "m": $0]) }
        lock.lock()
        current = second
        lock.unlock()
        let after = try await conn.call("system.health", [:], retrySafe: true)
        XCTAssertEqual(after["from"] as? String, "second")
        XCTAssertGreaterThanOrEqual(conn.reconnectCount, 1)
        second.stop()
    }

    func testMutationIsNeverRepeatedAfterADrop() async throws {
        let server = try FakeCoreServer { $0 == "tasks.cancel" ? .close : .reply([:]) }
        defer { server.stop() }
        let conn = AtlasConnection(timeout: 2, maxReconnects: 3, backoff: 0.05) { server.session }
        do {
            _ = try await conn.call("tasks.cancel", ["task_id": "t", "expected_version": 1], retrySafe: false)
            XCTFail("expected an unknown-outcome error")
        } catch let e as AtlasAPIError {
            XCTAssertEqual(e.code, AtlasAPIError.unknownOutcomeCode)
        }
        XCTAssertEqual(server.received.filter { $0 == "tasks.cancel" }.count, 1)
        // The connection recovers for the next call.
        _ = try await conn.call("system.health", [:], retrySafe: true)
    }

    func testDeadlineBoundsAHungCore() async throws {
        let server = try FakeCoreServer { _ in .hang }
        defer { server.stop() }
        let conn = AtlasConnection(timeout: 0.3, maxReconnects: 1, backoff: 0.05) { server.session }
        let start = Date()
        do {
            _ = try await conn.call("system.health", [:], retrySafe: true)
            XCTFail("expected a failure")
        } catch let e as AtlasAPIError {
            XCTAssertEqual(e.code, AtlasAPIError.unavailableCode)
        }
        XCTAssertLessThan(Date().timeIntervalSince(start), 3)
    }

    func testExpiredSessionIsReportedNotHidden() async throws {
        let server = try FakeCoreServer { _ in .reply([:]) }
        defer { server.stop() }
        let stale = SessionInfo(socketPath: server.path, ownerToken: "expired", employeeId: "emp-1")
        let conn = AtlasConnection(timeout: 1, maxReconnects: 2, backoff: 0.01) { stale }
        do {
            _ = try await conn.call("identity.get", [:], retrySafe: true)
            XCTFail("expected rejection")
        } catch let e as AtlasAPIError {
            XCTAssertEqual(e.code, AtlasAPIError.unavailableCode)
            XCTAssertTrue(e.message.contains("sessão recusada"))
        }
    }

    func testUncorrelatedReplyIsRejected() async throws {
        let server = try FakeCoreServer { _ in .wrongId }
        defer { server.stop() }
        let conn = AtlasConnection(timeout: 1, maxReconnects: 1, backoff: 0.01) { server.session }
        do {
            _ = try await conn.call("identity.get", [:], retrySafe: true)
            XCTFail("expected a failure")
        } catch let e as AtlasAPIError {
            XCTAssertEqual(e.code, AtlasAPIError.unavailableCode)
        }
    }

    func testCallsDoNotRunOnTheMainThread() async throws {
        let server = try FakeCoreServer { _ in .reply([:]) }
        defer { server.stop() }
        var sawMain = false
        let conn = AtlasConnection(timeout: 1) {
            sawMain = sawMain || Thread.isMainThread
            return server.session
        }
        _ = try await conn.call("identity.get", [:], retrySafe: true)
        XCTAssertFalse(sawMain)
    }
}
