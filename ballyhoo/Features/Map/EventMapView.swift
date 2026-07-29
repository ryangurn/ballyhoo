import SwiftUI
import MapKit

/// Events grouped by the place they happen.
///
/// The venue is the natural unit for a map. Portland's 722 upcoming events sit at
/// only 47 distinct coordinates — Keller Auditorium alone hosts 84 of them — so
/// plotting one pin per event stacks dozens of identical markers on the same point.
/// No amount of spatial gridding separates coordinates that are equal.
struct VenuePin: Identifiable {
    let id: String
    let name: String
    let coordinate: CLLocationCoordinate2D
    let events: [Event]

    var count: Int { events.count }
    var next: Event? { events.first }
    /// Several venues merged because they were too close to tell apart at this zoom.
    var isMerged: Bool = false
}

enum VenueGrouping {
    /// Pins closer together than roughly this fraction of the visible span would
    /// overlap on screen, so they merge until the user zooms in.
    private static let mergeThreshold = 0.045

    /// Position rounded to about a metre, keyed on rather than name so two
    /// spellings of one address still land on a single pin.
    ///
    /// `nonisolated` because it is a pure function of its argument, and callers
    /// pass it by reference into `compactMap` — which would otherwise mean
    /// converting a main-actor function to an unisolated one.
    nonisolated static func venueKey(for venue: Venue) -> String? {
        guard let latitude = venue.latitude, let longitude = venue.longitude else { return nil }
        return String(format: "%.5f,%.5f", latitude, longitude)
    }

    static func pins(for events: [Event], in region: MKCoordinateRegion) -> [VenuePin] {
        // Stage one: collapse to venues. This is the bulk of the reduction.
        var byVenue: [String: [Event]] = [:]
        for event in events {
            guard let venue = event.venue, let key = venueKey(for: venue) else { continue }
            byVenue[key, default: []].append(event)
        }

        let venues: [VenuePin] = byVenue.compactMap { key, grouped in
            let sorted = grouped.sorted { $0.start < $1.start }
            guard let venue = sorted.first?.venue,
                  let latitude = venue.latitude,
                  let longitude = venue.longitude else { return nil }
            return VenuePin(
                id: key,
                name: venue.name,
                coordinate: CLLocationCoordinate2D(latitude: latitude, longitude: longitude),
                events: sorted
            )
        }

        // Stage two: merge venues that would visually collide at this zoom, so a
        // dense downtown block reads as one pin until it is worth separating.
        let cellLatitude = max(region.span.latitudeDelta * mergeThreshold, 0.00005)
        let cellLongitude = max(region.span.longitudeDelta * mergeThreshold, 0.00005)

        var cells: [String: [VenuePin]] = [:]
        for pin in venues {
            let row = (pin.coordinate.latitude / cellLatitude).rounded()
            let column = (pin.coordinate.longitude / cellLongitude).rounded()
            cells["\(row)_\(column)", default: []].append(pin)
        }

        return cells.map { key, group -> VenuePin in
            if group.count == 1 { return group[0] }
            let merged = group.flatMap(\.events).sorted { $0.start < $1.start }
            let latitude = group.map(\.coordinate.latitude).reduce(0, +) / Double(group.count)
            let longitude = group.map(\.coordinate.longitude).reduce(0, +) / Double(group.count)
            return VenuePin(
                id: key,
                name: "\(group.count) venues",
                coordinate: CLLocationCoordinate2D(latitude: latitude, longitude: longitude),
                events: merged,
                isMerged: true
            )
        }
        // Stable ordering stops SwiftUI reshuffling annotations on every update.
        .sorted { $0.id < $1.id }
    }
}

/// What the store's filters are set to, as one comparable value.
///
/// The map keeps a selected pin, and a filter change can take the events out
/// from under it. Watching the filters as a whole is cheaper than diffing the
/// pins on every pass.
private struct FilterSignature: Equatable {
    let categories: Set<Category>
    let dateWindow: DateWindow
    let freeOnly: Bool
    let search: String

    init(_ store: EventStore) {
        categories = store.selectedCategories
        dateWindow = store.dateWindow
        freeOnly = store.freeOnly
        search = store.trimmedSearchText
    }
}

