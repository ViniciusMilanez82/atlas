import Foundation
#if canImport(Darwin)
import Darwin
#endif

public enum IPCError: Error, Equatable {
    case pathTooLong
    case socketFailed(Int32)
    case connectFailed(Int32)
    case connectionClosed
    case handshakeRejected
    /// No reply within the deadline. The connection must be discarded: a late reply could still arrive.
    case timeout
    /// The reply id does not match the request id (protocol violation): the connection is discarded.
    case mismatchedReply
}

/// Blocking client for the atlas-core Unix-socket IPC (ADR-013). The session token proves identity;
/// the client never sends an actor or role in request bodies. Every read and write has a deadline
/// (SO_RCVTIMEO/SO_SNDTIMEO) and every reply is correlated with its request id.
///
/// Not thread-safe by design: `AtlasConnection` owns one instance and serializes all calls on a
/// private queue, so no socket I/O ever runs on the main thread.
public final class IPCClient {
    private let fd: Int32
    private var counter = 0
    private let prefix = UUID().uuidString.prefix(8).lowercased()

    public init(socketPath: String, timeout: TimeInterval = 30) throws {
        let s = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
        guard s >= 0 else { throw IPCError.socketFailed(errno) }
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let path = Array(socketPath.utf8)
        let capacity = MemoryLayout.size(ofValue: addr.sun_path)
        guard path.count < capacity else {
            Darwin.close(s)
            throw IPCError.pathTooLong
        }
        withUnsafeMutableBytes(of: &addr.sun_path) { raw in
            for (i, b) in path.enumerated() { raw[i] = b }
            raw[path.count] = 0
        }
        var tv = timeval(tv_sec: Int(timeout), tv_usec: Int32((timeout - floor(timeout)) * 1_000_000))
        let tvSize = socklen_t(MemoryLayout<timeval>.size)
        _ = setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, tvSize)
        _ = setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, &tv, tvSize)
        var noSigPipe: Int32 = 1
        _ = setsockopt(s, SOL_SOCKET, SO_NOSIGPIPE, &noSigPipe, socklen_t(MemoryLayout<Int32>.size))
        let size = socklen_t(MemoryLayout<sockaddr_un>.size)
        let rc = withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.connect(s, $0, size) }
        }
        guard rc == 0 else {
            let e = errno
            Darwin.close(s)
            throw IPCError.connectFailed(e)
        }
        fd = s
    }

    deinit { Darwin.close(fd) }

    private static func failure(_ result: Int) -> IPCError {
        if result < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) { return .timeout }
        return .connectionClosed
    }

    private func sendAll(_ data: Data) throws {
        try data.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            guard let base = raw.baseAddress else { return }
            var sent = 0
            while sent < raw.count {
                let r = Darwin.write(fd, base + sent, raw.count - sent)
                if r <= 0 { throw IPCClient.failure(r) }
                sent += r
            }
        }
    }

    private func readExact(_ n: Int) throws -> Data {
        if n == 0 { return Data() }
        var buffer = [UInt8](repeating: 0, count: n)
        var got = 0
        while got < n {
            let r = buffer.withUnsafeMutableBytes { raw in Darwin.read(fd, raw.baseAddress! + got, n - got) }
            if r <= 0 { throw IPCClient.failure(r) }
            got += r
        }
        return Data(buffer)
    }

    public func send(_ object: [String: Any]) throws {
        try sendAll(Framing.encode(object))
    }

    public func receive() throws -> [String: Any] {
        let n = try Framing.decodeLength(readExact(4))
        return try Framing.decodeBody(readExact(n))
    }

    public func hello(token: String) throws {
        try send(["hello": token, "protocol": "1.0"])
        let reply = try receive()
        guard reply["hello"] as? String == "ok" else { throw IPCError.handshakeRejected }
    }

    public func call(_ method: String, params: [String: Any]) throws -> [String: Any] {
        counter += 1
        let requestId = "sreq-\(prefix)-\(counter)"
        var p = params
        p["schema_version"] = "1.0"
        p["correlation_id"] = "swift-\(prefix)-\(counter)"
        try send(["jsonrpc": "2.0", "id": requestId, "method": method, "params": p])
        let reply = try receive()
        // Errors raised before the id was parsed come back with a null id; anything else must match.
        if let id = reply["id"] as? String, id != requestId { throw IPCError.mismatchedReply }
        if reply["id"] == nil || reply["id"] is NSNull, reply["error"] == nil { throw IPCError.mismatchedReply }
        return reply
    }
}
