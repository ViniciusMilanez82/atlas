import AVFoundation
import Foundation
import Speech

private enum LocalSpeechError: LocalizedError {
    case unavailable, noMicrophone, missingVoice
    var errorDescription: String? {
        switch self {
        case .unavailable: return "O reconhecimento local deste idioma não está disponível neste Mac. Nenhum áudio foi enviado à nuvem. Continue por texto."
        case .noMicrophone: return "Nenhum microfone válido está disponível. Confira a entrada de áudio nos Ajustes do Sistema."
        case .missingVoice: return "Não há voz instalada para este idioma. Escolha uma voz nos Ajustes de Acessibilidade do Mac."
        }
    }
}

/// Apple's native speech APIs, strictly on-device. No audio files, API key or paid audio endpoint.
/// requiresOnDeviceRecognition alone is insufficient: capability is checked BEFORE installing a tap.
@MainActor
public final class OnDeviceSpeech: NSObject, SpeechDriver, AVSpeechSynthesizerDelegate {
    public var onTranscript: ((String, Bool) -> Void)?
    public var onFailure: ((String) -> Void)?
    public var onSpeechFinished: (() -> Void)?
    private let engine = AVAudioEngine()
    private let synthesizer = AVSpeechSynthesizer()
    private var recognizer: SFSpeechRecognizer?
    private var recognition: SFSpeechRecognitionTask?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var hasTap = false
    private var session = UUID()
    private var activeUtterance: AVSpeechUtterance?

    public override init() {
        super.init()
        synthesizer.delegate = self
    }

    public func authorize() async -> Bool {
        let microphone = await withCheckedContinuation { (c: CheckedContinuation<Bool, Never>) in
            AVCaptureDevice.requestAccess(for: .audio) { c.resume(returning: $0) }
        }
        guard microphone else { return false }
        return await withCheckedContinuation { (c: CheckedContinuation<Bool, Never>) in
            SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0 == .authorized) }
        }
    }

    public func start(locale: String) throws {
        stopCapture()
        guard let speech = SFSpeechRecognizer(locale: Locale(identifier: locale)),
              speech.isAvailable, speech.supportsOnDeviceRecognition else { throw LocalSpeechError.unavailable }
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else { throw LocalSpeechError.noMicrophone }
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.requiresOnDeviceRecognition = true
        req.shouldReportPartialResults = true
        req.taskHint = .dictation
        recognizer = speech
        request = req
        let id = session
        recognition = speech.recognitionTask(with: req) { [weak self] result, error in
            // Capture plain values before crossing to MainActor. Stale callbacks cannot affect a new turn.
            let words = result?.bestTranscription.formattedString
            let final = result?.isFinal ?? false
            let failed = error != nil
            Task { @MainActor [weak self] in
                guard let self, self.session == id else { return }
                if let words { self.onTranscript?(words, final) }
                if failed && !final { self.onFailure?("A captura de fala foi interrompida. Revise o trecho reconhecido ou continue digitando.") }
            }
        }
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in req.append(buffer) }
        hasTap = true
        engine.prepare()
        do { try engine.start() } catch { stopCapture(); throw error }
    }

    public func stopCapture() {
        session = UUID()
        if engine.isRunning { engine.stop() }
        if hasTap { engine.inputNode.removeTap(onBus: 0); hasTap = false }
        request?.endAudio()
        recognition?.cancel()
        recognition = nil
        request = nil
        recognizer = nil
    }

    public func speak(_ text: String, locale: String) throws {
        stopSpeaking()
        guard let voice = AVSpeechSynthesisVoice(language: locale) else { throw LocalSpeechError.missingVoice }
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = voice
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        activeUtterance = utterance
        synthesizer.speak(utterance)
    }

    public func stopSpeaking() {
        activeUtterance = nil
        synthesizer.stopSpeaking(at: .immediate)
    }

    public nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor [weak self] in
            guard let self, self.activeUtterance === utterance else { return }
            self.activeUtterance = nil
            self.onSpeechFinished?()
        }
    }
}
