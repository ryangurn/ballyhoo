import CoreLocation
import Foundation

// MARK: - Venue geocoding input

// Both are pure reads of a value type. They have to say so explicitly: the
// target builds with `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`, so an
// unannotated extension member is main-actor isolated and `VenueGeocoder`
// cannot reach it from its own actor.
extension Venue {
    nonisolated var coordinate: CLLocationCoordinate2D? {
        guard let latitude, let longitude else { return nil }
        return CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
    }

    /// The one-line address to hand a geocoder, or `nil` when there is nothing
    /// worth asking about.
    ///
    /// Only the postal address is sent. Venue names help a search engine but hurt
    /// a geocoder, which wants an address and treats the rest as noise. The city
    /// and state are appended when the address does not already carry them —
    /// roughly half of the address-only listings are bare street lines like
    /// "2007 SE Powell Blvd", which resolve to the wrong metro without them.
    nonisolated var geocodeQuery: String? {
        guard let address = address?.trimmingCharacters(in: .whitespacesAndNewlines),
              !address.isEmpty else { return nil }

        var parts = [address]
        if let city = neighborhood?.trimmingCharacters(in: .whitespacesAndNewlines),
           !city.isEmpty,
           !address.localizedCaseInsensitiveContains(city) {
            parts.append(city)
        }
        // Word-boundary matched: a plain `contains("OR")` is true of "Portland".
        if address.range(of: #"\b(OR|Ore|Oregon)\b"#, options: [.regularExpression, .caseInsensitive]) == nil {
            parts.append("OR")
        }
        return parts.joined(separator: ", ")
    }
}

// MARK: - Geocoder

/// Resolves a street address to a coordinate for the single venue a reader is
/// currently looking at.
///
/// This is the one place in the app allowed to geocode, and the reason is a rule
/// rather than a preference. Apple's documentation says to "send at most one
/// geocoding request for any one user action", rate-limits requests per app, and
/// asks that only one request be in flight at a time. Opening one event is one
/// user action about one address, which is the sanctioned shape. Placing the
/// whole feed is not: that work belongs to the pipeline, and no browsing screen
/// — Discover, Map, Saved — may call this.
///
/// Everything below exists to hold that line. Results are cached, including
/// failures, so a venue is asked about at most once per launch however many
/// times it is revisited; requests for one address are shared rather than
/// duplicated; and a venue the feed already placed never reaches the network.
actor VenueGeocoder {
    static let shared = VenueGeocoder()

    private let geocoder = CLGeocoder()

    /// A `nil` value is a cached failure — asked, could not place it. Kept so an
    /// unresolvable address is not retried on every revisit, which is the case
    /// most likely to burn through the rate limit. It lives in memory only, so a
    /// lookup that failed because the device was offline gets another chance
    /// next launch.
    private var cache: [String: CLLocationCoordinate2D?] = [:]

    /// Callers that arrive while a lookup is running wait on it instead of
    /// starting a second one.
    private var inFlight: [String: Task<CLLocationCoordinate2D?, Never>] = [:]

    func coordinate(for venue: Venue) async -> CLLocationCoordinate2D? {
        // Never spend a request on something the feed already told us.
        if let known = venue.coordinate { return known }
        guard let query = venue.geocodeQuery else { return nil }

        let key = query.lowercased()
        if let cached = cache[key] { return cached }
        if let running = inFlight[key] { return await running.value }

        let task = Task<CLLocationCoordinate2D?, Never> { [geocoder] in
            let placemarks = try? await geocoder.geocodeAddressString(query)
            return placemarks?.first?.location?.coordinate
        }
        inFlight[key] = task

        // Deliberately not cancelled with the caller. A view that disappears
        // mid-flight still wants the answer cached for the next visit, and
        // letting the request finish is cheaper than asking again.
        let coordinate = await task.value

        cache[key] = coordinate
        inFlight[key] = nil
        return coordinate
    }
}
