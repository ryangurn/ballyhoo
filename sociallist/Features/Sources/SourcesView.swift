import SwiftUI

/// Attribution and transparency. Several upstream licenses require visible
/// credit, and showing where a listing came from is also just useful context.
struct SourcesView: View {
    @Environment(EventStore.self) private var store

    private var counts: [(source: Source, count: Int)] {
        Dictionary(grouping: store.upcomingEvents, by: \.source)
            .map { (source: $0.key, count: $0.value.count) }
            .sorted { $0.count > $1.count }
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(counts, id: \.source.id) { entry in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(entry.source.name)
                                    .font(.subheadline.weight(.medium))
                                if let url = entry.source.url {
                                    Text(url.host() ?? url.absoluteString)
                                        .font(.caption)
                                        .foregroundStyle(Theme.inkSecondary)
                                }
                            }

                            Spacer()

                            Text("\(entry.count)")
                                .font(.subheadline.monospacedDigit())
                                .foregroundStyle(Theme.inkSecondary)
                        }
                    }
                } header: {
                    Text("Where these events come from")
                } footer: {
                    Text("Event details are provided by the organizations listed above. Always confirm times and prices on the original listing before heading out.")
                }

                Section("Feed") {
                    LabeledContent("Events") { Text("\(store.upcomingEvents.count)") }
                    LabeledContent("Published") {
                        Text(store.lastUpdated?.formatted(.relative(presentation: .named)) ?? "—")
                    }
                    Button {
                        Task { await store.load(revalidate: true) }
                    } label: {
                        HStack {
                            Text("Refresh now")
                            Spacer()
                            // The feed usually comes back unchanged, so without a
                            // visible in-flight state a working refresh is
                            // indistinguishable from a broken button.
                            if store.state == .loading {
                                ProgressView()
                            }
                        }
                    }
                    .disabled(store.state == .loading)
                }

                Section {
                    Text("Sociallist is free, has no accounts, and collects no personal data. Saved events stay on your device.")
                        .font(.footnote)
                        .foregroundStyle(Theme.inkSecondary)
                }
            }
            .navigationTitle("Sources")
        }
    }
}

#Preview {
    let store = EventStore()
    return SourcesView()
        .environment(store)
        .task { await store.load() }
}
