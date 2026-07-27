import Foundation
import Observation

enum LoadState: Equatable {
    case idle
    case loading
    case loaded
    case failed(String)
}

@Observable
final class EventStore {

    private(set) var allEvents: [Event] = []
    private(set) var state: LoadState = .idle
    private(set) var lastUpdated: Date?

    // Filters
    var searchText = ""
    var selectedCategories: Set<Category> = []
    var dateWindow: DateWindow = .upcoming
    var freeOnly = false

    private(set) var savedEventIDs: Set<String> = []

    private let repository: EventRepository
    private let defaults: UserDefaults
    private static let savedKey = "saved_event_ids"

    /// Swapping fixtures for the published feed means passing a
    /// `RemoteEventRepository` here; no view changes.
    init(repository: EventRepository = MockEventRepository(), defaults: UserDefaults = .standard) {
        self.repository = repository
        self.defaults = defaults
        self.savedEventIDs = Set(defaults.stringArray(forKey: Self.savedKey) ?? [])
    }

    // MARK: Loading

    /// - Parameter revalidate: Pass `true` for refreshes the user explicitly asked
    ///   for, so the request bypasses the feed's freshness window.
    func load(revalidate: Bool = false) async {
        guard state != .loading else { return }
        state = .loading

        do {
            let feed = try await repository.loadFeed(revalidate: revalidate)
            allEvents = feed.events.sorted { $0.start < $1.start }
            lastUpdated = feed.generatedAt
            state = .loaded
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    // MARK: Derived collections

    /// Everything still in the future, before user filters are applied.
    var upcomingEvents: [Event] {
        allEvents.filter { !$0.isPast }
    }

    var filteredEvents: [Event] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()

        return upcomingEvents.filter { event in
            if freeOnly, !event.price.isFree { return false }

            if !selectedCategories.isEmpty,
               selectedCategories.isDisjoint(with: Set(event.categories)) {
                return false
            }

            if !dateWindow.contains(event) { return false }

            if !query.isEmpty, !event.searchHaystack.contains(query) { return false }

            return true
        }
    }

    /// Filtered events bucketed by calendar day, for the sectioned feed.
    var eventsByDay: [(day: Date, events: [Event])] {
        let calendar = Calendar.current
        let grouped = Dictionary(grouping: filteredEvents) {
            calendar.startOfDay(for: $0.start)
        }
        return grouped
            .map { (day: $0.key, events: $0.value.sorted { $0.start < $1.start }) }
            .sorted { $0.day < $1.day }
    }

    var savedEvents: [Event] {
        allEvents
            .filter { savedEventIDs.contains($0.id) && !$0.isPast }
            .sorted { $0.start < $1.start }
    }

    /// Free events happening in the next 48 hours — the app's editorial hook.
    var freeSoon: [Event] {
        let cutoff = Calendar.current.date(byAdding: .hour, value: 48, to: .now) ?? .now
        return upcomingEvents
            .filter { $0.price.isFree && $0.start <= cutoff }
            .prefix(Self.railLimit)
            .map(\.self)
    }

    /// Today's events, for the "Tonight" rail.
    var tonight: [Event] {
        upcomingEvents
            .filter { $0.occurs(on: .now) }
            .prefix(Self.railLimit)
            .map(\.self)
    }

    /// Rails are an editorial skim, not an exhaustive list — the full set is a
    /// scroll away in the main feed. The cap also keeps each rail small enough to
    /// lay out eagerly, which is what lets the cards agree on a common height.
    private static let railLimit = 10

    var availableCategories: [Category] {
        let present = Set(upcomingEvents.flatMap(\.categories))
        return Category.allCases.filter(present.contains)
    }

    var hasActiveFilters: Bool {
        !selectedCategories.isEmpty || freeOnly || dateWindow != .upcoming
    }

    func clearFilters() {
        selectedCategories = []
        freeOnly = false
        dateWindow = .upcoming
    }

    func toggle(_ category: Category) {
        if selectedCategories.contains(category) {
            selectedCategories.remove(category)
        } else {
            selectedCategories.insert(category)
        }
    }

    // MARK: Saving

    func isSaved(_ event: Event) -> Bool {
        savedEventIDs.contains(event.id)
    }

    func toggleSaved(_ event: Event) {
        if savedEventIDs.contains(event.id) {
            savedEventIDs.remove(event.id)
        } else {
            savedEventIDs.insert(event.id)
        }
        defaults.set(Array(savedEventIDs), forKey: Self.savedKey)
    }
}

// MARK: - Date window

enum DateWindow: String, CaseIterable, Identifiable {
    case upcoming
    case today
    case tomorrow
    case weekend
    case week

    var id: String { rawValue }

    var title: String {
        switch self {
        case .upcoming: "Anytime"
        case .today: "Today"
        case .tomorrow: "Tomorrow"
        case .weekend: "This weekend"
        case .week: "Next 7 days"
        }
    }

    func contains(_ event: Event) -> Bool {
        let calendar = Calendar.current

        switch self {
        case .upcoming:
            return true

        case .today:
            return event.occurs(on: .now)

        case .tomorrow:
            guard let tomorrow = calendar.date(byAdding: .day, value: 1, to: .now) else { return false }
            return event.occurs(on: tomorrow)

        case .weekend:
            return Self.upcomingWeekendDays().contains { event.occurs(on: $0) }

        case .week:
            guard let cutoff = calendar.date(byAdding: .day, value: 7, to: .now) else { return false }
            return event.start <= cutoff
        }
    }

    /// Saturday and Sunday of the current week, or the coming week if the
    /// weekend has already passed.
    private static func upcomingWeekendDays() -> [Date] {
        let calendar = Calendar.current
        return (0..<7).compactMap { offset -> Date? in
            guard let day = calendar.date(byAdding: .day, value: offset, to: .now) else { return nil }
            let weekday = calendar.component(.weekday, from: day)
            return (weekday == 7 || weekday == 1) ? day : nil
        }
    }
}
