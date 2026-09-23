import Foundation

/// Length-prefixed JSON framing shared with the Python core (core/ipc/framing.py):
/// 4-byte big-endian length followed by a UTF-8 JSON object, at most 1 MiB.
public enum FramingError: Error, Equatable {
    case frameTooLarge(Int)
    case truncated
    case invalidJSON
    case notAnObject
}

public enum Framing {
    public static let maxFrame = 1024 * 1024

    public static func encode(_ object: [String: Any]) throws -> Data {
        let body = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        guard body.count <= maxFrame else { throw FramingError.frameTooLarge(body.count) }
        let n = UInt32(body.count)
        var data = Data([UInt8(n >> 24 & 0xFF), UInt8(n >> 16 & 0xFF), UInt8(n >> 8 & 0xFF), UInt8(n & 0xFF)])
        data.append(body)
        return data
    }

    /// Validates the declared length BEFORE any body is read.
    public static func decodeLength(_ header: Data) throws -> Int {
        let bytes = [UInt8](header)
        guard bytes.count == 4 else { throw FramingError.truncated }
        let n = Int(bytes[0]) << 24 | Int(bytes[1]) << 16 | Int(bytes[2]) << 8 | Int(bytes[3])
        guard n <= maxFrame else { throw FramingError.frameTooLarge(n) }
        return n
    }

    public static func decodeBody(_ body: Data) throws -> [String: Any] {
        guard let value = try? JSONSerialization.jsonObject(with: Data(body)) else { throw FramingError.invalidJSON }
        guard let object = value as? [String: Any] else { throw FramingError.notAnObject }
        return object
    }
}
