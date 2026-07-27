import Foundation

/// A single event, normalized across every upstream source.
///
/// This is the contract between the build-time aggregation pipeline and the app.
/// The pipeline emits snake_case JSON matching these properties; see `EventFeed`
/// for the envelope and `FeedDecoder` for the decoding configuration.
struct Event: Identifiable, Codable, Hashable {
    /// Stable across pipeline runs: derived from `source.id` + the upstream ID.
    /// Saved-event bookmarks key off this, so it must never be regenerated randomly.
    let id: String
    let title: String
    let summary: String?
    let start: Date
    let end: Date?
    let isAllDay: Bool
    let venue: Venue?
    let categories: [Category]
    let price: Price
    let imageURL: URL?
    let url: URL?
    let ticketURL: URL?
    let organizer: String?
    let source: Source

    init(
        id: String,
        title: String,
        summary: String? = nil,
        start: Date,
        end: Date? = nil,
        isAllDay: Bool = false,
        venue: Venue? = nil,
        categories: [Category] = [],
        price: Price = .unknown,
        imageURL: URL? = nil,
        url: URL? = nil,
        ticketURL: URL? = nil,
        organizer: String? = nil,
        source: Source
    ) {
        self.id = id
        self.title = title
        self.summary = summary
        self.start = start
        self.end = end
        self.isAllDay = isAllDay
        self.venue = venue
        self.categories = categories
        self.price = price
        self.imageURL = imageURL
        self.url = url
        self.ticketURL = ticketURL
        self.organizer = organizer
        self.source = source
    }
}

extension Event {
    var primaryCategory: Category { categories.first ?? .community }

    var isPast: Bool { (end ?? start) < .now }

    var isHappeningNow: Bool {
        guard !isPast else { return false }
        guard let end else { return Calendar.current.isDate(start, equalTo: .now, toGranularity: .hour) }
        return start <= .now && end >= .now
    }

    func occurs(on day: Date) -> Bool {
        let calendar = Calendar.current
        guard let end, !isAllDay else {
            return calendar.isDate(start, inSameDayAs: day)
        }
        // Multi-day events (festivals, exhibitions) should surface on every day they span.
        let dayStart = calendar.startOfDay(for: day)
        guard let dayEnd = calendar.date(byAdding: .day, value: 1, to: dayStart) else {
            return calendar.isDate(start, inSameDayAs: day)
        }
        return start < dayEnd && end >= dayStart
    }

    /// Text the search field matches against.
    var searchHaystack: String {
        [title, summary, venue?.name, venue?.neighborhood, organizer, source.name]
            .compactMap(\.self)
            .joined(separator: " ")
            .lowercased()
    }
}

// MARK: - Venue

struct Venue: Codable, Hashable {
    let name: String
    let address: String?
    let neighborhood: String?
    let latitude: Double?
    let longitude: Double?

    init(
        name: String,
        address: String? = nil,
        neighborhood: String? = nil,
        latitude: Double? = nil,
        longitude: Double? = nil
    ) {
        self.name = name
        self.address = address
        self.neighborhood = neighborhood
        self.latitude = latitude
        self.longitude = longitude
    }

    var hasCoordinate: Bool { latitude != nil && longitude != nil }
}

// MARK: - Price

struct Price: Codable, Hashable {
    let isFree: Bool
    let min: Double?
    let max: Double?

    static let unknown = Price(isFree: false, min: nil, max: nil)
    static let free = Price(isFree: true, min: 0, max: 0)

    static func from(_ amount: Double) -> Price {
        amount <= 0 ? .free : Price(isFree: false, min: amount, max: amount)
    }

    static func range(_ low: Double, _ high: Double) -> Price {
        Price(isFree: false, min: low, max: high)
    }

    var displayText: String {
        if isFree { return "Free" }
        guard let min else { return "See listing" }
        if let max, max > min {
            return "\(Self.currency(min))–\(Self.currency(max))"
        }
        return Self.currency(min)
    }

    private static func currency(_ value: Double) -> String {
        let hasCents = value != value.rounded()
        return value.formatted(.currency(code: "USD").precision(.fractionLength(hasCents ? 2 : 0)))
    }
}

// MARK: - Source

/// Provenance for an event. Ticketmaster's terms and Calagator's license both
/// require attribution, so every event carries the source it came from.
struct Source: Codable, Hashable, Identifiable {
    let id: String
    let name: String
    let url: URL?

    init(id: String, name: String, url: URL? = nil) {
        self.id = id
        self.name = name
        self.url = url
    }

    static let calagator = Source(
        id: "calagator",
        name: "Calagator",
        url: URL(string: "https://calagator.org")
    )
    static let ticketmaster = Source(
        id: "ticketmaster",
        name: "Ticketmaster",
        url: URL(string: "https://www.ticketmaster.com")
    )
    static let eventbrite = Source(
        id: "eventbrite",
        name: "Eventbrite",
        url: URL(string: "https://www.eventbrite.com")
    )
    static let portlandGov = Source(
        id: "portland_gov",
        name: "Portland.gov",
        url: URL(string: "https://www.portland.gov/events")
    )
    static let multcoLib = Source(
        id: "multcolib",
        name: "Multnomah County Library",
        url: URL(string: "https://multcolib.org/events-classes")
    )
    static let oregonMetro = Source(
        id: "oregon_metro",
        name: "Oregon Metro",
        url: URL(string: "https://www.oregonmetro.gov/events")
    )
    static let venueDirect = Source(
        id: "venue",
        name: "Venue listing",
        url: nil
    )
}

// MARK: - Category

enum Category: String, Codable, CaseIterable, Identifiable, Hashable {
    case music
    case arts
    case food
    case community
    case tech
    case outdoors
    case family
    case market
    case nightlife
    case civic
    case sports
    case film
    case literary
    case wellness

    var id: String { rawValue }

    var title: String {
        switch self {
        case .music: "Music"
        case .arts: "Arts"
        case .food: "Food & Drink"
        case .community: "Community"
        case .tech: "Tech"
        case .outdoors: "Outdoors"
        case .family: "Family"
        case .market: "Markets"
        case .nightlife: "Nightlife"
        case .civic: "Civic"
        case .sports: "Sports"
        case .film: "Film"
        case .literary: "Books"
        case .wellness: "Wellness"
        }
    }

    var symbol: String {
        switch self {
        case .music: "music.note"
        case .arts: "paintpalette.fill"
        case .food: "fork.knife"
        case .community: "person.2.fill"
        case .tech: "cpu.fill"
        case .outdoors: "leaf.fill"
        case .family: "figure.and.child.holdinghands"
        case .market: "basket.fill"
        case .nightlife: "moon.stars.fill"
        case .civic: "building.columns.fill"
        case .sports: "figure.run"
        case .film: "film.fill"
        case .literary: "book.fill"
        case .wellness: "heart.fill"
        }
    }
}

// MARK: - Feed envelope

/// Top-level shape of the static JSON file the pipeline publishes.
struct EventFeed: Codable {
    let generatedAt: Date
    let events: [Event]
}

enum FeedDecoder {
    static func make() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .custom { decoder in
            let raw = try decoder.singleValueContainer().decode(String.self)
            guard let date = iso8601.date(from: raw) ?? iso8601NoFraction.date(from: raw) else {
                throw DecodingError.dataCorrupted(
                    .init(codingPath: decoder.codingPath, debugDescription: "Unparseable date: \(raw)")
                )
            }
            return date
        }
        return decoder
    }

    private static let iso8601: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let iso8601NoFraction: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()
}
