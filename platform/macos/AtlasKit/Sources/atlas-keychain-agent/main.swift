import AtlasKit
import Darwin
import Foundation

// Keychain service of the Supervisor (ADR-001, AT-006.3). Only atlas-core talks to it.
// usage: atlas-keychain-agent <socket-path> <token-file> <keychain-service>
//
// Protocol (same framing as the core): first frame {"hello": <token>, "protocol": "1.0"}; then
// {"op": "put"|"get"|"delete", "locator": str, "secret_b64"?: str} -> {"ok": bool, ...}.
// The socket lives in a private 0700 directory, is chmod 0600, and the peer must run as our UID.
// Secrets are never logged.

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("atlas-keychain-agent: \(message)\n".utf8))
    exit(1)
}

let args = CommandLine.arguments
guard args.count == 4 else { fail("usage: atlas-keychain-agent <socket-path> <token-file> <service>") }
let socketPath = args[1]
let service = args[3]
guard let token = try? String(contentsOfFile: args[2], encoding: .utf8)
    .trimmingCharacters(in: .whitespacesAndNewlines), !token.isEmpty else { fail("cannot read token file") }

let dir = (socketPath as NSString).deletingLastPathComponent
var st = stat()
guard stat(dir, &st) == 0, st.st_mode & 0o077 == 0 else { fail("socket directory must be private (0700)") }

let listener = socket(AF_UNIX, SOCK_STREAM, 0)
guard listener >= 0 else { fail("socket() failed") }
unlink(socketPath)
var addr = sockaddr_un()
addr.sun_family = sa_family_t(AF_UNIX)
let pathBytes = Array(socketPath.utf8)
guard pathBytes.count < MemoryLayout.size(ofValue: addr.sun_path) else { fail("socket path too long") }
withUnsafeMutableBytes(of: &addr.sun_path) { raw in
    for (i, b) in pathBytes.enumerated() { raw[i] = b }
    raw[pathBytes.count] = 0
}
let bound = withUnsafePointer(to: &addr) {
    $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(listener, $0, socklen_t(MemoryLayout<sockaddr_un>.size)) }
}
guard bound == 0 else { fail("bind() failed: \(errno)") }
chmod(socketPath, 0o600)
guard listen(listener, 4) == 0 else { fail("listen() failed") }

let store = KeychainStore(service: service)

func readExact(_ fd: Int32, _ n: Int) -> Data? {
    if n == 0 { return Data() }
    var buffer = [UInt8](repeating: 0, count: n)
    var got = 0
    while got < n {
        let r = buffer.withUnsafeMutableBytes { Darwin.read(fd, $0.baseAddress! + got, n - got) }
        if r <= 0 { return nil }
        got += r
    }
    return Data(buffer)
}

func receive(_ fd: Int32) -> [String: Any]? {
    guard let header = readExact(fd, 4), let n = try? Framing.decodeLength(header),
          let body = readExact(fd, n) else { return nil }
    return try? Framing.decodeBody(body)
}

func reply(_ fd: Int32, _ object: [String: Any]) -> Bool {
    guard let data = try? Framing.encode(object) else { return false }
    return data.withUnsafeBytes { raw -> Bool in
        var sent = 0
        while sent < raw.count {
            let w = Darwin.write(fd, raw.baseAddress! + sent, raw.count - sent)
            if w <= 0 { return false }
            sent += w
        }
        return true
    }
}

func handle(_ request: [String: Any]) -> [String: Any] {
    guard let op = request["op"] as? String, let locator = request["locator"] as? String,
          !locator.isEmpty, locator.count <= 256 else { return ["ok": false, "error": "invalid_request"] }
    do {
        switch op {
        case "put":
            guard let b64 = request["secret_b64"] as? String, let secret = Data(base64Encoded: b64) else {
                return ["ok": false, "error": "invalid_request"]
            }
            try store.set(secret, account: locator)
            return ["ok": true]
        case "get":
            return ["ok": true, "secret_b64": try store.get(account: locator).base64EncodedString()]
        case "delete":
            try store.delete(account: locator)
            return ["ok": true]
        default:
            return ["ok": false, "error": "unknown_op"]
        }
    } catch KeychainError.notFound {
        return ["ok": false, "error": "not_found"]
    } catch {
        return ["ok": false, "error": "keychain_error"]
    }
}

signal(SIGPIPE, SIG_IGN)
while true {
    let conn = accept(listener, nil, nil)
    if conn < 0 { continue }
    var uid: uid_t = 0
    var gid: gid_t = 0
    if getpeereid(conn, &uid, &gid) != 0 || uid != getuid() {
        close(conn)
        continue
    }
    if let hello = receive(conn), hello["protocol"] as? String == "1.0", hello["hello"] as? String == token {
        _ = reply(conn, ["hello": "ok"])
        while let request = receive(conn) {
            if !reply(conn, handle(request)) { break }
        }
    } else {
        _ = reply(conn, ["hello": "rejected"])
    }
    close(conn)
}
