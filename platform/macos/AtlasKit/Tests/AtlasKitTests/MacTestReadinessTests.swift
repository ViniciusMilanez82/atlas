import Foundation
import XCTest
@testable import AtlasKit

final class MacTestReadinessTests: XCTestCase {
    private func environment(major: Int = 15, architecture: MacTestEnvironment.Architecture = .arm64,
                             location: MacTestEnvironment.InstallLocation = .applications,
                             build: String = "3c0aa38", python: Bool = true, core: Bool = true,
                             helper: Bool = true) -> MacTestEnvironment {
        MacTestEnvironment(osMajor: major, architecture: architecture, location: location, build: build,
                           pythonPresent: python, corePresent: core, keychainHelperPresent: helper)
    }
    private func health(worker: String = "ok", database: String = "ok", intelligence: String = "ready") -> [String: Any] {
        ["components": ["worker": worker, "database": database, "intelligence": intelligence]]
    }
    private func state(_ report: MacTestReport, _ id: String) -> MacTestCheckState? {
        report.checks.first { $0.id == id }?.state
    }

    func testNotRunDoesNotReportLocalReadinessOrConversation() {
        let report = MacTestReport.evaluate(environment: environment(), health: nil, attempted: false)
        XCTAssertFalse(report.localPrerequisitesPass)
        XCTAssertFalse(report.mayAttemptConversation)
        XCTAssertEqual(state(report, "ipc"), .notChecked)
    }
    func testHealthyComponentsAllowManualAttemptNotCompleteProduct() {
        let report = MacTestReport.evaluate(environment: environment(), health: health(), attempted: true)
        XCTAssertTrue(report.localPrerequisitesPass)
        XCTAssertTrue(report.mayAttemptConversation)
        XCTAssertFalse(report.completeProduct)
        XCTAssertFalse(report.realModelTestedByThisCheck)
        XCTAssertEqual(state(report, "distribution"), .limitation)
        XCTAssertEqual(state(report, "scope"), .limitation)
    }
    func testCoreAliveWithoutIntelligenceIsNotConversationReady() {
        let report = MacTestReport.evaluate(environment: environment(), health: health(intelligence: "not_configured"), attempted: true)
        XCTAssertTrue(report.localPrerequisitesPass)
        XCTAssertFalse(report.mayAttemptConversation)
    }
    func testIntelIsExplicitlyBlocked() {
        let report = MacTestReport.evaluate(environment: environment(architecture: .intel), health: health(), attempted: true)
        XCTAssertEqual(state(report, "architecture"), .blocked)
        XCTAssertFalse(report.mayAttemptConversation)
    }
    func testOldMacOSIsBlocked() {
        let report = MacTestReport.evaluate(environment: environment(major: 14), health: health(), attempted: true)
        XCTAssertEqual(state(report, "system"), .blocked)
        XCTAssertFalse(report.localPrerequisitesPass)
    }
    func testNewMacOSDoesNotClaimFullyHomologated() {
        let report = MacTestReport.evaluate(environment: environment(major: 26), health: health(), attempted: true)
        XCTAssertEqual(state(report, "system"), .passed)
        XCTAssertFalse(report.completeProduct)
    }
    func testMissingPythonBlocksLocalReadiness() {
        let report = MacTestReport.evaluate(environment: environment(python: false), health: health(), attempted: true)
        XCTAssertEqual(state(report, "bundle"), .blocked)
        XCTAssertFalse(report.localPrerequisitesPass)
    }
    func testMissingCoreBlocksLocalReadiness() {
        let report = MacTestReport.evaluate(environment: environment(core: false), health: health(), attempted: true)
        XCTAssertFalse(report.localPrerequisitesPass)
    }
    func testMissingCofreHelperBlocksLocalReadiness() {
        let report = MacTestReport.evaluate(environment: environment(helper: false), health: health(), attempted: true)
        XCTAssertFalse(report.localPrerequisitesPass)
    }
    func testDegradedStaleAndDeadWorkerCannotPass() {
        for worker in ["degraded", "stale", "stopped", "not_started", "starting", "unknown"] {
            let report = MacTestReport.evaluate(environment: environment(), health: health(worker: worker), attempted: true)
            XCTAssertEqual(state(report, "worker"), .blocked)
            XCTAssertFalse(report.mayAttemptConversation)
        }
    }
    func testDatabaseMustBeHealthyNotJustPresent() {
        let report = MacTestReport.evaluate(environment: environment(), health: health(database: "corrupt"), attempted: true)
        XCTAssertFalse(report.mayAttemptConversation)
    }
    func testMalformedHealthCannotPass() {
        for value: [String: Any] in [[:], ["components": "ok"], ["components": ["database": true, "worker": 1]]] {
            let report = MacTestReport.evaluate(environment: environment(), health: value, attempted: true)
            XCTAssertFalse(report.mayAttemptConversation)
        }
    }
    func testUnreachableCoreReplacesHealthyStatus() {
        let report = MacTestReport.evaluate(environment: environment(), health: nil, attempted: true)
        XCTAssertEqual(state(report, "ipc"), .blocked)
        XCTAssertEqual(state(report, "worker"), .blocked)
        XCTAssertFalse(report.mayAttemptConversation)
    }
    func testTranslocationAndUninstalledCopiesAreIdentifiedWithoutPaths() {
        for location in [MacTestEnvironment.InstallLocation.translocated, .other] {
            let report = MacTestReport.evaluate(environment: environment(location: location), health: health(), attempted: true)
            XCTAssertEqual(state(report, "location"), .limitation)
        }
    }
    func testBuildFieldAcceptsActualGitVersionsOnly() {
        for version in ["3c0aa38", "0.1.0", "v0.1.0-alpha.2-6-gabcdef0", "3c0aa38-dirty"] {
            XCTAssertEqual(environment(build: version).build, version)
        }
        for version in ["/Users/private-name", "secret:example", "", "<script>", String(repeating: "a", count: 81)] {
            XCTAssertEqual(environment(build: version).build, "unavailable")
        }
    }
    func testDiagnosticDoesNotExportHostileHealthFields() throws {
        var value = health()
        value["worker"] = ["last_error": "OWNER_PRIVATE_SENTINEL /Users/personal"]
        value["intelligence_reason"] = "FAKE_SECRET_FOR_TEST_NOT_A_CREDENTIAL"
        value["conversation"] = "PRIVATE_MESSAGE_SENTINEL"
        value["employee_id"] = "PRIVATE_ID_SENTINEL"
        value["unknown_future_field"] = "PRIVATE_FUTURE_SENTINEL"
        let report = MacTestReport.evaluate(environment: environment(), health: value, attempted: true)
        let json = String(decoding: try report.json(), as: UTF8.self)
        for sentinel in ["OWNER_PRIVATE", "/Users", "FAKE_SECRET", "PRIVATE_MESSAGE", "PRIVATE_ID", "PRIVATE_FUTURE"] {
            XCTAssertFalse(json.contains(sentinel))
        }
        XCTAssertTrue(json.contains("alpha-manual-test-prerequisites"))
    }
    func testUnknownComponentStateIsNotEchoed() throws {
        let report = MacTestReport.evaluate(environment: environment(), health: health(worker: "PERSONAL_DATA_SENTINEL"), attempted: true)
        XCTAssertFalse(String(decoding: try report.json(), as: UTF8.self).contains("PERSONAL_DATA_SENTINEL"))
    }
    func testExportHasFixedTopLevelFieldsAndNoImplicitNetwork() throws {
        let report = MacTestReport.evaluate(environment: environment(), health: health(), attempted: true)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: report.json()) as? [String: Any])
        XCTAssertEqual(Set(json.keys), ["schemaVersion", "scope", "completeProduct", "realModelTestedByThisCheck",
            "containsConversationContent", "checkedAt", "environment", "checks"])
        XCTAssertEqual(json["completeProduct"] as? Bool, false)
        XCTAssertEqual(json["realModelTestedByThisCheck"] as? Bool, false)
        XCTAssertEqual(json["containsConversationContent"] as? Bool, false)
    }
}

