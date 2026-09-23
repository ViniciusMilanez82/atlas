import Foundation
#if canImport(Darwin)
import Darwin
#endif

public enum IPCError: Error {
    case pathTooLong
    case socketFailed(Int32)
    case connectFailed(Int32)
    case connectionClosed
    case handshakeRejected
}

/// Client for the atlas-core Unix-socket IPC (ADR-013). The session token proves identity; the client
/// never sends an actor or role in request bodies.
public final class IPCClient {
    private let fd: Int32
    private var counter = 0

    public init(socketPath: String) throws {
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

    private func sendAll(_ data: Data) throws {
        try data.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            guard let base = raw.baseAddress else { return }
            var sent = 0
            while sent < raw.count {
                let r = Darwin.write(fd, base + sent, raw.count - sent)
                if r <= 0 { throw IPCError.connectionClosed }
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
            if r <= 0 { throw IPCError.connectionClosed }
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
        var p = params
        p["schema_version"] = "1.0"
        p["correlation_id"] = String(format: "swift-%06d", counter)
        try send(["jsonrpc": "2.0", "id": String(format: "sreq-%06d", counter), "method": method, "params": p])
        return try receive()
    }
}
