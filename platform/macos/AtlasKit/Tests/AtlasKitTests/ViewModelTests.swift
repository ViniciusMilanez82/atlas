import Foundation
import XCTest
@testable import AtlasKit

/// FAKE transport standing in for atlas-core: records every call and answers from a small in-memory
/// state. It proves the view model's behaviour, not the core's.
final class FakeTransport: AtlasTransport {
    var employeeId: String? = "emp-1"
    var calls: [(method: String, params: [String: Any], retrySafe: Bool)] = []
    var revision = 0
    var stored: [String: Any]?
    var failNext: [String: AtlasAPIError] = [:]
    var checkDelayNs: UInt64 = 0
    var artifact = Data("# Relatorio\n<script>alert(1)</script>\n".utf8)
    var reportedSha: String?

    func call(_ method: String, _ params: [String: Any], retrySafe: Bool) async throws -> [String: Any] {
        calls.append((method, params, retrySafe))
        if let e = failNext.removeValue(forKey: method) { throw e }
        switch method {
        case "identity.get": return ["name": "Atlas"]
        case "settings.get":
            return ["revision": revision, "settings": stored ?? NSNull(), "price_table": "spec-2026-09-22",
                    "prices_verified": false]
        case "settings.update":
            guard params["expected_revision"] as? Int == revision else {
                throw AtlasAPIError(code: "VERSION_CONFLICT", message: "settings changed; refresh and retry")
            }
            revision += 1
            stored = params["settings"] as? [String: Any]
            return ["revision": revision]
        case "conversations.current": return ["conversation_id": "conv-1"]
        case "conversations.history": return ["messages": [[String: Any]](), "has_more": false]
        case "conversations.send":
            let id = params["client_message_id"] as? String ?? ""
            return ["message": ["message_id": "m-\(id)", "role": "owner", "kind": "chat",
                                "content": params["text"] ?? ""] as [String: Any],
                    "reply": ["message_id": "r-\(id)", "role": "employee", "kind": "chat", "content": "Olá"],
                    "intent": "chat", "task_id": NSNull()]
        case "system.health": return ["status": "ok", "components": ["database": "ok", "intelligence": "not_configured"],
                                      "intelligence_reason": "no API credential registered"]
        case "tasks.list": return ["tasks": [[String: Any]]()]
        case "approvals.list": return ["approvals": [[String: Any]]()]
        case "events.subscribe":
            return ["events": [[String: Any]](), "last_sequence_id": (params["after_sequence_id"] as? Int ?? 0) + 2]
        case "intelligence.check":
            if checkDelayNs > 0 { try await Task.sleep(nanoseconds: checkDelayNs) }
            return ["report": ["passed": true, "cost_minor": 1, "currency": "USD"] as [String: Any]]
        case "artifacts.read":
            let off = params["offset"] as? Int ?? 0
            let len = params["length"] as? Int ?? 0
            let chunk = artifact.subdata(in: min(off, artifact.count)..<min(off + len, artifact.count))
            return ["data_b64": chunk.base64EncodedString(), "chunk_sha256": Hashing.sha256Hex(chunk),
                    "sha256": reportedSha ?? Hashing.sha256Hex(artifact), "name": "relatorio.html",
                    "mime_type": "text/html", "eof": off + chunk.count >= artifact.count]
        default: return [:]
        }
    }

    func count(_ method: String) -> Int { calls.filter { $0.method == method }.count }
}

@MainActor
final class ViewModelTests: XCTestCase {
    private func make(_ t: FakeTransport = FakeTransport()) -> (AtlasViewModel, FakeTransport) {
        (AtlasViewModel(api: AtlasAPI(transport: t)), t)
    }

