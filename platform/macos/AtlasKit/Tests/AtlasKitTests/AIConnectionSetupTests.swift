import Foundation
import XCTest
@testable import AtlasKit

private final class ConnectionSetupTransport: AtlasTransport {
    var employeeId: String? = "synthetic-employee"
    var registered = true
    var ready = false
    var revision = 2
    var calls: [String] = []
    var failSaving = false
    var blockCheck = false
    var failureReason: String?
    var pending: CheckedContinuation<Void, Never>?
    var document = AtlasAPI.settingsDocument(monthlyMinor: 500, perTaskMinor: 100,
        modelId: "gpt-6-sol", acceptReferencePrices: true)

    func call(_ method: String, _ params: [String: Any], retrySafe: Bool) async throws -> [String: Any] {
        calls.append(method)
        switch method {
        case "settings.get":
            return ["revision": revision, "settings": document, "prices_verified": false,
                "intelligence": ["configured": ready,
                    "reason": ready ? "READY: ready" : (registered ? "VALIDATION_REQUIRED: not validated" : "CREDENTIAL_MISSING: none")]]
        case "credentials.register":
            XCTAssertFalse(retrySafe)
            registered = true
            ready = false
            return [:]
        case "settings.update":
            XCTAssertFalse(retrySafe)
            if failSaving { throw AtlasAPIError(code: "VERSION_CONFLICT", message: "synthetic") }
            XCTAssertEqual(params["expected_revision"] as? Int, revision)
            document = params["settings"] as? [String: Any] ?? [:]
            revision += 1
            return ["revision": revision]
        case "intelligence.check":
            XCTAssertFalse(retrySafe, "A paid check is never automatically repeated")
            if blockCheck { await withCheckedContinuation { pending = $0 } }
            if let failureReason { return ["report": ["passed": false, "reason_code": failureReason,
                "errors": ["untrusted error body must not be displayed"]]] }
            ready = true
            return ["report": ["passed": true, "reason_code": "READY", "cost_minor": 1, "currency": "USD"]]
        default: return [:]
        }
    }
}

@MainActor final class AIConnectionSetupTests: XCTestCase {
    func testOpeningPanelUsesNoKeyReadAndNoPaidCall() async {
        let t = ConnectionSetupTransport()
        let m = AIConnectionSetupModel(api: AtlasAPI(transport: t))
        await m.load()
        XCTAssertEqual(t.calls, ["settings.get"])
        XCTAssertEqual(m.credentialRegistered, true)
        XCTAssertFalse(m.connected)
        XCTAssertEqual(m.newKey, "")
    }

    func testSingleConnectReusesSavedKeyAndPreservesPrivacy() async {
        let t = ConnectionSetupTransport()
        t.document["privacy"] = ["sensitive_consents": []]
        t.document["research"] = ["web_enabled": false]
        let m = AIConnectionSetupModel(api: AtlasAPI(transport: t))
        await m.load()
        await m.connect(maxCents: 5)
        XCTAssertTrue(m.connected)
        XCTAssertFalse(t.calls.contains("credentials.register"))
        XCTAssertEqual(t.calls.filter { $0 == "intelligence.check" }.count, 1)
        XCTAssertEqual((t.document["research"] as? [String: Any])?["web_enabled"] as? Bool, false)
        XCTAssertNotNil(t.document["privacy"])
        XCTAssertEqual(t.calls, ["settings.get", "settings.update", "intelligence.check", "settings.get"])
    }

    func testPriceConsentIsNeverCheckedOnTheUsersBehalf() async {
        let t = ConnectionSetupTransport()
        let m = AIConnectionSetupModel(api: AtlasAPI(transport: t))
        await m.load(); m.form.acceptReferencePrices = false
        await m.connect(maxCents: 5)
        XCTAssertEqual(t.calls, ["settings.get"])
        XCTAssertEqual(m.reason, .consent)
    }

    func testFailedSaveNeverStartsPaidCallOrDiscardsRegisteredKey() async {
        let t = ConnectionSetupTransport(); t.failSaving = true
        let m = AIConnectionSetupModel(api: AtlasAPI(transport: t))
        await m.load(); await m.connect(maxCents: 5)
        XCTAssertFalse(t.calls.contains("intelligence.check"))
        XCTAssertEqual(m.credentialRegistered, true)
        XCTAssertNotNil(m.error)
    }

    func testFailureMessageOnlyUsesFixedVocabulary() async {
        let t = ConnectionSetupTransport(); t.failureReason = "API_QUOTA_EXHAUSTED"
        let m = AIConnectionSetupModel(api: AtlasAPI(transport: t))
        await m.load(); await m.connect(maxCents: 5)
        XCTAssertFalse(m.connected)
        XCTAssertEqual(m.error, AIConnectionReason.quota.message)
        XCTAssertFalse(m.error?.contains("untrusted") ?? true)
    }

    func testConcurrentClicksNeverStartTwoPaidChecks() async {
        let t = ConnectionSetupTransport(); t.blockCheck = true
        let m = AIConnectionSetupModel(api: AtlasAPI(transport: t))
        await m.load()
        let first = Task { await m.connect(maxCents: 5) }
        for _ in 0..<200 where t.pending == nil { await Task.yield() }
        XCTAssertTrue(m.busy)
        await m.connect(maxCents: 5)
        XCTAssertEqual(t.calls.filter { $0 == "intelligence.check" }.count, 1)
        t.pending?.resume(); t.pending = nil
        await first.value
        XCTAssertFalse(m.busy)
    }

    func testValidationUsesItsOwnTransportAndNoAutomaticRetry() async throws {
        let chat = ConnectionSetupTransport(), control = ConnectionSetupTransport(), validation = ConnectionSetupTransport()
        let api = AtlasAPI(transport: chat, control: control, validation: validation)
        _ = try await api.testIntelligence(modelId: "gpt-6-sol", maxCents: 5)
        XCTAssertTrue(chat.calls.isEmpty); XCTAssertTrue(control.calls.isEmpty)
        XCTAssertEqual(validation.calls, ["intelligence.check"])
    }

    func testReadinessExportsSpecificFixedReasonNotRawServerMessage() throws {
        let e = MacTestEnvironment(osMajor: 27, architecture: .arm64, location: .applications, build: "8c6adbc",
            pythonPresent: true, corePresent: true, keychainHelperPresent: true)
        let report = MacTestReport.evaluate(environment: e, health: [
            "components": ["database": "ok", "worker": "ok", "intelligence": "not_configured"],
            "intelligence_reason": "API_AUTH_REJECTED: private raw key",
        ], attempted: true)
        XCTAssertEqual(report.checks.first { $0.id == "intelligence" }?.detail, AIConnectionReason.auth.message)
        let json = String(data: try report.json(), encoding: .utf8)!
        XCTAssertFalse(json.contains("private raw key")); XCTAssertFalse(report.mayAttemptConversation)
    }
}
