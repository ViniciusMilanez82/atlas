import Foundation
import Security

public enum KeychainError: Error, Equatable {
    case unexpectedStatus(OSStatus)
    case notFound
    case invalidData
}

/// Generic-password storage in the macOS Keychain (spec 11.4, AT-006.3 building block).
/// Items are device-only and readable only while the Mac is unlocked. The database keeps only a
/// reference (service + account); raw secrets never leave this API except to the trusted caller.
public struct KeychainStore {
    public let service: String

    public init(service: String) {
        self.service = service
    }

    private func query(_ account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    public func set(_ secret: Data, account: String) throws {
        let update = SecItemUpdate(query(account) as CFDictionary, [kSecValueData as String: secret] as CFDictionary)
        if update == errSecSuccess { return }
        guard update == errSecItemNotFound else { throw KeychainError.unexpectedStatus(update) }
        var add = query(account)
        add[kSecValueData as String] = secret
        add[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let status = SecItemAdd(add as CFDictionary, nil)
        guard status == errSecSuccess else { throw KeychainError.unexpectedStatus(status) }
    }

    public func get(account: String) throws -> Data {
        var q = query(account)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        let status = SecItemCopyMatching(q as CFDictionary, &out)
        if status == errSecItemNotFound { throw KeychainError.notFound }
        guard status == errSecSuccess else { throw KeychainError.unexpectedStatus(status) }
        guard let data = out as? Data else { throw KeychainError.invalidData }
        return data
    }

    public func delete(account: String) throws {
        let status = SecItemDelete(query(account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainError.unexpectedStatus(status)
        }
    }
}
