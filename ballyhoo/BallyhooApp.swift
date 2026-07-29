import SwiftUI

/// The published feed, unless a UI test asked for fixtures instead.
///
/// App Store screenshots have to show the same city every time, and the live
/// feed shows whatever Portland happens to be doing that morning — a thin
/// Tuesday makes the app look empty through no fault of its own.
///
/// Compiled out of release builds rather than merely guarded at runtime. A
/// sandboxed App Store install has no way to pass launch arguments in, but
/// `#if DEBUG` means the branch is not in the shipped binary to begin with,
/// which is a shorter thing to have to be sure of.
private func launchRepository() -> EventRepository {
    #if DEBUG
    if ProcessInfo.processInfo.arguments.contains("-UITestMockData") {
        return MockEventRepository(latency: .zero)
    }
    #endif
    return .production
}

@main
struct BallyhooApp: App {
    @State private var store = EventStore(repository: launchRepository())

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(store)
                .tint(Theme.evergreen)
                .task { await store.load() }
        }
    }
}

struct RootView: View {
    var body: some View {
        TabView {
            DiscoverView()
                .tabItem { Label("Discover", systemImage: "sparkles") }
            EventMapView()
                .tabItem { Label("Map", systemImage: "map") }
            SavedView()
                .tabItem { Label("Saved", systemImage: "bookmark") }
            SourcesView()
                .tabItem { Label("Sources", systemImage: "info.circle") }
        }
    }
}

#Preview {
    let store = EventStore()
    return RootView()
        .environment(store)
        .tint(Theme.evergreen)
        .task { await store.load() }
}
