import Foundation
import XCTest
@testable import AtlasKit

private final class SkillTransport: AtlasTransport {
    var employeeId: String? = "employee"
    var calls: [(String, [String: Any], Bool)] = []
    var failDecision = false
    var version: [String: Any] = ["id": "version-a", "skill_key": "totals", "version": 1, "revision": 2,
        "description": "Total por linha", "state": "TESTED", "content_hash": String(repeating: "a", count: 64),
        "test_id": "test-a", "can_activate": true, "can_rollback": false, "tests_passed": true,
        "tests_current": true, "classification": "INTERNAL"]
    private func record(_ method: String, _ params: [String: Any], _ retry: Bool) { calls.append((method, params, retry)) }
    func call(_ method: String, _ params: [String: Any], retrySafe: Bool) async throws -> [String: Any] {
        record(method, params, retrySafe)
        switch method {
        case "skills.list": return ["skills": [version]]
        case "skills.get": return version
        case "skills.test": return version
        case "skills.decide":
            if failDecision { throw AtlasAPIError(code: "VERSION_CONFLICT", message: "Versão alterada.") }
            version["state"] = "ACTIVE"; version["revision"] = 3; version["can_activate"] = false
            return version
        default: throw AtlasAPIError(code: "INVALID_INPUT", message: "Unexpected method")
        }
    }
}

@MainActor final class SkillLibraryTests: XCTestCase {
    func testLoadingNeverActivatesOrSendsATask() async {
        let transport = SkillTransport()
        let model = SkillLibraryModel(api: AtlasAPI(transport: transport))
        await model.load()
        XCTAssertEqual(model.skills.count, 1)
        await model.select(model.skills[0])
        XCTAssertEqual(model.selected?.state, "TESTED")
        XCTAssertEqual(transport.calls.map { $0.0 }, ["skills.list", "skills.get"])
    }
    func testDecisionBindsTheReviewedVersionHashAndEvidenceWithRetryId() async {
        let transport = SkillTransport()
        let model = SkillLibraryModel(api: AtlasAPI(transport: transport))
        await model.load(); await model.select(model.skills[0])
        let reviewed = model.selected!
        // The list changes after the owner opened the confirmation. It must not approve version-b.
        transport.version["id"] = "version-b"
        await model.load(); await model.select(model.skills[0])
        await model.decide("activate", reviewed: reviewed)
        let call = transport.calls.first { $0.0 == "skills.decide" }!
        XCTAssertEqual(call.1["version_id"] as? String, "version-a")
        XCTAssertEqual(call.1["expected_revision"] as? Int, 2)
        XCTAssertEqual(call.1["test_id"] as? String, "test-a")
        XCTAssertEqual(call.1["content_hash"] as? String, String(repeating: "a", count: 64))
        XCTAssertNotNil(UUID(uuidString: call.1["request_id"] as? String ?? ""))
        XCTAssertTrue(call.2)
    }
    func testFailedOrStaleTestCannotBeActivated() async {
        let transport = SkillTransport()
        transport.version["can_activate"] = false
        transport.version["tests_passed"] = false
        let model = SkillLibraryModel(api: AtlasAPI(transport: transport))
        await model.load(); await model.select(model.skills[0]); await model.decide("activate")
        XCTAssertNotNil(model.error)
        XCTAssertFalse(transport.calls.contains { $0.0 == "skills.decide" })
    }
    func testConflictDiscardsConfirmationWithoutRetryingNewRevision() async {
        let transport = SkillTransport(); transport.failDecision = true
        let model = SkillLibraryModel(api: AtlasAPI(transport: transport))
        await model.load(); await model.select(model.skills[0]); await model.decide("activate")
        XCTAssertNil(model.selected)
        XCTAssertNotNil(model.error)
        XCTAssertEqual(transport.calls.filter { $0.0 == "skills.decide" }.count, 1)
    }
    func testExamplesAndColumnsAreShownForReview() async {
        let transport = SkillTransport()
        transport.version["definition"] = ["columns": [["name": "total", "op": "multiply"]]]
        transport.version["test_report"] = ["cases": [["label": "example", "passed": true, "actual": [["total": "20.00"]]]]]
        let model = SkillLibraryModel(api: AtlasAPI(transport: transport))
        await model.load(); await model.select(model.skills[0])
        XCTAssertEqual(model.examples.count, 1)
        XCTAssertEqual(model.columns[0]["op"] as? String, "multiply")
    }
}
