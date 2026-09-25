import AtlasKit
import XCTest

@MainActor
private final class SpeechFake: SpeechDriver {
    var onTranscript: ((String, Bool) -> Void)?
    var onFailure: ((String) -> Void)?
    var onSpeechFinished: (() -> Void)?
    var authorized = true
    var starts = 0
    var stops = 0
    var spoken: [String] = []
    var suspendedAuthorization: CheckedContinuation<Bool, Never>?
    var waitForAuthorization = false
    func authorize() async -> Bool {
        if waitForAuthorization { return await withCheckedContinuation { suspendedAuthorization = $0 } }
        return authorized
    }
    func start(locale: String) throws { starts += 1 }
    func stopCapture() { stops += 1 }
    func speak(_ text: String, locale: String) throws { spoken.append(text) }
    func stopSpeaking() {}
}

final class VoiceControllerTests: XCTestCase {
    @MainActor func testTranscriptMustBeReviewedAndNeverSendsItself() async {
        let driver = SpeechFake()
        let vm = VoiceController(driver: driver)
        await vm.start()
        driver.onTranscript?("compre por oito mil", false)
        XCTAssertEqual(vm.state, .listening)
        XCTAssertNil(vm.takeReviewedText())
        driver.onTranscript?("compre por oito mil", true)
        XCTAssertEqual(vm.state, .review)
        vm.transcript = "pesquise, mas não compre"
        XCTAssertEqual(vm.takeReviewedText(), "pesquise, mas não compre")
        XCTAssertEqual(vm.state, .idle)
        XCTAssertEqual(driver.spoken, [])
    }

    @MainActor func testStaleRecognitionDoesNotChangeNextTurn() async {
        let driver = SpeechFake()
        let vm = VoiceController(driver: driver)
        await vm.start()
        let stale = driver.onTranscript
        vm.cancelCapture()
        await vm.start()
        stale?("texto antigo", true)
        XCTAssertEqual(vm.transcript, "")
        XCTAssertEqual(vm.state, .listening)
        vm.suspend()
    }

    @MainActor func testDeniedPermissionNeverStartsCapture() async {
        let driver = SpeechFake()
        driver.authorized = false
        let vm = VoiceController(driver: driver)
        await vm.start()
        XCTAssertEqual(driver.starts, 0)
        if case .failed = vm.state {} else { XCTFail("denial must be visible") }
    }

    @MainActor func testCancellationDuringPermissionPromptIsHonored() async {
        let driver = SpeechFake()
        driver.waitForAuthorization = true
        let vm = VoiceController(driver: driver)
        let start = Task { await vm.start() }
        while driver.suspendedAuthorization == nil { await Task.yield() }
        vm.cancelCapture()
        driver.suspendedAuthorization?.resume(returning: true)
        await start.value
        XCTAssertEqual(driver.starts, 0)
        XCTAssertEqual(vm.state, .idle)
    }

    @MainActor func testStopPlaybackDoesNotInventAWorkCancellation() {
        let driver = SpeechFake()
        let vm = VoiceController(driver: driver)
        vm.speak("Relatório disponível.")
        XCTAssertTrue(vm.isSpeaking)
        vm.stopSpeaking()
        XCTAssertFalse(vm.isSpeaking)
        XCTAssertEqual(driver.spoken, ["Relatório disponível."])
    }

    @MainActor func testDeadlineEndsMicrophoneCapture() async throws {
        let driver = SpeechFake()
        let vm = VoiceController(driver: driver, maximumSeconds: 0)
        await vm.start()
        driver.onTranscript?("rascunho", false)
        for _ in 0..<20 { await Task.yield() }
        XCTAssertNotEqual(vm.state, .listening)
        XCTAssertGreaterThan(driver.stops, 0)
        vm.suspend()
    }
}
