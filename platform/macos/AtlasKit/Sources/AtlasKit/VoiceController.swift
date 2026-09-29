import Combine
import Foundation

public enum VoiceEvent: Sendable {
    case transcript(String, final: Bool)
    case failure(String)
}

@MainActor public protocol VoiceCapture: AnyObject {
    func start(locale: String, receive: @escaping @Sendable (VoiceEvent) -> Void) async throws
    func stop()
}

@MainActor public protocol VoiceOutput: AnyObject {
    func speak(_ text: String, locale: String, finished: @escaping @Sendable () -> Void)
    func stop()
}

/// Voice produces an editable draft, NEVER a task or approval. Sending uses the existing chat API.
/// Epochs reject late recognizer/permission callbacks after cancel or a newer recording.
@MainActor
public final class VoiceController: ObservableObject {
    public enum Phase: Equatable { case idle, preparing, listening, review }
    @Published public private(set) var phase: Phase = .idle
    @Published public var transcript = ""
    @Published public private(set) var error: String?
    @Published public private(set) var reading = false
    private let capture: VoiceCapture
    private let output: VoiceOutput
    private let maximumSeconds: Double
    private var epoch = UUID()
    private var speechEpoch = UUID()
    private var timeout: Task<Void, Never>?

    public init(capture: VoiceCapture, output: VoiceOutput, maximumSeconds: Double = 60) {
        self.capture = capture
        self.output = output
        self.maximumSeconds = min(60, max(0.01, maximumSeconds))
    }

    public var recording: Bool { phase == .preparing || phase == .listening }

    public func start(locale: String) async {
        guard !recording else { return }
        stopSpeaking()
        epoch = UUID()
        let id = epoch
        transcript = ""
        error = nil
        phase = .preparing
        do {
            try await capture.start(locale: locale) { [weak self] event in
                Task { @MainActor in self?.receive(event, epoch: id) }
            }
            guard epoch == id, phase == .preparing else { return }
            phase = .listening
            timeout?.cancel()
            let nanos = UInt64(maximumSeconds * 1_000_000_000)
            timeout = Task { [weak self] in
                do { try await Task.sleep(nanoseconds: nanos) } catch { return }
                guard let self, self.epoch == id, self.recording else { return }
                self.finishRecording()
            }
        } catch {
            guard epoch == id else { return }
            capture.stop()
            self.error = "Não foi possível iniciar o ditado: \(error.localizedDescription)"
            phase = .idle
        }
    }

    private func receive(_ event: VoiceEvent, epoch id: UUID) {
        guard id == epoch, recording else { return }
        switch event {
        case let .transcript(text, final):
            transcript = String(text.prefix(16_000))
            if final { finishRecording() }
        case let .failure(message):
            finishRecording()
            error = "Ditado interrompido: \(message). Revise o texto capturado; nada foi enviado."
        }
    }

    public func finishRecording() {
        guard recording else { return }
        epoch = UUID()
        timeout?.cancel()
        timeout = nil
        capture.stop()
        phase = transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? .idle : .review
    }

    public func cancelRecording() {
        epoch = UUID()
        timeout?.cancel()
        timeout = nil
        capture.stop()
        transcript = ""
        phase = .idle
        error = nil
    }

    /// Returns only a reviewed draft. The UI appends it to the composer, never auto-sends it.
    public func takeDraft() -> String? {
        guard phase == .review else { return nil }
        let draft = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !draft.isEmpty else { return nil }
        transcript = ""
        phase = .idle
        return draft
    }

    public func speak(_ text: String, locale: String) {
        guard !recording else { return }
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        stopSpeaking()
        let id = UUID()
        speechEpoch = id
        reading = true
        output.speak(String(text.prefix(32_000)), locale: locale) { [weak self] in
            Task { @MainActor in
                guard let self, self.speechEpoch == id else { return }
                self.reading = false
            }
        }
    }

    /// Stops synthesized audio only. Operational stop remains the independent control lane.
    public func stopSpeaking() {
        speechEpoch = UUID()
        output.stop()
        reading = false
    }
}
