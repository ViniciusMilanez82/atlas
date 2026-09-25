import Foundation
import XCTest
@testable import AtlasKit

@MainActor
final class OwnerSettingsTests: XCTestCase {
    func testSavingModelsPreservesPrivacyAndResearch() async throws {
        let transport = FakeTransport()
        transport.stored = AtlasAPI.settingsDocument(monthlyMinor: 500, perTaskMinor: 100,
                                                      modelId: "general-test", acceptReferencePrices: false)
        transport.stored?["privacy"] = ["sensitive_consents": [["provider": "openai", "purposes": ["task"]]]]
        transport.stored?["research"] = ["web_enabled": true, "blocked_domains": ["example.com"]]
        let vm = AtlasViewModel(api: AtlasAPI(transport: transport))
        try await vm.loadSettings()
        vm.settings.monthlyMinor = 900
        await vm.saveSettings()
        XCTAssertNil(vm.lastError)
        let privacy = transport.stored?["privacy"] as? [String: Any]
        let grants = privacy?["sensitive_consents"] as? [[String: Any]]
        XCTAssertEqual(grants?.first?["purposes"] as? [String], ["task"])
        let research = transport.stored?["research"] as? [String: Any]
        XCTAssertEqual(research?["web_enabled"] as? Bool, true)
        XCTAssertEqual(research?["blocked_domains"] as? [String], ["example.com"])
    }

    func testStaleModelFormDoesNotOverwriteNewPrivacyConsent() async throws {
        let transport = FakeTransport()
        let vm = AtlasViewModel(api: AtlasAPI(transport: transport))
        try await vm.loadSettings()
        transport.stored = AtlasAPI.settingsDocument(monthlyMinor: 500, perTaskMinor: 100,
                                                      modelId: "general-test", acceptReferencePrices: false)
        transport.stored?["privacy"] = ["sensitive_consents": []]
        transport.revision = 4
        await vm.saveSettings()
        XCTAssertNotNil(vm.lastError)
        XCTAssertEqual(transport.revision, 4)
        XCTAssertNotNil(transport.stored?["privacy"])
    }
}