/// One walk over the store's collections, shared by the map, the filter bar and
/// the status overlay.
///
/// Each of these reads is a filter over the whole feed — about 6,000 events —
/// and SwiftUI re-evaluates computed properties every time they are touched.
/// Gathering them once per pass through `body` keeps that to a single traversal
/// instead of one per consumer.
private struct MapSnapshot {
    let events: [Event]
    let pins: [VenuePin]
    /// Distinct venues, counted before the zoom-dependent merge so the number
    /// does not change as the user pinches.
    let venueCount: Int
    /// Upcoming events with a location, before filters — the denominator.
    let mappableTotal: Int
    let state: LoadState
    /// Whether a feed has arrived at all, which is a different question from
    /// whether the current filters match anything in it.
    let hasContent: Bool
    let filters: FilterSignature

    init(store: EventStore, region: MKCoordinateRegion) {
        let mappable = store.filteredEvents.filter { $0.venue?.hasCoordinate == true }
        events = mappable
        pins = VenueGrouping.pins(for: mappable, in: region)
        venueCount = Set(mappable.compactMap { $0.venue.flatMap(VenueGrouping.venueKey) }).count
        // `upcomingEvents` would say this more plainly, but it materialises a
        // second ~6,000-element array on a path that already built one for
        // `filteredEvents`. Same predicate, counted lazily off the source.
        mappableTotal = store.allEvents.lazy
            .filter { !$0.isPast && $0.venue?.hasCoordinate == true }
            .count
        state = store.state
        hasContent = !store.allEvents.isEmpty
        filters = FilterSignature(store)
    }
}

struct EventMapView: View {
    @Environment(EventStore.self) private var store

    @State private var position: MapCameraPosition = .region(.portland)
    @State private var visibleRegion: MKCoordinateRegion = .portland
    @State private var selectedPin: VenuePin?
    @State private var detailEvent: Event?

    var body: some View {
        let snapshot = MapSnapshot(store: store, region: visibleRegion)

        NavigationStack {
            // A stack rather than a `safeAreaInset`: the map deliberately bleeds
            // under the status bar, and both `safeAreaInset` and `overlay` place
            // their content against the edge the map has already claimed, which
            // would put the bar under the Dynamic Island. As siblings, the map
            // can ignore the top safe area while the bar keeps it.
            ZStack(alignment: .top) {
                map(snapshot)

                // Nothing to filter until a feed arrives, and the loading and
                // failure states own the screen until one does.
                if snapshot.hasContent {
                    MapFilterBar(
                        matchedEvents: snapshot.events.count,
                        matchedVenues: snapshot.venueCount,
                        mappableTotal: snapshot.mappableTotal
                    )
                }
            }
            .onChange(of: snapshot.filters) {
                // The open card would otherwise keep describing a venue that no
                // longer has any matching events behind it.
                selectedPin = nil
            }
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(item: $detailEvent) { event in
                EventDetailView(event: event)
            }
        }
    }

    private func map(_ snapshot: MapSnapshot) -> some View {
        Map(position: $position) {
            ForEach(snapshot.pins) { pin in
                Annotation("", coordinate: pin.coordinate, anchor: .center) {
                    pinView(pin)
                }
                // Titles omitted deliberately: a label beside every pin was the
                // bulk of the clutter, and the card below names the selection.
                .annotationTitles(.hidden)
            }
        }
        .mapStyle(.standard(pointsOfInterest: .excludingAll))
        // Regrouped at the end of a gesture rather than continuously;
        // reclustering every frame of a pinch is wasted work.
        .onMapCameraChange(frequency: .onEnd) { context in
            visibleRegion = context.region
        }
        .ignoresSafeArea(edges: .top)
        .safeAreaInset(edge: .bottom) {
            if let pin = selectedPin {
                venueCard(pin)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 8)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.snappy(duration: 0.25), value: selectedPin?.id)
        .overlay { statusOverlay(snapshot) }
    }

    // MARK: States

