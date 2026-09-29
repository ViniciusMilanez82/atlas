import Foundation
import XCTest
@testable import AtlasKit

private final class SetupTransport: AtlasTransport {
    var employeeId: String? = "employee"
    var configured = false
    var completed = false
    var revision = 1
    var calls: [String] = []
    var profile: [String: Any] = ["name": "Aurora", "owner_name": "Test", "locale": "pt-BR",
        "timezone": "America/Sao_Paulo", "profile_version": 2, "settings_revision": 1]
    var document = AtlasAPI.settingsDocument(monthlyMinor: 500, perTaskMinor: 100, modelId: "test-model",
                                               acceptReferencePrices: false)
    private func record(_ method: String) { calls.append(method) }
    func call(_ method: String, _ params: [String: Any], retrySafe: Bool) async throws -> [String: Any] {
        record(method)
        switch method {
        case "setup.status": return ["identity": profile, "completed": completed, "intelligence_ready": configured,
                                     "settings_saved": true]
        case "settings.get": return ["revision": revision, "settings": document]
        case "settings.update":
            guard params["expected_revision"] as? Int == revision else {
                throw AtlasAPIError(code: "VERSION_CONFLICT", message: "stale")
            }
            document = params["settings"] as? [String: Any] ?? [:]
            revision += 1
            profile["settings_revision"] = revision
            return ["revision": revision]
        case "identity.update":
            profile["name"] = params["name"]
            profile["profile_version"] = 3
            return profile
        case "setup.complete":
            guard configured || params["allow_limited_mode"] as? Bool == true else {
                throw AtlasAPIError(code: "MODEL_UNSUPPORTED", message: "no real validation")
            }
            completed = true
            return ["completed": true, "intelligence_ready": configured]
        default: return [:]
        }
    }
}

@MainActor final class ProductSetupTests: XCTestCase {
    func testBudgetEditsPreservePrivacyResearchSecurityAndUnknownSupportedFields() throws {
        var original = AtlasAPI.settingsDocument(monthlyMinor: 500, perTaskMinor: 100, modelId: "test-model",
                                                   acceptReferencePrices: false)
        original["privacy"] = ["sensitive_consents": [["provider": "openai", "purposes": ["task"]]]]
        original["research"] = ["web_enabled": true, "allowed_domains": ["example.org"], "blocked_domains": ["bad.example"]]
        let edited = AtlasAPI.settingsDocument(monthlyMinor: 700, perTaskMinor: 200, modelId: "new-model",
                                                 acceptReferencePrices: true)
        let merged = ConfigurationMerge.intelligence(original: original, edited: edited)
        for key in ["privacy", "research", "security"] {
            XCTAssertEqual(try JSONSerialization.data(withJSONObject: merged[key]!, options: .sortedKeys),
                           try JSONSerialization.data(withJSONObject: original[key]!, options: .sortedKeys))
        }
        XCTAssertEqual((merged["budget"] as? [String: Any])?["monthly_limit_minor"] as? Int, 700)
    }

    func testPrivacyRevocationPreservesOtherProviderAndDomainPolicies() throws {
        let original: [String: Any] = ["privacy": ["sensitive_consents": [
            ["provider": "openai", "purposes": ["task", "conversation"]],
            ["provider": "other", "purposes": ["task"]]]],
            "research": ["web_enabled": true, "allowed_domains": ["example.org"]]]
        let merged = ConfigurationMerge.privacy(original: original, conversation: false, tasks: false, webEnabled: false)
        let privacy = try XCTUnwrap(merged["privacy"] as? [String: Any])
        let consents = try XCTUnwrap(privacy["sensitive_consents"] as? [[String: Any]])
        XCTAssertEqual(consents.count, 1)
        XCTAssertEqual(consents[0]["provider"] as? String, "other")
        XCTAssertEqual((merged["research"] as? [String: Any])?["allowed_domains"] as? [String], ["example.org"])
    }

    func testWizardDoesNotInferBillValidateOrPretendIntelligenceIsReady() async {
        let transport = SetupTransport()
        let model = ProductSetupModel(api: AtlasAPI(transport: transport))
        await model.load()
        XCTAssertTrue(model.loaded)
        XCTAssertFalse(model.completed)
        XCTAssertFalse(model.intelligenceReady)
        await model.finish(limited: false)
        XCTAssertFalse(model.completed)
        XCTAssertNotNil(model.error)
        await model.finish(limited: true)
        XCTAssertTrue(model.completed)
        XCTAssertFalse(model.intelligenceReady)
        XCTAssertFalse(transport.calls.contains("intelligence.check"))
        XCTAssertFalse(transport.calls.contains("conversations.send"))
        XCTAssertFalse(transport.calls.contains("tasks.create"))
    }

    func testConsentChangesPersistAndAConflictDoesNotOverwriteAnotherEdit() async {
        let transport = SetupTransport()
        let model = ProductSetupModel(api: AtlasAPI(transport: transport))
        await model.load()
        model.sensitiveTasks = true
        await model.savePrivacy()
        XCTAssertNil(model.error)
        await model.load()
        XCTAssertTrue(model.sensitiveTasks)
        XCTAssertFalse(model.sensitiveConversation)
        transport.revision += 1  // another window edited the configuration
        model.sensitiveConversation = true
        await model.savePrivacy()
        XCTAssertNotNil(model.error)
        XCTAssertFalse(model.sensitiveConversation) // authoritative configuration restored
    }
}
