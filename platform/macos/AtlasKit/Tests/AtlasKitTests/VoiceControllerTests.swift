import Foundation
import XCTest
@testable import AtlasKit

@MainActor private final class CaptureDouble: VoiceCapture {
    var receive: (@Sendable (VoiceEvent) -> Void)?
    var starts = 0
    var stops = 0
    var deny = false
    var hold = false
    var continuation: CheckedContinuation<Void, Never>?
    func start(locale: String, receive: @escaping @Sendable (VoiceEvent) -> Void) async throws {
        starts += 1
        self.receive = receive
        if deny { throw VoiceUnavailable("permission denied") }
        if hold { await withCheckedContinuation { continuation = $0 } }
    }
    func stop() { stops += 1 }
}

@MainActor private final class OutputDouble: VoiceOutput {
    var texts: [String] = []
    var stops = 0
    var done: (@Sendable () -> Void)?
    func speak(_ text: String, locale: String, finished: @escaping @Sendable () -> Void) {
        texts.append(text)
        done = finished
    }
    func stop() { stops += 1 }
}

@MainActor final class VoiceControllerTests: XCTestCase {
    func testRecordingProducesReviewedDraftOnly() async throws {
        let capture = CaptureDouble(), output = OutputDouble()
        let voice = VoiceController(capture: capture, output: output)
        await voice.start(locale: "pt-BR")
        XCTAssertTrue(voice.recording)
        capture.receive?(.transcript("Procure uma passagem", final: false))
        try await Task.sleep(nanoseconds: 10_000_000)
        XCTAssertNil(voice.takeDraft()) // partial transcript is not ready to be used
        voice.finishRecording()
        XCTAssertEqual(voice.phase, .review)
        voice.transcript = "Procure uma passagem, sem comprar" // owner corrects the draft
        XCTAssertEqual(voice.takeDraft(), "Procure uma passagem, sem comprar")
        XCTAssertEqual(voice.phase, .idle)
        XCTAssertTrue(output.texts.isEmpty)
    }

    func testCancelDiscardsLateTranscript() async throws {
        let capture = CaptureDouble(), output = OutputDouble()
        let voice = VoiceController(capture: capture, output: output)
        await voice.start(locale: "pt-BR")
        let old = capture.receive
        voice.cancelRecording()
        old?(.transcript("Pode comprar", final: true))
        try await Task.sleep(nanoseconds: 10_000_000)
        XCTAssertEqual(voice.phase, .idle)
        XCTAssertEqual(voice.transcript, "")
        XCTAssertNil(voice.takeDraft())
    }

    func testDeniedPermissionHasExplicitErrorAndNoDraft() async {
        let capture = CaptureDouble(), output = OutputDouble()
        capture.deny = true
        let voice = VoiceController(capture: capture, output: output)
        await voice.start(locale: "pt-BR")
        XCTAssertFalse(voice.recording)
        XCTAssertNotNil(voice.error)
        XCTAssertNil(voice.takeDraft())
    }

    func testPermissionReplyAfterCancelCannotStartListening() async throws {
        let capture = CaptureDouble(), output = OutputDouble()
        capture.hold = true
        let voice = VoiceController(capture: capture, output: output)
        let pending = Task { await voice.start(locale: "pt-BR") }
        while capture.continuation == nil { await Task.yield() }
        voice.cancelRecording()
        capture.continuation?.resume()
        await pending.value
        XCTAssertEqual(voice.phase, .idle)
    }

    func testTimeLimitStopsMicrophoneAndKeepsDraftForReview() async throws {
        let capture = CaptureDouble(), output = OutputDouble()
        let voice = VoiceController(capture: capture, output: output, maximumSeconds: 0.04)
        await voice.start(locale: "pt-BR")
        capture.receive?(.transcript("Mensagem de teste", final: false))
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(voice.phase, .review)
        XCTAssertGreaterThan(capture.stops, 0)
    }

    func testStopSpeechDoesNotSubmitOrControlTasks() async {
        let capture = CaptureDouble(), output = OutputDouble()
        let voice = VoiceController(capture: capture, output: output)
        voice.speak("Resultado pronto", locale: "pt-BR")
        XCTAssertTrue(voice.reading)
        voice.stopSpeaking()
        XCTAssertFalse(voice.reading)
        XCTAssertEqual(capture.starts, 0)
        XCTAssertNil(voice.takeDraft())
    }

    func testOldSpeechFinishDoesNotStopNewSpeechState() async throws {
        let capture = CaptureDouble(), output = OutputDouble()
        let voice = VoiceController(capture: capture, output: output)
        voice.speak("Primeira resposta", locale: "pt-BR")
        let old = output.done
        voice.speak("Segunda resposta", locale: "pt-BR")
        old?()
        try await Task.sleep(nanoseconds: 10_000_000)
        XCTAssertTrue(voice.reading)
        output.done?()
        try await Task.sleep(nanoseconds: 10_000_000)
        XCTAssertFalse(voice.reading)
    }
}