    @ViewBuilder
    private func statusOverlay(_ snapshot: MapSnapshot) -> some View {
        if !snapshot.hasContent {
            // Gated on whether there is anything to draw rather than on `state`
            // alone, so a refresh that fails on top of an already-loaded feed
            // leaves the pins where they are instead of blanking the map.
            switch snapshot.state {
            case .idle, .loading:
                loadingState
            case .failed(let message):
                failureState(message)
            case .loaded:
                emptyFeedState
            }
        } else if snapshot.events.isEmpty {
            noMatchesState
        }
    }

    private var loadingState: some View {
        VStack(spacing: 14) {
            ProgressView()
                .controlSize(.large)
            Text("Loading Portland events…")
                .font(.subheadline)
                .foregroundStyle(Theme.inkSecondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.regularMaterial)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Loading events")
    }

    private func failureState(_ message: String) -> some View {
        ContentUnavailableView {
            Label("Couldn't load events", systemImage: "wifi.exclamationmark")
        } description: {
            Text(message)
        } actions: {
            retryButton("Try again")
        }
        .background(.regularMaterial)
    }

    private var emptyFeedState: some View {
        ContentUnavailableView {
            Label("No events yet", systemImage: "calendar.badge.exclamationmark")
        } description: {
            Text("The feed loaded, but had nothing upcoming in it.")
        } actions: {
            retryButton("Check again")
        }
        .background(.regularMaterial)
    }

    private var noMatchesState: some View {
        ContentUnavailableView {
            Label("Nothing to map", systemImage: "mappin.slash")
        } description: {
            Text(
                store.hasActiveRefinements
                    ? "No events match your filters, or the ones that do have no location yet."
                    : "None of the upcoming events have a location yet."
            )
        } actions: {
            if store.hasActiveRefinements {
                Button {
                    store.clearRefinements()
                } label: {
                    tintedButtonLabel("Clear filters")
                }
                .buttonStyle(.borderedProminent)
                .tint(Theme.evergreen)
            }
        }
        .background(.regularMaterial)
    }

    private func retryButton(_ title: String) -> some View {
        Button {
            Task { await store.load(revalidate: true) }
        } label: {
            tintedButtonLabel(title)
        }
        .buttonStyle(.borderedProminent)
        .tint(Theme.evergreen)
    }

    /// `.borderedProminent` draws a white label over the tint, and the tint is a
    /// pale green in dark mode. Setting the label colour explicitly keeps it
    /// readable in both appearances.
    private func tintedButtonLabel(_ title: String) -> some View {
        Text(title)
            .fontWeight(.semibold)
            .foregroundStyle(Theme.onTint)
    }

    // MARK: Pins

    @ViewBuilder
    private func pinView(_ pin: VenuePin) -> some View {
        let isSelected = selectedPin?.id == pin.id
        let tint = pin.isMerged ? Theme.evergreen : (pin.next?.primaryCategory.tint ?? Theme.evergreen)

        // A button rather than a tap gesture, so VoiceOver can reach it and
        // reports it as something to activate.
        Button {
            if pin.isMerged {
                zoom(into: pin)
            } else {
                selectedPin = pin
            }
        } label: {
            ZStack(alignment: .topTrailing) {
                Group {
                    if pin.isMerged {
                        Text("\(pin.count)")
                            .font(.system(size: 13, weight: .bold))
                    } else {
                        Image(systemName: pin.next?.primaryCategory.symbol ?? "mappin")
                            .font(.system(size: 13, weight: .semibold))
                    }
                }
                .foregroundStyle(Theme.onTint)
                .frame(width: 32, height: 32)
                .background(tint, in: .circle)
                .overlay(
                    Circle().stroke(
                        Theme.onTint.opacity(isSelected ? 0.95 : 0.4),
                        lineWidth: isSelected ? 2.5 : 1
                    )
                )
                .shadow(color: .black.opacity(0.3), radius: 3, y: 1)

                // A single venue with a run of events shows how many without needing
                // its own bubble, which keeps one venue reading as one place.
                if !pin.isMerged, pin.count > 1 {
                    Text(pin.count > 99 ? "99+" : "\(pin.count)")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(Theme.ink)
                        .padding(.horizontal, 4)
                        .frame(minWidth: 16, minHeight: 16)
                        .background(Theme.surface, in: .capsule)
                        .offset(x: 6, y: -4)
                }
            }
            .scaleEffect(isSelected ? 1.2 : 1)
            // 32pt of paint, 44pt of target. Sized last so the pin still draws
            // at its own size and still centres on the coordinate.
            .frame(width: Theme.minimumTapTarget, height: Theme.minimumTapTarget)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .animation(.snappy(duration: 0.2), value: isSelected)
        .accessibilityLabel(pinLabel(for: pin))
        .accessibilityHint(pin.isMerged ? "Zooms in to separate these venues" : "Shows what is on here")
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    private func pinLabel(for pin: VenuePin) -> String {
        let events = pin.count == 1 ? "1 event" : "\(pin.count) events"

        guard !pin.isMerged, let next = pin.next else {
            // `name` is already "N venues" for a merged pin.
            return "\(pin.name), \(events)"
        }
        return "\(pin.name), \(events), next \(next.start.relativeDayLabel) at \(next.start.shortTimeLabel)"
    }

    /// Drilling into a merged pin is the only way to reach the venues under it.
    private func zoom(into pin: VenuePin) {
        selectedPin = nil
        let span = MKCoordinateSpan(
            latitudeDelta: max(visibleRegion.span.latitudeDelta / 3, 0.0015),
            longitudeDelta: max(visibleRegion.span.longitudeDelta / 3, 0.0015)
        )
        withAnimation(.easeInOut(duration: 0.4)) {
            position = .region(MKCoordinateRegion(center: pin.coordinate, span: span))
        }
    }

    // MARK: Venue card

    private func venueCard(_ pin: VenuePin) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Text(pin.name)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                    .lineLimit(1)

                Spacer(minLength: 0)

                Text(pin.count == 1 ? "1 event" : "\(pin.count) events")
                    .font(.caption)
                    .foregroundStyle(Theme.inkSecondary)

                Button {
                    selectedPin = nil
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.body)
                        .foregroundStyle(Theme.inkSecondary)
                        .frame(width: Theme.minimumTapTarget, height: Theme.minimumTapTarget)
                        .contentShape(.rect)
                }
                .buttonStyle(.plain)
                // The touch area is 44pt; the row it sits in is not. Letting the
                // label overhang into the card's padding buys the target without
                // making the card taller.
                .frame(width: 24, height: 22)
                .accessibilityLabel("Close venue details")
            }

            // A busy venue can hold dozens of events, so they scroll rather than
            // growing the card off the screen.
            ScrollView(.horizontal) {
                LazyHStack(spacing: 10) {
                    ForEach(pin.events.prefix(20)) { event in
                        Button {
                            detailEvent = event
                        } label: {
                            venueEventRow(event)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .scrollTargetLayout()
            }
            .scrollIndicators(.hidden)
            .scrollTargetBehavior(.viewAligned)
            .frame(height: 62)
        }
        .padding(12)
        .background(.regularMaterial, in: .rect(cornerRadius: Theme.Radius.card))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card)
                .stroke(Theme.hairline, lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.12), radius: 12, y: 4)
    }

    private func venueEventRow(_ event: Event) -> some View {
        HStack(spacing: 9) {
            EventThumbnail(event: event)
                .frame(width: 44, height: 44)

            VStack(alignment: .leading, spacing: 2) {
                Text(event.title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)

                Text("\(event.start.relativeDayLabel) · \(event.start.shortTimeLabel)")
                    .font(.caption2)
                    .foregroundStyle(Theme.inkSecondary)
            }
            .frame(width: 132, alignment: .leading)
        }
        .padding(.trailing, 4)
    }
}

extension MKCoordinateRegion {
    static let portland = MKCoordinateRegion(
        center: CLLocationCoordinate2D(latitude: 45.5230, longitude: -122.6600),
        span: MKCoordinateSpan(latitudeDelta: 0.11, longitudeDelta: 0.11)
    )
}

#Preview {
    let store = EventStore()
    return EventMapView()
        .environment(store)
        .task { await store.load() }
}