#if canImport(Combine)
private final class ReadinessTransport: AtlasTransport {
    var employeeId: String? = "not-exported"
    var calls: [String] = []
    var failing = false
    var started: (() -> Void)?
    var gate: CheckedContinuation<Void, Never>?
    var suspend = false
    func call(_ method: String, _ params: [String: Any], retrySafe: Bool) async throws -> [String: Any] {
        calls.append(method)
        XCTAssertTrue(retrySafe)
        XCTAssertTrue(params.isEmpty)
        started?()
        if suspend { await withCheckedContinuation { gate = $0 } }
        if failing { throw AtlasAPIError(code: "FAKE_PRIVATE_ERROR", message: "FAKE_PRIVATE_PATH") }
        return ["components": ["database": "ok", "worker": "ok", "intelligence": "ready"]]
    }
}

@MainActor final class MacTestReadinessModelTests: XCTestCase {
    private func model(_ transport: ReadinessTransport) -> MacTestReadinessModel {
        MacTestReadinessModel(api: AtlasAPI(transport: transport), inspect: {
            MacTestEnvironment(osMajor: 15, architecture: .arm64, location: .applications, build: "3c0aa38",
                               pythonPresent: true, corePresent: true, keychainHelperPresent: true)
        })
    }
    func testOnlyReadOnlyHealthIsCalledAndNoPaidTest() async {
        let transport = ReadinessTransport()
        let readiness = model(transport)
        XCTAssertTrue(transport.calls.isEmpty)
        await readiness.run()
        XCTAssertEqual(transport.calls, ["system.health"])
        XCTAssertTrue(readiness.report.mayAttemptConversation)
        XCTAssertFalse(readiness.report.realModelTestedByThisCheck)
    }
    func testFailureClearsPreviousGreenResultAndHidesException() async throws {
        let transport = ReadinessTransport()
        let readiness = model(transport)
        await readiness.run()
        XCTAssertTrue(readiness.report.localPrerequisitesPass)
        transport.failing = true
        await readiness.run()
        XCTAssertFalse(readiness.report.localPrerequisitesPass)
        XCTAssertFalse(readiness.checking)
        XCTAssertFalse(String(decoding: try readiness.report.json(), as: UTF8.self).contains("FAKE_PRIVATE"))
    }
    func testConcurrentClicksDoNotQueueUnboundedChecksOrKeepOldGreen() async {
        let transport = ReadinessTransport()
        let readiness = model(transport)
        await readiness.run()
        transport.suspend = true
        let task = Task { await readiness.run() }
        for _ in 0..<100 where transport.gate == nil { await Task.yield() }
        XCTAssertTrue(readiness.checking)
        XCTAssertFalse(readiness.report.localPrerequisitesPass)
        await readiness.run()
        XCTAssertEqual(transport.calls.count, 2)
        transport.gate?.resume()
        await task.value
        XCTAssertFalse(readiness.checking)
    }
}
#endif
