import Foundation
import XCTest
@testable import AtlasKit

/// FAKE transport whose `conversations.send` hangs until released: stands in for a slow model call on
/// the main lane. Proves the view model's routing of "stop", not the core's behaviour (that is covered
/// by tests/regression/test_a3_04.py over the real IPC protocol).
final class GateTransport: AtlasTransport {
    var employeeId: String? = "emp-1"
    private let lock = NSLock()
    private var _calls: [String] = []
    private var waiters: [CheckedContinuation<Void, Never>] = []
    private var open = false

    var calls: [String] {
        lock.lock()
        defer { lock.unlock() }
        return _calls
    }

    func release() {
        lock.lock()
        open = true
        let w = waiters
        waiters = []
        lock.unlock()
        w.forEach { $0.resume() }
    }

    private func mustWait() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        return !open
    }

    func call(_ method: String, _ params: [String: Any], retrySafe: Bool) async throws -> [String: Any] {
        lock.lock()
        _calls.append(method)
        lock.unlock()
        if (method == "conversations.send" || method == "artifacts.upload") && mustWait() {
            await withCheckedContinuation { (c: CheckedContinuation<Void, Never>) in
                lock.lock()
                if open {
                    lock.unlock()
                    c.resume()
                } else {
                    waiters.append(c)
                    lock.unlock()
                }
            }
        }
        switch method {
        case "control.stop":
            return ["stopped": true, "control_epoch": 1, "paused_tasks": ["t-1", "t-2"],
                    "in_flight_actions": ["a-1"], "unknown_actions": [String](), "elapsed_ms": 3]
        case "conversations.send":
            return ["message": ["message_id": "m-1", "role": "owner", "kind": "chat", "content": "x"],
                    "reply": NSNull(), "intent": "chat", "task_id": NSNull()]
        default:
            return [:]
        }
    }
}

@MainActor
final class A304RegressionTests: XCTestCase {
    private func waitUntil(_ condition: () -> Bool, timeout: TimeInterval = 2) async {
        let end = Date().addingTimeInterval(timeout)
        while !condition() && Date() < end { try? await Task.sleep(nanoseconds: 5_000_000) }
    }

    /// Before the fix, stopAll() called send("pare tudo"), which returned immediately while isSending.
    func testStopWorksWhileASendIsBlockedOnTheMainLane() async {
        let main = GateTransport(), control = GateTransport()
        let vm = AtlasViewModel(api: AtlasAPI(transport: main, control: control))
        let sending = Task { await vm.send("Me explique o contrato") }
        await waitUntil { vm.isSending }
        XCTAssertTrue(vm.isSending)

        let t0 = Date()
        await vm.stopAll()
        XCTAssertLessThan(Date().timeIntervalSince(t0), 1.0, "stop waited behind the conversation")
        XCTAssertTrue(vm.isSending, "the send is still blocked: stop did not ride on it")
        XCTAssertEqual(control.calls.first, "control.stop")
        XCTAssertFalse(main.calls.contains("control.stop"))
        XCTAssertFalse(main.calls.filter { $0 == "conversations.send" }.count > 1, "no 'pare tudo' chat message")
        XCTAssertTrue(vm.notice?.contains("Parei: 2 tarefa(s)") ?? false, vm.notice ?? "no notice")
        XCTAssertTrue(vm.notice?.contains("não é desfeito") ?? false)

        main.release()
        await sending.value
    }

    func testStopFailureIsVisibleNotSilent() async {
        final class Failing: AtlasTransport {
            var employeeId: String? = "emp-1"
            func call(_ method: String, _ params: [String: Any], retrySafe: Bool) async throws -> [String: Any] {
                throw AtlasAPIError(code: AtlasAPIError.unavailableCode, message: "atlas-core indisponível")
            }
        }
        let vm = AtlasViewModel(api: AtlasAPI(transport: GateTransport(), control: Failing()))
        await vm.stopAll()
        XCTAssertTrue(vm.lastError?.contains("NÃO foi confirmada") ?? false)
    }
}
