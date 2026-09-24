import Foundation
import XCTest
@testable import AtlasKit

/// FAKE core for the window's logic (A3-14/15/21/22/23/30/32). It proves the view model's behaviour,
/// not the core's (the core side is covered by tests/regression/*.py over the real IPC protocol) and not
/// the pixels of the interface, which still need the real Mac (D-01).
final class ScriptedCore: AtlasTransport {
    var employeeId: String? = "emp-1"
    private let lock = NSLock()
    private var _calls: [(method: String, params: [String: Any])] = []
    var uploadDelayNs: UInt64 = 0
    var failImportOnce = false
    var history: [[String: Any]] = []
    var changed: [[String: Any]] = []
    var importsByRef: [String: [String: Any]] = [:]

    var calls: [(method: String, params: [String: Any])] {
        lock.lock()
        defer { lock.unlock() }
        return _calls
    }

    func count(_ m: String) -> Int { calls.filter { $0.method == m }.count }

    func call(_ method: String, _ params: [String: Any], retrySafe: Bool) async throws -> [String: Any] {
        lock.lock()
        _calls.append((method, params))
        lock.unlock()
        switch method {
        case "artifacts.upload":
            if uploadDelayNs > 0 { try await Task.sleep(nanoseconds: uploadDelayNs) }
            return ["received_bytes": 1, "duplicate": false]
        case "artifacts.import":
            let ref = params["upload_ref"] as? String ?? ""
            if let known = importsByRef[ref] { return known.merging(["recovered": true]) { _, n in n } }
            let r: [String: Any] = ["artifact_id": "art-\(importsByRef.count + 1)", "name": params["declared_name"] ?? "",
                                    "size_bytes": 3, "sha256": params["expected_sha256"] ?? "", "recovered": false]
            importsByRef[ref] = r
            if failImportOnce {
                failImportOnce = false
                throw AtlasAPIError(code: AtlasAPIError.unknownOutcomeCode, message: "reply lost")
            }
            return r
        case "conversations.send":
            let id = params["client_message_id"] as? String ?? ""
            return ["message": ["message_id": "m-\(id)", "role": "owner", "kind": "chat", "content": params["text"] ?? ""],
                    "reply": ["message_id": "r-\(id)", "role": "employee", "kind": "ack", "content": "ok"],
                    "intent": "chat", "task_id": NSNull()]
        case "conversations.current": return ["conversation_id": "conv-1"]
        case "conversations.history":
            if let after = params["after_sequence"] as? Int {
                let limit = params["limit"] as? Int ?? 50
                let rest = history.filter { ($0["sequence"] as? Int ?? 0) > after }
                return ["messages": Array(rest.prefix(limit)), "has_more": rest.count > limit]
            }
            if let since = params["changed_since_revision"] as? Int {
                let rest = changed.filter { ($0["revision"] as? Int ?? 0) > since }
                return ["messages": rest, "has_more": false]
            }
            return ["messages": Array(history.suffix(50)), "has_more": history.count > 50]
        case "identity.get": return ["name": "Atlas"]
        case "settings.get": return ["revision": 0, "settings": NSNull()]
        case "system.health": return ["status": "ok", "components": ["worker": "ok"]]
        case "tasks.list": return ["tasks": [[String: Any]]()]
        case "approvals.list": return ["approvals": [[String: Any]]()]
        case "events.subscribe": return ["events": [[String: Any]](), "last_sequence_id": 0]
        case "artifacts.read": return ["name": "relatorio.md", "mime_type": "text/markdown", "data_b64": "", "eof": true]
        case "tasks.reevaluate": return ["explanation": "o orçamento continua esgotado"]
        default: return [:]
        }
    }
}

private func msg(_ seq: Int, rev: Int? = nil, kind: String = "chat", task: String? = nil) -> [String: Any] {
    var d: [String: Any] = ["message_id": "m\(seq)", "role": seq % 2 == 0 ? "owner" : "employee", "kind": kind,
                            "content": "mensagem \(seq)", "sequence": seq, "revision": rev ?? seq]
    if let task { d["task_id"] = task }
    return d
}

@MainActor
final class G3RegressionTests: XCTestCase {
    private func tempFiles(_ n: Int, invalid: Bool = false) throws -> [URL] {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var urls = try (0..<n).map { i -> URL in
            let u = dir.appendingPathComponent("anexo\(i).txt")
            try Data("abc".utf8).write(to: u)
            return u
        }
        if invalid { urls.append(dir) }  // a folder: must fail explicitly, not vanish
        return urls
    }

    /// A3-21: ten files dropped as separate events while imports are slow: none is discarded.
    func testTenDroppedFilesAllEndImportedOrFailed() async throws {
        let core = ScriptedCore()
        core.uploadDelayNs = 30_000_000
        let vm = AtlasViewModel(api: AtlasAPI(transport: core))
        let urls = try tempFiles(10, invalid: true)
        await withTaskGroup(of: Void.self) { g in
            for u in urls { g.addTask { await vm.attach(fileURL: u) } }  // like the old per-file drop tasks
        }
        while vm.isAttaching { try await Task.sleep(nanoseconds: 10_000_000) }
        XCTAssertEqual(vm.importResults.count, 11)
        XCTAssertEqual(vm.importResults.filter(\.ok).count, 10)
        XCTAssertEqual(vm.attachments.count, 10)
        XCTAssertEqual(vm.importResults.filter { !$0.ok }.count, 1)
        XCTAssertNotNil(vm.lastError)
    }

