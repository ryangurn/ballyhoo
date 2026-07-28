import MapKit
import SwiftUI

/// A still map of where an event is, sized to sit in the detail screen's column
/// of cards and carrying the same hairline border as the one above it.
struct VenueMapCard: View {
    let venue: Venue
    let coordinate: CLLocationCoordinate2D
    let symbol: String
    let action: () -> Void

    /// Tight enough to read the block the venue is on, wide enough to show the
    /// couple of arterials that place it.
    private static let span = MKCoordinateSpan(latitudeDelta: 0.008, longitudeDelta: 0.008)

    var body: some View {
        Button(action: action) {
            Map(initialPosition: .region(MKCoordinateRegion(center: coordinate, span: Self.span))) {
                Marker(venue.name, systemImage: symbol, coordinate: coordinate)
                    .tint(Theme.rose)
            }
            // The map handles none of its own gestures. Panning it inside a
            // ScrollView fights the scroll, and a map that swallowed taps would
            // stop the card from opening Maps. Hits land on the button instead.
            .allowsHitTesting(false)
            // The frame is the parent and the map fills it, so nothing here can
            // report a size larger than its slot and grow past the clip.
            .frame(height: 170)
            .clipShape(.rect(cornerRadius: Theme.Radius.card))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.card)
                    .stroke(Theme.hairline, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Show \(venue.name) in Maps")
    }
}

/// Sits beside the venue address. Deliberately small: it is an accessory to the
/// address it belongs to, not a second primary action competing with tickets.
struct DirectionsButton: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label("Directions", systemImage: "arrow.triangle.turn.up.right")
                .font(.caption.weight(.semibold))
                .labelStyle(.titleAndIcon)
                .lineLimit(1)
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .foregroundStyle(Theme.evergreen)
                .background(Theme.evergreen.opacity(0.13), in: .capsule)
                // The venue row is the tightest on the screen — a long venue
                // name sits directly to the left of this. Without both of these
                // the pill wraps and hyphenates instead of squeezing the name.
                .fixedSize()
        }
        .buttonStyle(.plain)
    }
}
