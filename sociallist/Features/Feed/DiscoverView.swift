import SwiftUI

struct DiscoverView: View {
    @Environment(EventStore.self) private var store
    @State private var selectedEvent: Event?

    /// The editorial rails only make sense on an unfiltered browse.
    private var showsRails: Bool {
        store.searchText.isEmpty && !store.hasActiveFilters
    }

    var body: some View {
        @Bindable var store = store

        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 22, pinnedViews: []) {
                    filterBar

                    switch store.state {
                    case .idle, .loading:
                        loadingPlaceholder

                    case .failed(let message):
                        failureView(message)

                    case .loaded:
                        if showsRails {
                            tonightRail
                            freeRail
                        }
                        feedSections
                    }
                }
                .padding(.vertical, 12)
            }
            .background(Theme.canvas)
            .scrollDismissesKeyboard(.immediately)
            .navigationTitle("Portland")
            .toolbarTitleDisplayMode(.large)
            .searchable(
                text: $store.searchText,
                placement: .navigationBarDrawer(displayMode: .always),
                prompt: "Search events, venues, neighborhoods"
            )
            .navigationDestination(item: $selectedEvent) { event in
                EventDetailView(event: event)
            }
            .refreshable { await store.load(revalidate: true) }
        }
    }

    // MARK: Filters

    private var filterBar: some View {
        VStack(alignment: .leading, spacing: 10) {
            ScrollView(.horizontal) {
                HStack(spacing: 8) {
                    ForEach(DateWindow.allCases) { window in
                        FilterChip(
                            title: window.title,
                            isSelected: store.dateWindow == window
                        ) {
                            store.dateWindow = window
                        }
                    }
                }
                .padding(.horizontal, 16)
            }
            .scrollIndicators(.hidden)

            ScrollView(.horizontal) {
                HStack(spacing: 8) {
                    FilterChip(
                        title: "Free",
                        systemImage: "gift",
                        isSelected: store.freeOnly,
                        tint: Theme.rose
                    ) {
                        store.freeOnly.toggle()
                    }

                    ForEach(store.availableCategories) { category in
                        FilterChip(
                            title: category.title,
                            systemImage: category.symbol,
                            isSelected: store.selectedCategories.contains(category),
                            tint: category.tint
                        ) {
                            store.toggle(category)
                        }
                    }
                }
                .padding(.horizontal, 16)
            }
            .scrollIndicators(.hidden)

            if store.hasActiveFilters {
                Button("Clear filters", systemImage: "xmark.circle.fill") {
                    store.clearFilters()
                }
                .font(.subheadline)
                .foregroundStyle(Theme.inkSecondary)
                .padding(.horizontal, 16)
            }
        }
    }

    // MARK: Rails

    @ViewBuilder
    private var tonightRail: some View {
        let tonight = store.upcomingEvents.filter { $0.occurs(on: .now) }

        if !tonight.isEmpty {
            VStack(alignment: .leading, spacing: 11) {
                SectionHeader(title: "Tonight", subtitle: "Happening in the next few hours")
                    .padding(.horizontal, 16)

                rail(tonight)
            }
        }
    }

    @ViewBuilder
    private var freeRail: some View {
        let free = store.freeSoon

        if !free.isEmpty {
            VStack(alignment: .leading, spacing: 11) {
                SectionHeader(title: "Free in the next 48 hours", subtitle: "No ticket required")
                    .padding(.horizontal, 16)

                rail(free)
            }
        }
    }

    private func rail(_ events: [Event]) -> some View {
        ScrollView(.horizontal) {
            // Lazy for the same reason as the feed: a rail can hold dozens of cards
            // and only two or three are ever on screen.
            LazyHStack(alignment: .top, spacing: 12) {
                ForEach(events) { event in
                    Button {
                        selectedEvent = event
                    } label: {
                        EventHighlightCard(event: event)
                    }
                    .buttonStyle(.plain)
                }
            }
            // Marks the cards as snap targets. Without it `.viewAligned` has nothing
            // to align to and SwiftUI warns at runtime while scrolling freely.
            .scrollTargetLayout()
            .padding(.horizontal, 16)
        }
        .scrollIndicators(.hidden)
        .scrollTargetBehavior(.viewAligned)
    }

    // MARK: Feed

    @ViewBuilder
    private var feedSections: some View {
        let sections = store.eventsByDay

        if sections.isEmpty {
            emptyResults
        } else {
            // Lazy at both levels. An enclosing LazyVStack only defers its *direct*
            // children, so a plain VStack here would build every day's section — and
            // every card's AsyncImage — the moment the feed appears. With 700+ events
            // that decodes hundreds of images at once and the app is killed for
            // exceeding its memory limit.
            LazyVStack(alignment: .leading, spacing: 22) {
                if showsRails {
                    SectionHeader(title: "All upcoming")
                        .padding(.horizontal, 16)
                }

                ForEach(sections, id: \.day) { section in
                    LazyVStack(alignment: .leading, spacing: 9) {
                        Text(section.day.relativeDayLabel)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(Theme.inkSecondary)
                            .textCase(.uppercase)
                            .kerning(0.5)
                            .padding(.horizontal, 16)

                        ForEach(section.events) { event in
                            Button {
                                selectedEvent = event
                            } label: {
                                EventRowCard(
                                    event: event,
                                    isSaved: store.isSaved(event),
                                    onToggleSave: { store.toggleSaved(event) }
                                )
                            }
                            .buttonStyle(.plain)
                            .padding(.horizontal, 16)
                        }
                    }
                }
            }
        }
    }

    // MARK: States

    private var loadingPlaceholder: some View {
        VStack(spacing: 12) {
            ForEach(0..<5, id: \.self) { _ in
                RoundedRectangle(cornerRadius: Theme.Radius.card)
                    .fill(Theme.surfaceRaised)
                    .frame(height: 104)
            }
        }
        .padding(.horizontal, 16)
        .redacted(reason: .placeholder)
        .accessibilityLabel("Loading events")
    }

    private var emptyResults: some View {
        ContentUnavailableView {
            Label("No events match", systemImage: "magnifyingglass")
        } description: {
            Text("Try a different date range, or clear your filters.")
        } actions: {
            if store.hasActiveFilters {
                Button("Clear filters") { store.clearFilters() }
                    .buttonStyle(.borderedProminent)
                    .tint(Theme.evergreen)
            }
        }
        .padding(.top, 40)
    }

    private func failureView(_ message: String) -> some View {
        ContentUnavailableView {
            Label("Couldn't load events", systemImage: "wifi.exclamationmark")
        } description: {
            Text(message)
        } actions: {
            Button("Try again") {
                Task { await store.load(revalidate: true) }
            }
            .buttonStyle(.borderedProminent)
            .tint(Theme.evergreen)
        }
        .padding(.top, 40)
    }
}

#Preview {
    let store = EventStore()
    return DiscoverView()
        .environment(store)
        .task { await store.load() }
}
