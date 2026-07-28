import SwiftUI

@main
struct BallyhooApp: App {
    @State private var store = EventStore(repository: .production)

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
