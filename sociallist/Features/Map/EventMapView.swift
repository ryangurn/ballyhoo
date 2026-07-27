import SwiftUI
import MapKit

struct EventMapView: View {
    @Environment(EventStore.self) private var store

    @State private var position: MapCameraPosition = .region(.portland)
    @State private var selectedEventID: String?
    @State private var detailEvent: Event?

    private var mappableEvents: [Event] {
        store.filteredEvents.filter { $0.venue?.hasCoordinate == true }
    }

    private var selectedEvent: Event? {
        mappableEvents.first { $0.id == selectedEventID }
    }

    var body: some View {
        NavigationStack {
            Map(position: $position, selection: $selectedEventID) {
                ForEach(mappableEvents) { event in
                    if let venue = event.venue,
                       let latitude = venue.latitude,
                       let longitude = venue.longitude {
                        Marker(
                            event.title,
                            systemImage: event.primaryCategory.symbol,
                            coordinate: CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
                        )
                        .tint(event.primaryCategory.tint)
                        .tag(event.id)
                    }
                }
            }
            .mapStyle(.standard(pointsOfInterest: .excludingAll))
            .safeAreaInset(edge: .bottom) {
                if let event = selectedEvent {
                    selectionCard(event)
                        .padding(.horizontal, 16)
                        .padding(.bottom, 8)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
            .animation(.snappy(duration: 0.25), value: selectedEventID)
            .navigationTitle("Map")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Text("\(mappableEvents.count) events")
                        .font(.caption)
                        .foregroundStyle(Theme.inkSecondary)
                }
            }
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

    private func selectionCard(_ event: Event) -> some View {
        Button {
            detailEvent = event
        } label: {
            HStack(spacing: 12) {
                EventThumbnail(event: event)
                    .frame(width: 54, height: 54)

                VStack(alignment: .leading, spacing: 3) {
                    Text(event.title)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Theme.ink)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)

                    Text("\(event.start.relativeDayLabel) · \(event.start.shortTimeLabel)")
                        .font(.caption)
                        .foregroundStyle(Theme.inkSecondary)

                    Text(event.locationLabel)
                        .font(.caption)
                        .foregroundStyle(Theme.inkSecondary)
                        .lineLimit(1)
                }

                Spacer(minLength: 0)

                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Theme.inkSecondary)
            }
            .padding(12)
            .background(.regularMaterial, in: .rect(cornerRadius: Theme.Radius.card))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.card)
                    .stroke(Theme.hairline, lineWidth: 1)
            )
            .shadow(color: .black.opacity(0.12), radius: 12, y: 4)
        }
        .buttonStyle(.plain)
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
