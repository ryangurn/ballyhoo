import SwiftUI
import MapKit

/// Events grouped by the place they happen.
///
/// The venue is the natural unit for a map. Of the live feed's 5,872 events,
/// 4,945 carry a location and those sit at only 692 distinct coordinates — one
/// address alone hosts 166 of them — so plotting one pin per event stacks
/// dozens of identical markers on the same point. No amount of spatial gridding
/// separates coordinates that are equal.
///
/// 692 is still far too many to draw at once, which is what the merge below is
/// for. It is also a number that grows every time a source is added, so the
/// merge has to be sized against the screen rather than tuned to a pin count.
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
    /// How far apart two pins have to sit on screen before they stop competing
    /// for the same touch.
    ///
    /// Twice the tap target rather than exactly one. The merge runs on a grid,
    /// and two venues either side of a cell boundary can be arbitrarily close,
    /// so a cell the size of the target still leaves targets overlapping — and
    /// leaves no bare map between the pins for a pinch to start on. Against the
    /// live feed this is the difference between the pins claiming 84% of a
    /// phone screen at the default zoom and claiming a third of it.
    private static let separation = Theme.minimumTapTarget * 2

    /// `separation` is a distance on glass and a region is measured in degrees,
    /// so something has to stand in for the height of the map view. A phone in
    /// portrait is the case worth tuning for; a taller screen merges a little
    /// more eagerly, which is the harmless direction to be wrong in.
    private static let nominalMapHeight: CGFloat = 850

    private static let mergeThreshold = Double(separation / nominalMapHeight)

    /// Below this the merge stops: two venues five metres apart are the same
    /// place however far the user has zoomed in.
    private static let smallestCell = 0.00005

    /// The grid stage two merges on, quantised to one step per halving of the
    /// zoom.
    ///
    /// The quantising is the point. The camera reports a slightly different
    /// span every time it settles — a pan alone re-derives it — and the cell
    /// size used to track that span exactly, so every camera move re-cut the
    /// grid and handed `ForEach` a different set of pin ids to rebuild. Rounded
    /// like this, a camera delta too small to see produces an identical grid,
    /// identical pins, and no annotation churn at all.
    ///
    /// A span sitting exactly on a bucket boundary can still flip between two
    /// grids, but only across separate gestures: the region is sampled when a
    /// gesture ends, never during one.
    struct MergeGrid: Equatable {
        let latitude: Double
        let longitude: Double

        init(for region: MKCoordinateRegion) {
            latitude = Self.cell(spanning: region.span.latitudeDelta)
            longitude = Self.cell(spanning: region.span.longitudeDelta)
        }

        private static func cell(spanning delta: Double) -> Double {
            guard delta > 0, delta.isFinite else { return smallestCell }
            return max(exp2(log2(delta).rounded()) * mergeThreshold, smallestCell)
        }
    }

    /// Position rounded to about a metre, keyed on rather than name so two
    /// spellings of one address still land on a single pin.
    ///
    /// `nonisolated` because it is a pure function of its argument and nothing
    /// about it wants an actor.
    nonisolated static func venueKey(for venue: Venue) -> String? {
        guard let latitude = venue.latitude, let longitude = venue.longitude else { return nil }
        return String(format: "%.5f,%.5f", latitude, longitude)
    }

    /// Stage one: collapse events to the places they happen. This is the bulk
    /// of the reduction and the expensive half — a pass over every filtered
    /// event, formatting a key for each.
    ///
    /// Split out from the merge below because it does not depend on the camera.
    /// Panning cannot change which venues exist, so a pan must not pay for this.
    static func venues(for events: [Event]) -> [VenuePin] {
        var byVenue: [String: [Event]] = [:]
        for event in events {
            guard let venue = event.venue, let key = venueKey(for: venue) else { continue }
            byVenue[key, default: []].append(event)
        }

        return byVenue.compactMap { key, grouped in
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
        // Stable ordering stops SwiftUI reshuffling annotations on every update.
        .sorted { $0.id < $1.id }
    }

    /// Stage two: merge venues that would visually collide at this zoom, so a
    /// dense downtown block reads as one pin until it is worth separating.
    ///
    /// Cheap — it walks the few hundred venues stage one produced, not the
    /// thousands of events behind them — which is what makes it affordable to
    /// re-run when the zoom changes.
    static func merge(_ venues: [VenuePin], on grid: MergeGrid) -> [VenuePin] {
        var cells: [String: [VenuePin]] = [:]
        for pin in venues {
            let row = (pin.coordinate.latitude / grid.latitude).rounded()
            let column = (pin.coordinate.longitude / grid.longitude).rounded()
            cells["\(row)_\(column)", default: []].append(pin)
        }

        return cells.values.map { group -> VenuePin in
            if group.count == 1 { return group[0] }
            let members = group.map(\.id).sorted()
            let merged = group.flatMap(\.events).sorted { $0.start < $1.start }
            let latitude = group.map(\.coordinate.latitude).reduce(0, +) / Double(group.count)
            let longitude = group.map(\.coordinate.longitude).reduce(0, +) / Double(group.count)
            return VenuePin(
                // Identified by what it contains, not by the cell it landed in.
                // A cell key encodes the zoom, so it changed under every camera
                // move and SwiftUI tore the annotation down and built it again;
                // the members are what the pin actually is, so a group that
                // comes out the same at a different zoom keeps the view it had.
                id: members.joined(separator: "|"),
                name: "\(group.count) venues",
                coordinate: CLLocationCoordinate2D(latitude: latitude, longitude: longitude),
                events: merged,
                isMerged: true
            )
        }
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

/// Everything outside the camera that decides which events the map draws.
///
/// Compared on every pass through `body` to work out whether the snapshot below
/// is still good, so it is deliberately all cheap reads — no collection walks.
private struct MapInputs: Equatable {
    let filters: FilterSignature
    /// A refresh can replace the feed without any filter changing.
    let feedStamp: Date?
    let feedCount: Int

    init(_ store: EventStore) {
        filters = FilterSignature(store)
        feedStamp = store.lastUpdated
        feedCount = store.allEvents.count
    }
}

/// One walk over the store's collections, shared by the map, the filter bar and
/// the status overlay.
///
/// Held in state rather than recomputed inside `body`, because the camera also
/// drives `body` and this is the expensive half: a filter over the whole feed —
/// about 6,000 events — and then a formatted key for each of the ~4,900 with a
/// location. None of that can change while the map is merely being panned, so
/// panning must not pay for it.
private struct MapSnapshot {
    /// What this was built from. A pass that has already seen a new filter but
    /// not yet rebuilt can compare against it and tell that it is holding a
    /// stale answer.
    let inputs: MapInputs
    let events: [Event]
    /// Stage one of the grouping: one entry per distinct coordinate, before the
    /// zoom-dependent merge. The filter bar's "places" count comes off this, so
    /// it has to be taken here — counted off the merged pins it would change as
    /// the user pinched.
    let venues: [VenuePin]
    /// Upcoming events with a location, before filters — the denominator.
    let mappableTotal: Int

    init(store: EventStore) {
        inputs = MapInputs(store)
        let mappable = store.filteredEvents.filter { $0.venue?.hasCoordinate == true }
        events = mappable
        venues = VenueGrouping.venues(for: mappable)
        // `upcomingEvents` would say this more plainly, but it materialises a
        // second ~6,000-element array on a path that already built one for
        // `filteredEvents`. Same predicate, counted lazily off the source.
        mappableTotal = store.allEvents.lazy
            .filter { !$0.isPast && $0.venue?.hasCoordinate == true }
            .count
    }
}

struct EventMapView: View {
    @Environment(EventStore.self) private var store

    @State private var position: MapCameraPosition = .region(.portland)
    @State private var visibleRegion: MKCoordinateRegion = .portland
    @State private var selectedPin: VenuePin?
    @State private var detailEvent: Event?

    /// Nil until the first pass has run. Distinguishable from an empty snapshot
    /// on purpose: "nothing matched" and "not worked out yet" want different
    /// things on screen, and the second lasts one frame.
    @State private var snapshot: MapSnapshot?
    @State private var pins: [VenuePin] = []

    var body: some View {
        let inputs = MapInputs(store)
        let grid = VenueGrouping.MergeGrid(for: visibleRegion)
        // Cheap enough to read live rather than snapshot, and reading it live
        // keeps it honest while the snapshot is a frame behind.
        let hasContent = !store.allEvents.isEmpty
        // The snapshot lags by a pass whenever an input has just changed — the
        // frame a feed lands on, most visibly. A count that is one frame stale
        // is invisible, so the bar can have the snapshot regardless; a stale
        // "nothing matched" is a full-screen panel thrown over a map that does
        // have pins, so that one waits for the rebuild.
        let settled = snapshot?.inputs == inputs ? snapshot : nil

        NavigationStack {
            // A stack rather than a `safeAreaInset`: the map deliberately bleeds
            // under the status bar, and both `safeAreaInset` and `overlay` place
            // their content against the edge the map has already claimed, which
            // would put the bar under the Dynamic Island. As siblings, the map
            // can ignore the top safe area while the bar keeps it.
            ZStack(alignment: .top) {
                map(hasContent: hasContent, settled: settled)

                // Nothing to filter until a feed arrives, and the loading and
                // failure states own the screen until one does.
                if hasContent {
                    MapFilterBar(
                        matchedEvents: snapshot?.events.count ?? 0,
                        matchedVenues: snapshot?.venues.count ?? 0,
                        mappableTotal: snapshot?.mappableTotal ?? 0
                    )
                }
            }
            .onChange(of: inputs, initial: true) {
                rebuild(on: grid)
            }
            .onChange(of: grid) {
                recluster(on: grid)
            }
            .onChange(of: inputs.filters) {
                // The open card would otherwise keep describing a venue that no
                // longer has any matching events behind it. Watched separately
                // from `inputs` so a refresh landing underneath does not close
                // a card the user is reading.
                selectedPin = nil
            }
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(item: $detailEvent) { event in
                EventDetailView(event: event)
            }
        }
    }

    /// Both stages, for when the filters or the feed changed under the map.
    private func rebuild(on grid: VenueGrouping.MergeGrid) {
        let fresh = MapSnapshot(store: store)
        snapshot = fresh
        pins = VenueGrouping.merge(fresh.venues, on: grid)
    }

    /// Stage two alone — the whole cost of a camera move, and only when the
    /// move crossed a zoom step. Leaves the pins alone rather than emptying
    /// them if the camera somehow reports in before the first pass.
    private func recluster(on grid: VenueGrouping.MergeGrid) {
        guard let snapshot else { return }
        pins = VenueGrouping.merge(snapshot.venues, on: grid)
    }

    private func map(hasContent: Bool, settled: MapSnapshot?) -> some View {
        Map(position: $position) {
            ForEach(pins) { pin in
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
        .overlay { statusOverlay(hasContent: hasContent, settled: settled) }
    }

    // MARK: States

    @ViewBuilder
    private func statusOverlay(hasContent: Bool, settled: MapSnapshot?) -> some View {
        if !hasContent {
            // Gated on whether there is anything to draw rather than on `state`
            // alone, so a refresh that fails on top of an already-loaded feed
            // leaves the pins where they are instead of blanking the map.
            switch store.state {
            case .idle, .loading:
                loadingState
            case .failed(let message):
                failureState(message)
            case .loaded:
                emptyFeedState
            }
        } else if let settled, settled.events.isEmpty {
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
        .buttonStyle(MapPinButtonStyle())
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

/// A press with no feedback of its own.
///
/// Pins crowd the busy part of the map, so fingers land on them during pans and
/// pinches that were never aimed at a pin. The built-in styles dim their label
/// on touch-down, which turns that into the annotations twinkling. Selection
/// already announces itself — the pin grows and the card slides up — so the
/// press has nothing left to say.
private struct MapPinButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
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
