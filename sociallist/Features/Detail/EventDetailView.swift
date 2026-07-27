import SwiftUI
import MapKit

struct EventDetailView: View {
    let event: Event

    @Environment(EventStore.self) private var store
    @Environment(\.openURL) private var openURL
    @Environment(\.scenePhase) private var scenePhase

    /// Filled in only for venues the feed could not place. Around a third of the
    /// catalogue arrives with a street address and no coordinates, which is a
    /// map we can draw rather than one we have to skip.
    @State private var geocodedCoordinate: CLLocationCoordinate2D?

    /// What the feed knows, or failing that what we resolved on this screen.
    private var venueCoordinate: CLLocationCoordinate2D? {
        event.venue?.coordinate ?? geocodedCoordinate
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                hero
                header
                actions

                if let summary = event.summary {
                    Text(summary)
                        .font(.body)
                        .foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(.horizontal, 16)
                }

                details
                mapSection
                attribution
            }
            .padding(.bottom, 32)
        }
        .background(Theme.canvas)
        .navigationTitle(event.title)
        .navigationBarTitleDisplayMode(.inline)
        // Keyed on the scene phase so a screen that appeared while the app was
        // still waking — a cold launch straight into an event — gets its one
        // chance once the app is actually active, rather than none at all.
        .task(id: scenePhase) { await locateVenue() }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                SaveButton(isSaved: store.isSaved(event)) {
                    store.toggleSaved(event)
                }
            }
            if let url = event.url {
                ToolbarItem(placement: .topBarTrailing) {
                    ShareLink(item: url) {
                        Image(systemName: "square.and.arrow.up")
                    }
                }
            }
        }
    }

    // MARK: Hero

    private var hero: some View {
        EventThumbnail(event: event, cornerRadius: 0)
            .frame(height: 200)
            .frame(maxWidth: .infinity)
            .overlay(alignment: .bottomLeading) {
                if event.isHappeningNow {
                    HappeningNowBadge()
                        .padding(14)
                }
            }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(event.title)
                .font(.title2.weight(.bold))
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)

            if !event.categories.isEmpty {
                // Wraps rather than scrolls, so no tag is hidden off-screen.
                FlowLayout(spacing: 6) {
                    ForEach(event.categories) { category in
                        CategoryTag(category: category)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 16)
    }

    // MARK: Actions

    /// Directions used to live here beside the ticket link, gated on the venue
    /// having coordinates — so it disappeared for exactly the third of the
    /// catalogue whose location is hardest to find. It now sits on the venue row
    /// with the address it applies to, and this row is the ticket call to action
    /// alone. Nothing is rendered when there is no link, rather than an empty
    /// row the stack still spaces around.
    @ViewBuilder
    private var actions: some View {
        if let ticketURL = event.ticketURL {
            actionLink("Get tickets", systemImage: "ticket.fill", destination: ticketURL)
        } else if let url = event.url {
            actionLink("View listing", systemImage: "arrow.up.right.square", destination: url)
        }
    }

    private func actionLink(_ title: String, systemImage: String, destination: URL) -> some View {
        Link(destination: destination) {
            Label(title, systemImage: systemImage)
                .font(.subheadline.weight(.semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
                .foregroundStyle(.white)
                .background(Theme.evergreen, in: .rect(cornerRadius: 13))
        }
        .padding(.horizontal, 16)
    }

    // MARK: Details

    private var details: some View {
        VStack(spacing: 0) {
            detailRow(
                icon: "calendar",
                title: event.start.relativeDayLabel,
                detail: event.start.formatted(.dateTime.month(.wide).day().year())
            )
            Divider().padding(.leading, 48)

            detailRow(
                icon: "clock",
                title: event.timeRangeLabel,
                detail: event.end.map { _ in "Doors and set times may vary" }
            )
            Divider().padding(.leading, 48)

            if let venue = event.venue {
                detailRow(
                    icon: "mappin.and.ellipse",
                    title: venue.name,
                    detail: [venue.address, venue.neighborhood].compactMap(\.self).joined(separator: ", ")
                ) {
                    // Offered whenever there is somewhere to send them, which
                    // includes a venue we never managed to place ourselves —
                    // Maps can resolve a written address without our help.
                    if canOfferDirections(to: venue) {
                        DirectionsButton { openDirections(to: venue) }
                    }
                }
                Divider().padding(.leading, 48)
            }

            // Unlike the cards, this keeps the "See listing" fallback. They
            // drop it because the badge competes for a 241pt row; a full-width
            // row costs nothing here, and saying nothing would be worse than
            // the fallback — with no price row at all the reader cannot tell an
            // unpriced listing from a free one. The listing button the fallback
            // sends them to is on this screen already.
            detailRow(
                icon: "tag",
                title: event.price.displayText,
                detail: event.price.isFree ? "No ticket required" : nil
            )

            if let organizer = event.organizer {
                Divider().padding(.leading, 48)
                detailRow(icon: "person.2", title: organizer, detail: "Organizer")
            }
        }
        .background(Theme.surface, in: .rect(cornerRadius: Theme.Radius.card))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card)
                .stroke(Theme.hairline, lineWidth: 1)
        )
        .padding(.horizontal, 16)
    }

    private func detailRow(icon: String, title: String, detail: String?) -> some View {
        detailRow(icon: icon, title: title, detail: detail) { EmptyView() }
    }

    private func detailRow<Accessory: View>(
        icon: String,
        title: String,
        detail: String?,
        @ViewBuilder accessory: () -> Accessory
    ) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.subheadline)
                .foregroundStyle(Theme.evergreen)
                .frame(width: 20)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Theme.ink)
                if let detail, !detail.isEmpty {
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(Theme.inkSecondary)
                }
            }
            .fixedSize(horizontal: false, vertical: true)

            Spacer(minLength: 0)

            accessory()
        }
        .padding(14)
    }

    // MARK: Map

    /// Drawn whenever we can place the venue: straight away for the events the
    /// feed carries coordinates for, and a moment later for the ones we geocode.
    /// A venue we cannot place contributes nothing at all — no placeholder, no
    /// spinner, no error. The address still reads in the row above.
    @ViewBuilder
    private var mapSection: some View {
        if let venue = event.venue, let coordinate = venueCoordinate {
            VenueMapCard(
                venue: venue,
                coordinate: coordinate,
                symbol: event.primaryCategory.symbol
            ) {
                // The map answers "where is this", the pill answers "take me
                // there". Two affordances, two different questions.
                openInMaps(venue, directions: false)
            }
            .padding(.horizontal, 16)
            .transition(.opacity)
        }
    }

    // MARK: Locating

    /// At most one geocode for this screen, and only for a venue the feed left
    /// unplaced.
    ///
    /// Apple's rule is to "send at most one geocoding request for any one user
    /// action" and not to geocode while the app is inactive. Opening one event
    /// is one user action about one address. `.task` bounds the work to the
    /// lifetime of this view, and `VenueGeocoder` remembers the answer —
    /// including a failure — so re-running this body, or returning to the event
    /// later, costs nothing and reaches no network.
    private func locateVenue() async {
        guard scenePhase == .active else { return }
        guard let venue = event.venue, !venue.hasCoordinate else { return }

        let coordinate = await VenueGeocoder.shared.coordinate(for: venue)
        guard !Task.isCancelled, let coordinate else { return }
        withAnimation(.easeIn(duration: 0.2)) {
            geocodedCoordinate = coordinate
        }
    }

    // MARK: Maps handoff

    private func canOfferDirections(to venue: Venue) -> Bool {
        venueCoordinate != nil || venue.geocodeQuery != nil
    }

    private func openDirections(to venue: Venue) {
        openInMaps(venue, directions: true)
    }

    /// Hands the venue to Maps, as a point when we have one and as an address
    /// when we do not.
    ///
    /// `MKMapItem(placemark:)` is deprecated as of iOS 26, but the compiler only
    /// diagnoses a deprecation once the deployment target reaches the version it
    /// landed in. At 17.6 this builds clean, and the iOS 26 replacement
    /// `init(location:address:)` would need an availability branch back to this
    /// same call anyway. Verified by compiling both against the iOS 27 SDK.
    private func openInMaps(_ venue: Venue, directions: Bool) {
        let launchOptions = directions
            ? [MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeDefault]
            : nil

        if let coordinate = venueCoordinate {
            let destination = MKMapItem(placemark: MKPlacemark(coordinate: coordinate))
            destination.name = venue.name
            destination.openInMaps(launchOptions: launchOptions)
        } else if let query = venue.geocodeQuery {
            // No coordinate to build an `MKMapItem` around — before iOS 26 there
            // is no address-only initializer — so the written address goes to
            // Maps as a link and Maps runs the lookup we could not.
            var components = URLComponents(string: "https://maps.apple.com/")
            components?.queryItems = [URLQueryItem(name: directions ? "daddr" : "q", value: query)]
            guard let url = components?.url else { return }
            openURL(url)
        }
    }

    // MARK: Attribution

    private var attribution: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Listing from \(event.source.name)")
                .font(.caption)
                .foregroundStyle(Theme.inkSecondary)

            if let sourceURL = event.source.url {
                Link("View on \(event.source.name)", destination: sourceURL)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(Theme.evergreen)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 16)
    }
}

