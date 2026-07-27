import SwiftUI

struct SavedView: View {
    @Environment(EventStore.self) private var store
    @State private var selectedEvent: Event?

    var body: some View {
        NavigationStack {
            Group {
                if store.savedEvents.isEmpty {
                    ContentUnavailableView {
                        Label("Nothing saved yet", systemImage: "bookmark")
                    } description: {
                        Text("Tap the bookmark on any event to keep it here.")
                    }
                } else {
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            ForEach(store.savedEvents) { event in
                                Button {
                                    selectedEvent = event
                                } label: {
                                    EventRowCard(
                                        event: event,
                                        isSaved: true,
                                        onToggleSave: { store.toggleSaved(event) }
                                    )
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .padding(16)
                    }
                }
            }
            .background(Theme.canvas)
            .navigationTitle("Saved")
            .navigationDestination(item: $selectedEvent) { event in
                EventDetailView(event: event)
            }
        }
    }
}

#Preview {
    let store = EventStore()
    return SavedView()
        .environment(store)
        .task { await store.load() }
}
