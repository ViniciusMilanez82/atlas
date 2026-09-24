import CryptoKit
import Foundation

public enum Hashing {
    public static func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}

public enum MoneyText {
    /// Minor units -> readable money for the owner ("US$ 5,00"), never raw cents.
    public static func format(minor: Int, currency: String = "USD", locale: Locale = Locale(identifier: "pt_BR")) -> String {
        let f = NumberFormatter()
        f.numberStyle = .currency
        f.locale = locale
        f.currencyCode = currency
        let digits = f.maximumFractionDigits
        var divisor = Decimal(1)
        for _ in 0..<max(digits, 0) { divisor *= 10 }
        let value = Decimal(minor) / divisor
        return f.string(from: value as NSDecimalNumber) ?? "\(minor) \(currency)"
    }
}

/// Plain-text preview policy (review A4): text is shown as text; HTML is shown as its source, never
/// rendered, so no script runs and nothing remote is loaded. Binary types get no inline preview.
public enum Preview {
    public static let maxBytes = 256 * 1024

    public static func text(mime: String, data: Data) -> String? {
        let textual = mime.hasPrefix("text/") || mime == "application/json"
        guard textual else { return nil }
        let slice = data.prefix(maxBytes)
        let body = String(decoding: slice, as: UTF8.self)
        return data.count > maxBytes ? body + "\n\n[… pré-visualização truncada …]" : body
    }
}
