import AVFoundation
import Foundation
import Speech

public struct VoiceUnavailable: LocalizedError {
    public let message: String
    public var errorDescription: String? { message }
    public init(_ message: String) { self.message = message }
}

/// On-device only: unsupported locales/devices fail explicitly, with NO network recognition fallback.
/// Audio exists in the recognition request buffers only; Atlas does not write recordings to disk.
@MainActor
public final class NativeVoiceCapture: VoiceCapture {
    private let engine = AVAudioEngine()
    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var tapped = false
    private var epoch = UUID()

    public init() {}

    public func start(locale: String, receive: @escaping @Sendable (VoiceEvent) -> Void) async throws {
        stop()
        let id = UUID()
        epoch = id
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: locale)),
              recognizer.supportsOnDeviceRecognition else {
            throw VoiceUnavailable("O reconhecimento local deste idioma não está disponível neste Mac. Use texto; nenhum áudio foi enviado à nuvem.")
        }
        let authorized: SFSpeechRecognizerAuthorizationStatus = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
        guard epoch == id else { throw CancellationError() }
        guard authorized == .authorized else {
            throw VoiceUnavailable("Autorize o reconhecimento de fala nos Ajustes do Sistema para usar o ditado.")
        }
        let microphone: Bool = await withCheckedContinuation { continuation in
            AVCaptureDevice.requestAccess(for: .audio) { continuation.resume(returning: $0) }
        }
        guard epoch == id else { throw CancellationError() }
        guard microphone else {
            throw VoiceUnavailable("O microfone não foi autorizado. O chat por texto continua disponível.")
        }
        guard recognizer.isAvailable else {
            throw VoiceUnavailable("O reconhecedor local está indisponível. Tente novamente ou use texto.")
        }
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.requiresOnDeviceRecognition = true
        req.shouldReportPartialResults = true
        req.taskHint = .dictation
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw VoiceUnavailable("Nenhum dispositivo de entrada de áudio utilizável foi encontrado.")
        }
        self.recognizer = recognizer
        request = req
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in req.append(buffer) }
        tapped = true
        task = recognizer.recognitionTask(with: req) { result, error in
            if let result { receive(.transcript(result.bestTranscription.formattedString, final: result.isFinal)) }
            if let error { receive(.failure(error.localizedDescription)) }
        }
        do {
            engine.prepare()
            try engine.start()
        } catch {
            stop()
            throw error
        }
    }

    public func stop() {
        epoch = UUID()
        engine.stop()
        if tapped {
            engine.inputNode.removeTap(onBus: 0)
            tapped = false
        }
        request?.endAudio()
        task?.cancel()
        task = nil
        request = nil
        recognizer = nil
    }
}

@MainActor
public final class NativeVoiceOutput: NSObject, VoiceOutput, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    private var callback: (@Sendable () -> Void)?
    private var current: AVSpeechUtterance?

    public override init() {
        super.init()
        synthesizer.delegate = self
    }

    public func speak(_ text: String, locale: String, finished: @escaping @Sendable () -> Void) {
        stop()
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: locale)
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        callback = finished
        current = utterance
        synthesizer.speak(utterance)
    }

    public func stop() {
        current = nil
        callback = nil
        synthesizer.stopSpeaking(at: .immediate)
    }

    nonisolated public func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,
                                              didFinish utterance: AVSpeechUtterance) {
        finished(utterance)
    }

    nonisolated public func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,
                                              didCancel utterance: AVSpeechUtterance) {
        finished(utterance)
    }

    private nonisolated func finished(_ utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, self.current === utterance else { return }
            let done = self.callback
            self.callback = nil
            self.current = nil
            done?()
        }
    }
}