    func testThreeSequentialSavesAndReopenPreserveValues() async throws {
        let (vm, t) = make()
        try await vm.loadSettings()
        for (i, monthly) in [300, 400, 500].enumerated() {
            vm.settings.monthlyMinor = monthly
            vm.settings.acceptReferencePrices = true
            await vm.saveSettings()
            XCTAssertNil(vm.lastError)
            XCTAssertEqual(vm.settings.revision, i + 1)
        }
        let (reopened, _) = make(t)  // "close and reopen the window"
        try await reopened.loadSettings()
        XCTAssertEqual(reopened.settings.revision, 3)
        XCTAssertEqual(reopened.settings.monthlyMinor, 500)
        XCTAssertTrue(reopened.settings.acceptReferencePrices)
    }

    func testConflictReloadsAndNextSaveSucceeds() async throws {
        let (vm, t) = make()
        try await vm.loadSettings()
        t.revision = 7  // someone else saved meanwhile
        await vm.saveSettings()
        XCTAssertNotNil(vm.lastError)
        XCTAssertEqual(vm.settings.revision, 7)  // reloaded from the core
        await vm.saveSettings()
        XCTAssertNil(vm.lastError)
        XCTAssertEqual(t.revision, 8)
    }

    func testConversationNeverCreatesTasksByItself() async {
        let (vm, t) = make()
        await vm.start()
        await vm.send("Oi, tudo bem?")
        XCTAssertEqual(t.count("tasks.create"), 0)
        let send = t.calls.first { $0.method == "conversations.send" }
        XCTAssertEqual(send?.retrySafe, true)
        XCTAssertEqual(send?.params["intent"] as? String, "auto")
        XCTAssertEqual(vm.messages.map(\.role), ["owner", "employee"])
        XCTAssertEqual(vm.eventCursor, 2)
    }

    func testFailedSendIsRetriedWithTheSameClientId() async {
        let (vm, t) = make()
        await vm.start()
        t.failNext["conversations.send"] = AtlasAPIError(code: AtlasAPIError.unavailableCode, message: "down")
        await vm.send("Compare as propostas", delegate: true)
        XCTAssertNotNil(vm.failedDraft)
        await vm.retryFailedSend()
        XCTAssertNil(vm.failedDraft)
        let ids = t.calls.filter { $0.method == "conversations.send" }.map { $0.params["client_message_id"] as? String }
        XCTAssertEqual(ids.count, 2)
        XCTAssertEqual(ids[0], ids[1])
    }

    func testRepeatedCheckClicksStartOnePaidCall() async {
        let (vm, t) = make()
        t.checkDelayNs = 200_000_000
        async let a: Void = vm.testIntelligence(maxCents: 5)
        async let b: Void = vm.testIntelligence(maxCents: 5)
        _ = await (a, b)
        XCTAssertEqual(t.count("intelligence.check"), 1)
        XCTAssertTrue(vm.notice?.contains("0,01") ?? false)
    }

    func testPreviewShowsHtmlAsTextOnly() async {
        let (vm, _) = make()
        let text = await vm.preview(artifactId: "a-1")
        XCTAssertTrue(text.contains("<script>alert(1)</script>"))  // shown as source, never executed
        XCTAssertNil(Preview.text(mime: "application/pdf", data: Data("%PDF".utf8)))
    }

    func testExportWritesOnlyVerifiedContent() async throws {
        let (vm, t) = make()
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        t.reportedSha = String(repeating: "0", count: 64)
        let bad = dir.appendingPathComponent("bad.html")
        let failed = await vm.export(artifactId: "a-1", to: bad)
        XCTAssertNil(failed)
        XCTAssertFalse(FileManager.default.fileExists(atPath: bad.path))
        t.reportedSha = nil
        let good = dir.appendingPathComponent("good.html")
        let sha = await vm.export(artifactId: "a-1", to: good)
        XCTAssertEqual(sha, Hashing.sha256Hex(t.artifact))
        XCTAssertEqual(try Data(contentsOf: good), t.artifact)
    }

    func testMoneyIsReadable() {
        XCTAssertTrue(MoneyText.format(minor: 500, currency: "USD").contains("5,00"))
        XCTAssertTrue(MoneyText.format(minor: 12345, currency: "BRL").contains("123,45"))
    }
}
