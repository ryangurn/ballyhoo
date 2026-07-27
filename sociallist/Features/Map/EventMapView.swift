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

    static func pins(for events: [Event], in region: MKCoordinateRegion) -> [VenuePin] {
        // Stage one: collapse to venues. This is the bulk of the reduction.
        var byVenue: [String: [Event]] = [:]
        for event in events {
            guard let venue = event.venue,
                  let latitude = venue.latitude,
                  let longitude = venue.longitude else { continue }
            // Key on position rather than name so two spellings of one address
            // still land on a single pin.
            byVenue[String(format: "%.5f,%.5f", latitude, longitude), default: []].append(event)
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

struct EventMapView: View {
    @Environment(EventStore.self) private var store

    @State private var position: MapCameraPosition = .region(.portland)
    @State private var visibleRegion: MKCoordinateRegion = .portland
    @State private var selectedPin: VenuePin?
    @State private var detailEvent: Event?

    private var mappableEvents: [Event] {
        store.filteredEvents.filter { $0.venue?.hasCoordinate == true }
    }

    private var pins: [VenuePin] {
        VenueGrouping.pins(for: mappableEvents, in: visibleRegion)
    }

    var body: some View {
        NavigationStack {
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
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(item: $detailEvent) { event in
                EventDetailView(event: event)
            }
            .overlay {
                if mappableEvents.isEmpty, store.state == .loaded {
                    ContentUnavailableView(
                        "Nothing to map",
                        systemImage: "mappin.slash",
                        description: Text("No events match your filters, or they have no location yet.")
                    )
                    .background(.regularMaterial)
                }
            }
        }
    }

    // MARK: Pins

    @ViewBuilder
    private func pinView(_ pin: VenuePin) -> some View {
        let isSelected = selectedPin?.id == pin.id
        let tint = pin.isMerged ? Theme.evergreen : (pin.next?.primaryCategory.tint ?? Theme.evergreen)

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
            .foregroundStyle(.white)
            .frame(width: 32, height: 32)
            .background(tint, in: .circle)
            .overlay(Circle().stroke(.white.opacity(isSelected ? 0.95 : 0.4), lineWidth: isSelected ? 2.5 : 1))
            .shadow(color: .black.opacity(0.3), radius: 3, y: 1)

            // A single venue with a run of events shows how many without needing
            // its own bubble, which keeps one venue reading as one place.
            if !pin.isMerged, pin.count > 1 {
                Text(pin.count > 99 ? "99+" : "\(pin.count)")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(Theme.ink)
                    .padding(.horizontal, 4)
                    .frame(minWidth: 16, minHeight: 16)
                    .background(.white, in: .capsule)
                    .offset(x: 6, y: -4)
            }
        }
        .scaleEffect(isSelected ? 1.2 : 1)
        .animation(.snappy(duration: 0.2), value: isSelected)
        .onTapGesture {
            if pin.isMerged {
                zoom(into: pin)
            } else {
                selectedPin = pin
            }
        }
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
                }
                .buttonStyle(.plain)
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
