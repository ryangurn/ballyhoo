import SwiftUI

/// Filter controls floating over the top of the map.
///
/// These read and write the same `EventStore` properties the Discover tab binds
/// to rather than keeping a map-local copy. Two independent sets of filters
/// would let the tabs disagree about what the user asked for, which is a worse
/// problem than the one this solves — the map already derives from
/// `filteredEvents`, so the state was always shared and only the controls were
/// missing.
struct MapFilterBar: View {
    @Environment(EventStore.self) private var store

    /// Events currently drawn as pins, and the number of distinct places they
    /// sit at. Passed in rather than recomputed: the map has already done this
    /// work to lay out its annotations.
    let matchedEvents: Int
    let matchedVenues: Int
    /// Every upcoming event with a location, before filters. The denominator
    /// that makes a filtered count mean something.
    let mappableTotal: Int

    @State private var showsCategorySheet = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            controls
            summary
        }
        // Chrome over a map has a budget the rest of the app does not: at the
        // largest accessibility sizes an uncapped bar takes most of the screen
        // and there is no map left to filter. Deliberately applied here and not
        // to the whole view, so the sheet below — where the category controls
        // actually live, on a screen with room for them — scales without a
        // ceiling rather than inheriting this cap through the environment.
        .dynamicTypeSize(...DynamicTypeSize.accessibility2)
        .padding(.top, 8)
        // Deep enough that the clear button's touch area, which overhangs the
        // summary row, stays inside the material rather than over the map.
        .padding(.bottom, 14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.ultraThinMaterial, ignoresSafeAreaEdges: [.top, .horizontal])
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(Theme.hairline)
                .frame(height: 0.5)
        }
        .sheet(isPresented: $showsCategorySheet) {
            CategoryFilterSheet()
        }
    }

    // MARK: Controls

    private var controls: some View {
        HStack(spacing: 10) {
            // Pinned outside the scroll view. Fourteen categories live behind
            // this one chip, so it is the control most worth reaching, and a
            // chip that scrolls away is one the user has to go looking for.
            categoriesChip

            Rectangle()
                .fill(Theme.hairline)
                .frame(width: 1, height: 26)

            ScrollView(.horizontal) {
                HStack(spacing: 8) {
                    if !store.trimmedSearchText.isEmpty {
                        searchChip
                    }

                    FilterChip(
                        title: "Free",
                        systemImage: "gift",
                        isSelected: store.freeOnly,
                        tint: Theme.rose
                    ) {
                        store.freeOnly.toggle()
                    }

                    ForEach(DateWindow.allCases) { window in
                        FilterChip(
                            title: window.title,
                            isSelected: store.dateWindow == window
                        ) {
                            store.dateWindow = window
                        }
                    }
                }
                .padding(.trailing, 16)
            }
            .scrollIndicators(.hidden)
        }
        .padding(.leading, 16)
    }

    private var categoriesChip: some View {
        let count = store.selectedCategories.count

        return Button {
            showsCategorySheet = true
        } label: {
            // The label sheds its text before it sheds the badge: at
            // accessibility sizes on a narrow screen, how many categories are
            // on is the part worth keeping.
            ViewThatFits(in: .horizontal) {
                categoriesLabel(showsTitle: true, count: count)
                categoriesLabel(showsTitle: false, count: count)
            }
            .modifier(ChipStyle(isFilled: count > 0))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Categories")
        .accessibilityValue(categoriesAccessibilityValue)
        .accessibilityHint("Opens the category filter")
    }

    private func categoriesLabel(showsTitle: Bool, count: Int) -> some View {
        HStack(spacing: 5) {
            Image(systemName: "line.3.horizontal.decrease")
                .font(.caption.weight(.semibold))

            if showsTitle {
                Text("Categories")
                    .font(.subheadline.weight(.medium))
                    .lineLimit(1)
            }

            if count > 0 {
                Text("\(count)")
                    .font(.caption2.weight(.bold))
                    .monospacedDigit()
                    .padding(.horizontal, 5)
                    .frame(minWidth: 17)
                    .background(Theme.onTint.opacity(0.22), in: .capsule)
            }
        }
    }

    private var categoriesAccessibilityValue: String {
        // Ordered off `allCases` rather than the store's `availableCategories`,
        // which walks the whole feed to work out what is present. This is read
        // on every pass through `body`; that is not a cost to pay here.
        let selected = Category.allCases.filter(store.selectedCategories.contains)
        guard !selected.isEmpty else { return "All categories" }
        return selected.map(\.title).formatted(.list(type: .and))
    }

    /// A query typed on Discover narrows the map too. Showing it here as a
    /// removable token is the whole point — otherwise it is a filter with no
    /// on-screen cause, which is the failure this bar exists to fix.
    private var searchChip: some View {
        Button {
            store.searchText = ""
        } label: {
            HStack(spacing: 5) {
                Image(systemName: "magnifyingglass")
                    .font(.caption.weight(.semibold))
                Text(store.trimmedSearchText)
                    .font(.subheadline.weight(.medium))
                    .lineLimit(1)
                    .truncationMode(.tail)
                Image(systemName: "xmark")
                    .font(.caption2.weight(.bold))
            }
            .modifier(ChipStyle(isFilled: true, tint: Theme.amber))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Search: \(store.trimmedSearchText)")
        .accessibilityHint("Clears the search")
    }

    // MARK: Summary

    private var summary: some View {
        HStack(spacing: 10) {
            // Line limits sit on the candidates, not the container: an
            // unconstrained `Text` "fits" any width by wrapping, so the long
            // form would always win and the row would grow a second line
            // instead of falling back. The shorter form still truncates if even
            // it runs out of room.
            ViewThatFits(in: .horizontal) {
                Text(longSummary).lineLimit(1)
                Text(shortSummary).lineLimit(1)
            }
            .font(.caption)
            .foregroundStyle(store.hasActiveRefinements ? Theme.ink : Theme.inkSecondary)
            .accessibilityLabel(summaryAccessibilityLabel)

            Spacer(minLength: 0)

            if store.hasActiveRefinements {
                clearButton
            }
        }
        .padding(.horizontal, 16)
    }

    private var clearButton: some View {
        Button {
            store.clearRefinements()
        } label: {
            HStack(spacing: 4) {
                Image(systemName: "xmark.circle.fill")
                Text("Clear")
            }
            .font(.caption.weight(.semibold))
            .foregroundStyle(Theme.rose)
            .frame(minHeight: Theme.minimumTapTarget)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        // The touch area is 44pt and the caption is not, so the label is left to
        // overhang its row rather than paying for the height twice. Nothing
        // clips it, and the bar's bottom padding keeps the overhang on material.
        .frame(height: 18)
        .accessibilityLabel("Clear all filters")
    }

    private var longSummary: String {
        let places = matchedVenues == 1 ? "1 place" : "\(matchedVenues.formatted()) places"

        if store.hasActiveRefinements {
            return "\(matchedEvents.formatted()) of \(mappableTotal.formatted()) events · \(places)"
        }
        let events = matchedEvents == 1 ? "1 event" : "\(matchedEvents.formatted()) events"
        return "\(events) · \(places)"
    }

    private var shortSummary: String {
        if store.hasActiveRefinements {
            return "\(matchedEvents.formatted()) of \(mappableTotal.formatted())"
        }
        return matchedEvents == 1 ? "1 event" : "\(matchedEvents.formatted()) events"
    }

    private var summaryAccessibilityLabel: String {
        let places = matchedVenues == 1 ? "1 place" : "\(matchedVenues.formatted()) places"

        if store.hasActiveRefinements {
            return "Showing \(matchedEvents.formatted()) of \(mappableTotal.formatted()) events, at \(places). Filters are active."
        }
        return "Showing \(matchedEvents.formatted()) events at \(places)."
    }
}

// MARK: - Chip style

/// The `FilterChip` pill treatment, for the two map controls that are not
/// on/off filters and so cannot use `FilterChip` itself — one opens a sheet,
/// one removes a search. Sharing the metrics keeps them from drifting.
private struct ChipStyle: ViewModifier {
    var isFilled: Bool
    var tint: Color = Theme.evergreen

    func body(content: Content) -> some View {
        content
            .padding(.horizontal, 13)
            .padding(.vertical, 8)
            .foregroundStyle(isFilled ? Theme.onTint : Theme.ink)
            .background(
                isFilled ? tint : Theme.surface,
                in: .rect(cornerRadius: Theme.Radius.chip)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.chip)
                    .stroke(isFilled ? .clear : Theme.hairline, lineWidth: 1)
            )
            .frame(minHeight: Theme.minimumTapTarget)
            .contentShape(.rect)
    }
}

// MARK: - Category sheet

/// All fourteen categories, wrapped rather than scrolled.
///
/// Inline on the bar they would need a second horizontal carousel — roughly
/// 1,500pt of chips, four screens of sideways scrolling on a phone to reach
/// Wellness, and a second swipe surface sitting directly on top of a map that
/// pans. A sheet shows every option at once, reads the same on an iPad where
/// there is room for more per row, and costs the map nothing when closed.
struct CategoryFilterSheet: View {
    @Environment(EventStore.self) private var store
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text("Events matching any category you pick.")
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)

                    FlowLayout(spacing: 8) {
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
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
            }
            .background(Theme.canvas)
            .navigationTitle("Categories")
            .toolbarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Clear") {
                        store.selectedCategories = []
                    }
                    .disabled(store.selectedCategories.isEmpty)
                    .accessibilityLabel("Clear selected categories")
                }

                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .fontWeight(.semibold)
                }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }
}

#Preview("Filter bar") {
    let store = EventStore()

    return ZStack(alignment: .top) {
        Color.gray.opacity(0.4).ignoresSafeArea()
        MapFilterBar(matchedEvents: 184, matchedVenues: 63, mappableTotal: 5_867)
    }
    .environment(store)
    .task { await store.load() }
}

#Preview("Category sheet") {
    let store = EventStore()

    return CategoryFilterSheet()
        .environment(store)
        .task { await store.load() }
}
