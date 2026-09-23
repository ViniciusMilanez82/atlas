import XCTest
@testable import AtlasKit

final class FramingTests: XCTestCase {
    func testRoundTrip() throws {
        let frame = try Framing.encode(["method": "system.health", "n": 1])
        let length = try Framing.decodeLength(frame.prefix(4))
        XCTAssertEqual(length, frame.count - 4)
        let object = try Framing.decodeBody(frame.dropFirst(4))
        XCTAssertEqual(object["method"] as? String, "system.health")
        XCTAssertEqual(object["n"] as? Int, 1)
    }

    func testOversizedLengthIsRejectedBeforeReadingBody() {
        let n = UInt32(Framing.maxFrame + 1)
        let header = Data([UInt8(n >> 24 & 0xFF), UInt8(n >> 16 & 0xFF), UInt8(n >> 8 & 0xFF), UInt8(n & 0xFF)])
        XCTAssertThrowsError(try Framing.decodeLength(header)) { error in
            XCTAssertEqual(error as? FramingError, .frameTooLarge(Framing.maxFrame + 1))
        }
    }

    func testNonObjectAndInvalidJSONRejected() {
        XCTAssertThrowsError(try Framing.decodeBody(Data("[1,2]".utf8)))
        XCTAssertThrowsError(try Framing.decodeBody(Data("{not json".utf8)))
    }

    func testClientRefusesTooLongSocketPath() {
        let path = "/tmp/" + String(repeating: "x", count: 200)
        XCTAssertThrowsError(try IPCClient(socketPath: path))
    }
}

final class KeychainStoreTests: XCTestCase {
    /// Real Keychain round trip with a synthetic value in a throwaway service.
    func testSetGetUpdateDelete() throws {
        let store = KeychainStore(service: "com.atlas.tests.\(UUID().uuidString)")
        let account = "synthetic-account"
        defer { try? store.delete(account: account) }

        try store.set(Data("synthetic-value-1".utf8), account: account)
        XCTAssertEqual(try store.get(account: account), Data("synthetic-value-1".utf8))

        try store.set(Data("synthetic-value-2".utf8), account: account)
        XCTAssertEqual(try store.get(account: account), Data("synthetic-value-2".utf8))

        try store.delete(account: account)
        XCTAssertThrowsError(try store.get(account: account)) { error in
            XCTAssertEqual(error as? KeychainError, .notFound)
        }
    }

    func testServicesAreIsolated() throws {
        let a = KeychainStore(service: "com.atlas.tests.\(UUID().uuidString)")
        let b = KeychainStore(service: "com.atlas.tests.\(UUID().uuidString)")
        defer { try? a.delete(account: "acct") }
        try a.set(Data("synthetic".utf8), account: "acct")
        XCTAssertThrowsError(try b.get(account: "acct"))
    }
}
