import Foundation

/// Every event read goes through this protocol, so the fixture-backed and
/// feed-backed implementations stay interchangeable.
///
/// Nothing behind this protocol may contact an upstream source directly: the
/// app only ever reads the single pre-aggregated file the pipeline publishes.
protocol EventRepository {
    /// - Parameter revalidate: Ask the server whether the feed changed, rather than
    ///   trusting its freshness window. Set this for refreshes the user asked for;
    ///   leave it off for automatic loads so they stay cheap.
    func loadFeed(revalidate: Bool) async throws -> EventFeed
}

extension EventRepository {
    func loadFeed() async throws -> EventFeed {
        try await loadFeed(revalidate: false)
    }
}

/// In-memory Portland fixtures, used until the build-time pipeline publishes
/// a real feed.
struct MockEventRepository: EventRepository {
    /// Non-zero so the loading state is actually exercised while developing.
    var latency: Duration = .milliseconds(350)

    func loadFeed(revalidate: Bool = false) async throws -> EventFeed {
        try? await Task.sleep(for: latency)
        return MockData.feed
    }
}

/// Reads the static JSON file the pipeline publishes to a CDN.
struct RemoteEventRepository: EventRepository {
    /// The single file the build-time pipeline publishes. Rebuilt hourly by
    /// GitHub Actions; see `pipeline/` for how it is produced.
    static let productionFeedURL = URL(string: "https://ryangurn.github.io/sociallist/events.json")!

    let feedURL: URL
    var session: URLSession = .shared

    func loadFeed(revalidate: Bool = false) async throws -> EventFeed {
        // A static file behind a CDN, so the shared URL cache handles
        // ETag revalidation without a bespoke caching layer.
        var request = URLRequest(url: feedURL)

        // GitHub Pages serves the feed with `Cache-Control: max-age=600`. Under the
        // default policy URLSession honors that window by answering from the local
        // cache without contacting the server at all, so a user tapping refresh
        // inside ten minutes of the last load would see nothing happen.
        //
        // Revalidating still sends `If-None-Match`, so an unchanged feed costs a 304
        // rather than a full download. The ETag benefit survives; only the blind
        // freshness window is skipped.
        request.cachePolicy = revalidate ? .reloadRevalidatingCacheData : .useProtocolCachePolicy

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse,
              (200..<300).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        return try FeedDecoder.make().decode(EventFeed.self, from: data)
    }
}

extension EventRepository where Self == RemoteEventRepository {
    /// What ships. Previews and tests keep using `.mock` so they stay fast and
    /// work offline.
    static var production: RemoteEventRepository {
        RemoteEventRepository(feedURL: RemoteEventRepository.productionFeedURL)
    }
}

extension EventRepository where Self == MockEventRepository {
    static var mock: MockEventRepository { MockEventRepository() }
}