// MARK: - Flow layout

/// Wraps subviews onto new lines when they run out of horizontal room.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        let rows = layout(subviews: subviews, maxWidth: maxWidth)
        let height = rows.reduce(0) { $0 + $1.height } + spacing * CGFloat(max(0, rows.count - 1))
        return CGSize(width: maxWidth == .infinity ? rows.map(\.width).max() ?? 0 : maxWidth, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let rows = layout(subviews: subviews, maxWidth: bounds.width)
        var y = bounds.minY

        for row in rows {
            var x = bounds.minX
            for index in row.indices {
                let size = subviews[index].sizeThatFits(.unspecified)
                subviews[index].place(
                    at: CGPoint(x: x, y: y),
                    anchor: .topLeading,
                    proposal: ProposedViewSize(size)
                )
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private struct Row {
        var indices: [Int] = []
        var width: CGFloat = 0
        var height: CGFloat = 0
    }

    private func layout(subviews: Subviews, maxWidth: CGFloat) -> [Row] {
        var rows: [Row] = []
        var current = Row()

        for index in subviews.indices {
            let size = subviews[index].sizeThatFits(.unspecified)
            let needed = current.indices.isEmpty ? size.width : current.width + spacing + size.width

            if needed > maxWidth, !current.indices.isEmpty {
                rows.append(current)
                current = Row()
                current.indices = [index]
                current.width = size.width
                current.height = size.height
            } else {
                current.indices.append(index)
                current.width = needed
                current.height = max(current.height, size.height)
            }
        }

        if !current.indices.isEmpty { rows.append(current) }
        return rows
    }
}

#Preview("Feed has coordinates") {
    NavigationStack {
        EventDetailView(event: MockData.events[1])
    }
    .environment(EventStore())
}

/// Every mock venue carries coordinates, so the geocoded path is unreachable
/// from the fixtures. These two are shaped like the real DoPDX listings that
/// need it: a street address and nothing else, and a bare venue name.
#Preview("Address only — geocoded on appear") {
    NavigationStack {
        EventDetailView(event: Event(
            id: "dopdx:preview-address-only",
            title: "Open Mic Night",
            summary: "Sign-ups at 6, music at 7. All levels welcome.",
            start: .now.addingTimeInterval(3600),
            venue: Venue(name: "Artichoke Music", address: "2007 SE Powell Blvd", neighborhood: "Portland"),
            categories: [.music, .community],
            price: .free,
            source: Source(id: "dopdx", name: "DoPDX")
        ))
    }
    .environment(EventStore())
}

#Preview("Venue name only — no map, no directions") {
    NavigationStack {
        EventDetailView(event: Event(
            id: "dopdx:preview-name-only",
            title: "Community Potluck",
            start: .now.addingTimeInterval(7200),
            venue: Venue(name: "Trout Lake Hall"),
            categories: [.community],
            price: .free,
            source: Source(id: "dopdx", name: "DoPDX")
        ))
    }
    .environment(EventStore())
}
