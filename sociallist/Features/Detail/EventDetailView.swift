import SwiftUI
import MapKit

struct EventDetailView: View {
    let event: Event

    @Environment(EventStore.self) private var store
    @Environment(\.openURL) private var openURL

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

    private var actions: some View {
        HStack(spacing: 10) {
            if let ticketURL = event.ticketURL {
                Link(destination: ticketURL) {
                    Label("Get tickets", systemImage: "ticket.fill")
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .foregroundStyle(.white)
                        .background(Theme.evergreen, in: .rect(cornerRadius: 13))
                }
            } else if let url = event.url {
                Link(destination: url) {
                    Label("View listing", systemImage: "arrow.up.right.square")
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .foregroundStyle(.white)
                        .background(Theme.evergreen, in: .rect(cornerRadius: 13))
                }
            }

            if let venue = event.venue, venue.hasCoordinate {
                Button {
                    openInMaps(venue)
                } label: {
                    Label("Directions", systemImage: "map.fill")
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 12)
                        .foregroundStyle(Theme.evergreen)
                        .background(Theme.evergreen.opacity(0.12), in: .rect(cornerRadius: 13))
                }
                .buttonStyle(.plain)
            }
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
                )
                Divider().padding(.leading, 48)
            }

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
        }
        .padding(14)
    }

    // MARK: Map

    @ViewBuilder
    private var mapSection: some View {
        if let venue = event.venue,
           let latitude = venue.latitude,
           let longitude = venue.longitude {
            let coordinate = CLLocationCoordinate2D(latitude: latitude, longitude: longitude)

            Map(initialPosition: .region(
                MKCoordinateRegion(
                    center: coordinate,
                    span: MKCoordinateSpan(latitudeDelta: 0.01, longitudeDelta: 0.01)
                )
            )) {
                Marker(venue.name, systemImage: event.primaryCategory.symbol, coordinate: coordinate)
                    .tint(Theme.rose)
            }
            .frame(height: 170)
            .clipShape(.rect(cornerRadius: Theme.Radius.card))
            .allowsHitTesting(false)
            .padding(.horizontal, 16)
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

    /// Uses the Maps universal link rather than `MKMapItem`, whose initializers
    /// churned in iOS 26 and would need availability branching.
    private func openInMaps(_ venue: Venue) {
        guard let latitude = venue.latitude, let longitude = venue.longitude else { return }
        var components = URLComponents(string: "http://maps.apple.com/")
        components?.queryItems = [
            URLQueryItem(name: "daddr", value: "\(latitude),\(longitude)"),
            URLQueryItem(name: "q", value: venue.name)
        ]
        guard let url = components?.url else { return }
        openURL(url)
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

#Preview {
    NavigationStack {
        EventDetailView(event: MockData.events[1])
    }
    .environment(EventStore())
}