    /// A3-15: an attachment does not force delegation.
    func testAttachmentDoesNotForceDelegation() async throws {
        let core = ScriptedCore()
        let vm = AtlasViewModel(api: AtlasAPI(transport: core))
        await vm.attach(fileURLs: try tempFiles(1))
        await vm.send("Guarde este arquivo para depois")
        let send = try XCTUnwrap(core.calls.first { $0.method == "conversations.send" })
        XCTAssertEqual(send.params["intent"] as? String, "auto")
        XCTAssertEqual((send.params["artifact_ids"] as? [String])?.count, 1)
    }

    /// A3-22: the retried request is the SAME envelope even after the window's attachments changed.
    func testRetryResendsTheImmutableEnvelope() async throws {
        let core = ScriptedCore()
        let vm = AtlasViewModel(api: AtlasAPI(transport: core))
        await vm.attach(fileURLs: try tempFiles(2))
        let q = ChatMessage(["message_id": "q-1", "role": "employee", "kind": "question", "content": "PDF ou planilha?"])
        vm.reply(to: q)
        final class Once: AtlasTransport {
            let inner: ScriptedCore
            var failed = false
            var employeeId: String? { inner.employeeId }
            init(_ i: ScriptedCore) { inner = i }
            func call(_ m: String, _ p: [String: Any], retrySafe: Bool) async throws -> [String: Any] {
                if m == "conversations.send" && !failed {
                    failed = true
                    _ = try await inner.call(m, p, retrySafe: retrySafe)  // the core got it...
                    throw AtlasAPIError(code: AtlasAPIError.unknownOutcomeCode, message: "reply lost")  // ...reply lost
                }
                return try await inner.call(m, p, retrySafe: retrySafe)
            }
        }
        let flaky = Once(core)
        let vm2 = AtlasViewModel(api: AtlasAPI(transport: flaky))
        await vm2.attach(fileURLs: try tempFiles(2))
        vm2.reply(to: q)
        await vm2.send("Planilha")
        XCTAssertTrue(vm2.confirmingReceipt)
        let draft = try XCTUnwrap(vm2.failedDraft)
        vm2.removeAttachment(vm2.attachments[0])  // the owner changes the window meanwhile
        await vm2.retryFailedSend()
        let sends = core.calls.filter { $0.method == "conversations.send" }
        XCTAssertEqual(sends.count, 2)
        XCTAssertEqual(sends[0].params["client_message_id"] as? String, sends[1].params["client_message_id"] as? String)
        XCTAssertEqual(sends[1].params["artifact_ids"] as? [String], draft.artifactIds)
        XCTAssertEqual(sends[1].params["reply_to_message_id"] as? String, "q-1")
        XCTAssertNil(vm2.failedDraft)
        _ = vm
    }

    /// A3-22: a lost import reply is recovered with the same upload_ref, never re-uploaded.
    func testLostImportReplyIsRecovered() async throws {
        let core = ScriptedCore()
        core.failImportOnce = true
        let vm = AtlasViewModel(api: AtlasAPI(transport: core))
        await vm.attach(fileURLs: try tempFiles(1))
        XCTAssertEqual(core.count("artifacts.upload"), 1)
        XCTAssertEqual(vm.importResults.first?.ok, false)  // the connection layer would retry retry-safe calls
        let refs = core.calls.filter { $0.method == "artifacts.import" }.map { $0.params["upload_ref"] as? String }
        let again = try await vm.api.transport.call("artifacts.import", core.calls.last!.params, retrySafe: true)
        XCTAssertEqual(again["recovered"] as? Bool, true)
        XCTAssertEqual(Set(refs).count, 1)
        XCTAssertEqual(core.calls.last?.params["expected_sha256"] as? String, Hashing.sha256Hex(Data("abc".utf8)))
    }

    /// A3-23: no gap after 120 messages and a changed kind/task link replaces the old version.
    func testHistoryHasNoGapsAndUpsertsChanges() async throws {
        let core = ScriptedCore()
        core.history = (1...2).map { msg($0) }
        let vm = AtlasViewModel(api: AtlasAPI(transport: core))
        await vm.start()
        XCTAssertEqual(vm.messages.map(\.sequence), [1, 2])
        core.history = (1...122).map { msg($0) }  // 120 more while the app was away
        core.changed = [msg(2, rev: 500, kind: "correction", task: "t-9")]
        await vm.refresh()
        XCTAssertEqual(vm.messages.map(\.sequence), Array(1...122))
        let updated = try XCTUnwrap(vm.messages.first { $0.id == "m2" })
        XCTAssertEqual(updated.kind, "correction")
        XCTAssertEqual(updated.taskId, "t-9")
    }

    /// A3-30: only actions the core listed are executed.
    func testOnlyAvailableActionsRun() async {
        let core = ScriptedCore()
        let vm = AtlasViewModel(api: AtlasAPI(transport: core))
        let blocked = TaskItem(["task_id": "t-1", "objective": "x", "state": "BLOCKED", "version": 3,
                                "blocked_reason": "BUDGET_EXCEEDED", "available_actions": ["reevaluate", "cancel"]])
        await vm.perform("resume", on: blocked)
        XCTAssertEqual(core.count("tasks.resume"), 0)
        XCTAssertNotNil(vm.lastError)
        await vm.perform("reevaluate", on: blocked)
        XCTAssertEqual(core.count("tasks.reevaluate"), 1)
        XCTAssertEqual(vm.notice, "o orçamento continua esgotado")
    }

    /// A3-32: the save panel starts with the artifact's name and extension.
    func testSuggestedFileNameKeepsTheExtension() async {
        let vm = AtlasViewModel(api: AtlasAPI(transport: ScriptedCore()))
        let name = await vm.suggestedFileName(artifactId: "a-1")
        XCTAssertEqual(name, "relatorio.md")
    }
}
