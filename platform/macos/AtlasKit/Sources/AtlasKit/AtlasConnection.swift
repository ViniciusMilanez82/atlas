import Foundation

/// Normalized error shown to the owner with its message; never hidden or replaced by a fake success.
public struct AtlasAPIError: Error, CustomStringConvertible, Equatable {
    public let code: String
    public let message: String
    public var description: String { "\(code): \(message)" }

    public init(code: String, message: String) {
        self.code = code
        self.message = message
    }

    /// The connection dropped after the request left: the core may or may not have applied it.
    public static let unknownOutcomeCode = "CONNECTION_LOST"
    public static let unavailableCode = "CORE_UNAVAILABLE"
}

/// What the view model needs from the core. `AtlasConnection` is the real one; tests use a fake.
public protocol AtlasTransport: AnyObject {
    /// `retrySafe`: the call may be repeated after a reconnect because it is read-only or carries a
    /// client-generated id the core deduplicates (conversations.send, tasks.create with
    /// client_request_id, artifacts.upload with offset). Anything else is never repeated automatically.
    func call(_ method: String, _ params: [String: Any], retrySafe: Bool) async throws -> [String: Any]
    var employeeId: String? { get }
}

public enum ConnectionState: Equatable {
    case disconnected
    case connected
    case reconnecting(attempt: Int)
    case failed(String)

    public var text: String {
        switch self {
        case .disconnected: return "Desconectado"
        case .connected: return "Conectado"
        case let .reconnecting(n): return "Reconectando (tentativa \(n))…"
        case let .failed(why): return "Sem conexão: \(why)"
        }
    }
}

/// Async, serialized connection to atlas-core (review Alpha 1, A3).
///
/// * All socket I/O runs on one private serial queue - never on the main actor - so a slow or dead
///   core cannot freeze the window. Each call has a deadline (`timeout`).
/// * Replies are correlated by request id (`IPCClient`).
/// * If the core restarts (Supervisor), the next call re-reads `session.json` (new socket token),
///   performs the handshake again and continues. Only retry-safe calls are repeated; for other calls
///   an interrupted request is reported as "result unknown", never silently re-sent.
/// * Task cancellation is honoured: a cancelled caller gets `CancellationError` and the reply, if it
///   arrives, is discarded (the connection stays consistent because the queue still reads it).
public final class AtlasConnection: AtlasTransport, @unchecked Sendable {
    private let queue = DispatchQueue(label: "com.atlas.ipc.connection")
    private let sessionProvider: () throws -> SessionInfo
    private let timeout: TimeInterval
    private let maxReconnects: Int
    private let backoff: TimeInterval
    private var client: IPCClient?
    private var _employeeId: String?
    private let stateLock = NSLock()
    public var onStateChange: ((ConnectionState) -> Void)?
    public private(set) var reconnectCount = 0

    public init(timeout: TimeInterval = 30, maxReconnects: Int = 5, backoff: TimeInterval = 0.25,
                sessionProvider: @escaping () throws -> SessionInfo) {
        self.timeout = timeout
        self.maxReconnects = maxReconnects
        self.backoff = backoff
        self.sessionProvider = sessionProvider
    }

    public var employeeId: String? {
        stateLock.lock()
        defer { stateLock.unlock() }
        return _employeeId
    }

    public func call(_ method: String, _ params: [String: Any] = [:], retrySafe: Bool) async throws -> [String: Any] {
        try Task.checkCancellation()
        let box = CancelBox()
        let result: [String: Any] = try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (cont: CheckedContinuation<[String: Any], Error>) in
                queue.async {
                    do { cont.resume(returning: try self.callSync(method, params, retrySafe: retrySafe, box: box)) }
                    catch { cont.resume(throwing: error) }
                }
            }
        } onCancel: {
            box.cancel()
        }
        if box.isCancelled { throw CancellationError() }
        return result
    }

    /// Drops the current socket; the next call reconnects with a fresh session.
    public func reset() {
        queue.async { self.client = nil }
    }

    // MARK: - queue-confined

    private func publish(_ state: ConnectionState) {
        onStateChange?(state)
    }

    private func connect() throws -> IPCClient {
        if let c = client { return c }
        let session = try sessionProvider()  // re-read on every connect: the token changes on restart
        let c = try IPCClient(socketPath: session.socketPath, timeout: timeout)
        try c.hello(token: session.ownerToken)
        stateLock.lock()
        _employeeId = session.employeeId
        stateLock.unlock()
        client = c
        publish(.connected)
        return c
    }

    private static func unwrap(_ reply: [String: Any]) throws -> [String: Any] {
        if let error = reply["error"] as? [String: Any] {
            let data = error["data"] as? [String: Any]
            throw AtlasAPIError(code: data?["atlas_code"] as? String ?? "ERROR",
                                message: error["message"] as? String ?? "erro desconhecido")
        }
        return reply["result"] as? [String: Any] ?? [:]
    }

    private func callSync(_ method: String, _ params: [String: Any], retrySafe: Bool, box: CancelBox) throws
        -> [String: Any]
    {
        var attempt = 0
        var lastReason = "atlas-core indisponível"
        while true {
            if box.isCancelled { throw CancellationError() }
            let c: IPCClient
            do {
                c = try connect()
            } catch {
                // Nothing was sent: retrying is safe for every method.
                client = nil
                lastReason = Self.describe(error)
                attempt += 1
                if attempt > maxReconnects {
                    publish(.failed(lastReason))
                    throw AtlasAPIError(code: AtlasAPIError.unavailableCode, message: lastReason)
                }
                reconnectCount += 1
                publish(.reconnecting(attempt: attempt))
                Thread.sleep(forTimeInterval: min(backoff * pow(2, Double(attempt - 1)), 3))
                continue
            }
            do {
                return try Self.unwrap(try c.call(method, params: params))
            } catch let apiError as AtlasAPIError {
                throw apiError
            } catch {
                client = nil  // timeout, EOF or protocol violation: this socket is unusable
                lastReason = Self.describe(error)
                guard retrySafe else {
                    publish(.reconnecting(attempt: 1))
                    throw AtlasAPIError(
                        code: AtlasAPIError.unknownOutcomeCode,
                        message: "A conexão caiu durante \(method) (\(lastReason)). O resultado é desconhecido: "
                            + "confira o estado antes de repetir.")
                }
                attempt += 1
                if attempt > maxReconnects {
                    publish(.failed(lastReason))
                    throw AtlasAPIError(code: AtlasAPIError.unavailableCode, message: lastReason)
                }
                reconnectCount += 1
                publish(.reconnecting(attempt: attempt))
                Thread.sleep(forTimeInterval: min(backoff * pow(2, Double(attempt - 1)), 3))
            }
        }
    }

    static func describe(_ error: Error) -> String {
        switch error {
        case IPCError.timeout: return "sem resposta dentro do prazo"
        case IPCError.handshakeRejected: return "sessão recusada (expirada?)"
        case IPCError.connectFailed: return "atlas-core não está aceitando conexões"
        case IPCError.connectionClosed: return "conexão encerrada pelo atlas-core"
        case IPCError.mismatchedReply: return "resposta fora de ordem"
        case SupervisorError.notRunning: return "serviços não estão em execução"
        default: return "\(error)"
        }
    }
}

final class CancelBox: @unchecked Sendable {
    private let lock = NSLock()
    private var cancelled = false

    func cancel() {
        lock.lock()
        cancelled = true
        lock.unlock()
    }

    var isCancelled: Bool {
        lock.lock()
        defer { lock.unlock() }
        return cancelled
    }
}
