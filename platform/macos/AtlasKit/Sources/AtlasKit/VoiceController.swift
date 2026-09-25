import Combine
import Foundation

/// Speech is an input/output device, NOT a second agent or an authorization channel.
/// Drivers may only emit draft text. Only the reviewed composer calls conversations.send.
@MainActor
public protocol SpeechDriver: AnyObject {
    var onTranscript: ((String, Bool) -> Void)? { get set }
    var onFailure: ((String) -> Void)? { get set }
    var onSpeechFinished: (() -> Void)? { get set }
    func authorize() async -> Bool
    func start(locale: String) throws
    func stopCapture()
    func speak(_ text: String, locale: String) throws
    func stopSpeaking()
}

public enum VoiceState: Equatable {
    case idle, authorizing, listening, review, failed(String)
}

@MainActor
public final class VoiceController: ObservableObject {
    @Published public private(set) var state: VoiceState = .idle
    @Published public var transcript = ""
    @Published public private(set) var isSpeaking = false
    private let driver: SpeechDriver
    private var generation = UUID()
    private var deadline: Task<Void, Never>?
    private let maximumSeconds: UInt64

    public init(driver: SpeechDriver, maximumSeconds: UInt64 = 60) {
        self.driver = driver
        self.maximumSeconds = min(maximumSeconds, 60)
        driver.onSpeechFinished = { [weak self] in self?.isSpeaking = false }
    }

    public func start(locale: String = "pt-BR") async {
        guard state != .listening, state != .authorizing else { return }
        cancelCapture()
        stopSpeaking() // no echo from the Atlas speaker into its own microphone
        transcript = ""
        state = .authorizing
        let id = generation
        guard await driver.authorize() else {
            if generation == id { state = .failed("Autorize o microfone e o reconhecimento de fala nos Ajustes do Sistema.") }
            return
        }
        guard id == generation else { return } // owner cancelled while the system prompt was open
        driver.onTranscript = { [weak self] text, final in
            guard let self, self.generation == id, self.state == .listening else { return }
            self.transcript = text
            if final { self.finishCapture() }
        }
        driver.onFailure = { [weak self] why in
            guard let self, self.generation == id else { return }
            self.cancelCapture(clear: false)
            self.state = .failed(why)
        }
        do {
            try driver.start(locale: locale)
            state = .listening
            deadline = Task { [weak self] in
                do { try await Task.sleep(nanoseconds: (self?.maximumSeconds ?? 60) * 1_000_000_000) }
                catch { return }
                if let self, self.generation == id { self.finishCapture() }
            }
        } catch {
            driver.stopCapture()
            state = .failed(error.localizedDescription)
        }
    }

    public func finishCapture() {
        guard state == .listening else { return }
        generation = UUID()
        deadline?.cancel()
        deadline = nil
        driver.onTranscript = nil
        driver.onFailure = nil
        driver.stopCapture()
        state = transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? .failed("Nenhuma fala foi reconhecida. Tente novamente ou digite sua mensagem.") : .review
    }

    public func cancelCapture(clear: Bool = true) {
        generation = UUID()
        deadline?.cancel()
        deadline = nil
        driver.onTranscript = nil
        driver.onFailure = nil
        driver.stopCapture()
        if clear { transcript = "" }
        state = .idle
    }

    /// Returns only reviewed draft text. No network, task, approval or message is created here.
    public func takeReviewedText() -> String? {
        guard state == .review else { return nil }
        let value = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return nil }
        cancelCapture()
        return value
    }

    public func speak(_ text: String, locale: String = "pt-BR") {
        if state == .listening || state == .authorizing { cancelCapture(clear: false) }
        stopSpeaking()
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        guard text.count <= 32_000 else {
            state = .failed("Este texto é longo demais para leitura em voz. Abra o arquivo e selecione um trecho.")
            return
        }
        do {
            try driver.speak(text, locale: locale)
            isSpeaking = true
        } catch { state = .failed(error.localizedDescription) }
    }

    /// Stops playback only. Operational stop is the independent control.stop IPC action.
    public func stopSpeaking() {
        driver.stopSpeaking()
        isSpeaking = false
    }

    public func suspend() { cancelCapture(); stopSpeaking() }
}
