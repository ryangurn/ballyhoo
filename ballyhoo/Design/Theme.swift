import SwiftUI

/// Design tokens. Defined in code rather than an asset catalog so the palette
/// stays reviewable in diffs.
enum Theme {
    // Evergreen and rose: Pacific Northwest forest, City of Roses.
    static let evergreen = Color(light: 0x1F4034, dark: 0x8FD3B6)
    static let rose = Color(light: 0xC2426B, dark: 0xFF8FB0)
    static let amber = Color(light: 0xB4741B, dark: 0xF0B860)

    static let canvas = Color(light: 0xFBF8F4, dark: 0x121311)
    static let surface = Color(light: 0xFFFFFF, dark: 0x1D201C)
    static let surfaceRaised = Color(light: 0xF3EEE7, dark: 0x272B26)

    static let ink = Color(light: 0x191C18, dark: 0xF2F0EB)
    static let inkSecondary = Color(light: 0x5C6158, dark: 0xA8AEA3)
    static let hairline = Color(light: 0xE4DED4, dark: 0x33382F)

    enum Radius {
        static let card: CGFloat = 20
        static let chip: CGFloat = 12
        static let thumbnail: CGFloat = 16
    }
}

extension Category {
    var tint: Color {
        switch self {
        case .music: Color(light: 0x8B3FA8, dark: 0xD9A6EC)
        case .arts: Color(light: 0xC2426B, dark: 0xFF8FB0)
        case .food: Color(light: 0xC05621, dark: 0xF2A365)
        case .community: Color(light: 0x1F6F5C, dark: 0x7FD4BC)
        case .tech: Color(light: 0x2B5FA8, dark: 0x93BEF5)
        case .outdoors: Color(light: 0x3F7A2E, dark: 0x9FD58A)
        case .family: Color(light: 0xB8862B, dark: 0xEFC677)
        case .market: Color(light: 0x9A5B1E, dark: 0xE0AC6B)
        case .nightlife: Color(light: 0x4B3FA8, dark: 0xAFA6F0)
        case .civic: Color(light: 0x4A5568, dark: 0xB0BAC9)
        case .sports: Color(light: 0x1F6FA8, dark: 0x8CC6EE)
        case .film: Color(light: 0x6B3FA8, dark: 0xC2A6EC)
        case .literary: Color(light: 0x8A5A2B, dark: 0xDDB183)
        case .wellness: Color(light: 0xA83F63, dark: 0xEE9EBB)
        }
    }
}

// MARK: - Color helpers

extension Color {
    /// Builds a dynamic color from two hex values so the palette reads as
    /// light/dark pairs at the definition site.
    init(light: UInt32, dark: UInt32) {
        self.init(uiColor: UIColor { traits in
            UIColor(hex: traits.userInterfaceStyle == .dark ? dark : light)
        })
    }
}

private extension UIColor {
    convenience init(hex: UInt32) {
        self.init(
            red: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255,
            alpha: 1
        )
    }
}

// MARK: - Deterministic artwork

/// Most community listings ship without images. Rather than showing a grey box,
/// derive a stable gradient from the event so each card still reads distinctly.
extension Event {
    var placeholderGradient: LinearGradient {
        let tint = primaryCategory.tint
        var hasher = Hasher()
        hasher.combine(id)
        let angle = Double(abs(hasher.finalize()) % 360)

        return LinearGradient(
            colors: [
                tint.opacity(0.95),
                tint.opacity(0.55),
                Theme.evergreen.opacity(0.35)
            ],
            startPoint: UnitPoint(
                x: 0.5 + 0.5 * cos(angle * .pi / 180),
                y: 0.5 + 0.5 * sin(angle * .pi / 180)
            ),
            endPoint: UnitPoint(
                x: 0.5 - 0.5 * cos(angle * .pi / 180),
                y: 0.5 - 0.5 * sin(angle * .pi / 180)
            )
        )
    }
}
