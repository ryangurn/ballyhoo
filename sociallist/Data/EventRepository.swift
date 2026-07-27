import Foundation

/// Every event read goes through this protocol, so the fixture-backed and
/// feed-backed implementations stay interchangeable.
///
/// Nothing behind this protocol may contact an upstream source directly: the
/// app only ever reads the single pre-aggregated file the pipeline publishes.
protocol EventRepository {
    func loadFeed() async throws -> EventFeed
}

/// In-memory Portland fixtures, used until the build-time pipeline publishes
/// a real feed.
struct MockEventRepository: EventRepository {
    /// Non-zero so the loading state is actually exercised while developing.
    var latency: Duration = .milliseconds(350)

    func loadFeed() async throws -> EventFeed {
        try? await Task.sleep(for: latency)
        return MockData.feed
    }
}

/// Reads the static JSON file the pipeline publishes to a CDN.
struct RemoteEventRepository: EventRepository {
    let feedURL: URL
    var session: URLSession = .shared

    func loadFeed() async throws -> EventFeed {
        // A static file behind a CDN, so the shared URL cache handles
        // ETag revalidation without a bespoke caching layer.
        var request = URLRequest(url: feedURL)
        request.cachePolicy = .useProtocolCachePolicy

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse,
              (200..<300).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        return try FeedDecoder.make().decode(EventFeed.self, from: data)
    }
}
