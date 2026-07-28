## 1. Models

- [ ] 1.1 Create `ballyhoo/Models/SourceHealth.swift`
- [ ] 1.2 Define `SourceStatus` as a `Codable` enum with cases `ok`, `stale`, `error`, and `unknown`, decoding unrecognized raw values to `.unknown` rather than throwing
- [ ] 1.3 Define `SourceHealth` with `sourceID`, `lastRunAt`, `eventCount`, `status`, and an optional per-source feed `url`
- [ ] 1.4 Define `SourceHealthIndex` envelope with `generatedAt` and `sources: [SourceHealth]`
- [ ] 1.5 Reuse the existing `FeedDecoder` date strategy so health timestamps accept the same ISO-8601 variants as the event feed
- [ ] 1.6 Add a computed `stalenessDescription` (or equivalent) producing a human-readable relative age from `lastRunAt`

## 2. Repository abstraction

- [ ] 2.1 Create `ballyhoo/Data/SourceHealthRepository.swift` defining the `SourceHealthRepository` protocol with a single async throwing `fetchHealth()` returning `SourceHealthIndex`
- [ ] 2.2 Implement `MockSourceHealthRepository` returning a fixture index that includes at least one `ok`, one `stale`, and one `error` source, with source IDs matching the mock event fixtures
- [ ] 2.3 Implement `RemoteSourceHealthRepository` fetching over `URLSession.shared` so ETag revalidation applies
- [ ] 2.4 Derive the health index URL from the configured feed URL (`<base>/events.json` → `<base>/sources/index.json`) rather than accepting a second independent URL
- [ ] 2.5 Ensure `FeedSource.mock` resolves to the mock health repository and `.remote(_)` resolves to the remote one, so the two never disagree

## 3. Health store

- [ ] 3.1 Create `ballyhoo/Data/SourceHealthStore.swift` as an `@Observable`, `MainActor`-isolated type
- [ ] 3.2 Model load state explicitly (`idle`, `loading`, `loaded(SourceHealthIndex)`, `failed(String)`)
- [ ] 3.3 Implement `loadIfNeeded()` that fetches only when state is `idle` or `failed`, so repeat tab appearances reuse the cached result
- [ ] 3.4 Implement `refresh()` that always re-fetches, for the explicit refresh control
- [ ] 3.5 Expose a lookup helper returning the `SourceHealth` for a given source id, or `nil` when absent
- [ ] 3.6 Verify no health request is issued on app launch — only on Sources tab appearance

## 4. App wiring

- [ ] 4.1 Construct a `SourceHealthStore` in `BallyhooApp` alongside the existing `EventStore`, using the same `FeedSource`
- [ ] 4.2 Inject it into the environment
- [ ] 4.3 Update every existing `#Preview` that injects `EventStore` to also inject a `SourceHealthStore`, or provide a shared preview helper that injects both

## 5. Sources tab rewrite

- [ ] 5.1 Build the merged row model: union of health-index sources and feed-derived sources, deduplicated by source id
- [ ] 5.2 Populate each row's count from the loaded feed (`store.upcomingEvents` grouped by source), defaulting to zero for sources present only in the index
- [ ] 5.3 Populate each row's status and freshness from the health index, defaulting to `.unknown` for sources present only in the feed
- [ ] 5.4 Sort rows so problem sources are discoverable without burying healthy ones — sort by status severity first, then by count descending
- [ ] 5.5 Render `ok` with no status treatment (name, origin, count only)
- [ ] 5.6 Render `stale` with a cautionary treatment and relative age of the last successful run
- [ ] 5.7 Render `error` with a clear, non-alarming "Currently unavailable" treatment
- [ ] 5.8 Render `unknown` exactly as `ok` is rendered (no treatment)
- [ ] 5.9 Show a loading indicator in the source list area while the first health fetch is in flight
- [ ] 5.10 Preserve the existing "Feed" section (event total, last updated, refresh) and the existing privacy footer
- [ ] 5.11 Wire the existing refresh control to refresh both the feed and the health index
- [ ] 5.12 Add pull-to-refresh on the list, refreshing both

## 6. Graceful degradation

- [ ] 6.1 When the health fetch has failed, render the feed-derived source list exactly as the current implementation does
- [ ] 6.2 Add an unobtrusive footnote indicating source status could not be loaded — no error banner, no blocked tab
- [ ] 6.3 Confirm every source contributing to the loaded feed is still listed with name and origin so attribution obligations hold
- [ ] 6.4 Confirm an explicit refresh retries the health fetch after a failure

## 7. Previews

- [ ] 7.1 Add a preview showing the healthy path (all sources `ok`)
- [ ] 7.2 Add a preview showing a mixed path (`ok`, `stale`, `error` together)
- [ ] 7.3 Add a preview showing a source present in the index with zero events in the feed
- [ ] 7.4 Add a preview showing the degraded path (health fetch failed)
- [ ] 7.5 Add a preview showing the loading path
- [ ] 7.6 Verify all previews render in both Light and Dark appearance

## 8. Decoding resilience

- [ ] 8.1 Add a decoding test feeding an index entry containing an unknown extra field; assert it decodes successfully
- [ ] 8.2 Add a decoding test feeding an unrecognized status string; assert that entry decodes as `.unknown` and the surrounding index still decodes
- [ ] 8.3 Add a decoding test for both ISO-8601 timestamp variants on `last_run_at`
- [ ] 8.4 Add a decoding test for a malformed timestamp; assert a clear `DecodingError` rather than a silently substituted date

## 9. Isolation verification

- [ ] 9.1 Simulate a health fetch failure with a successful feed; confirm all events still display normally across every tab
- [ ] 9.2 Simulate a feed failure with a successful health fetch; confirm the Sources tab still lists configured sources and their status
- [ ] 9.3 Confirm no code path allows a health error to surface as an event-feed error

## 10. Device validation (after the pipeline is live)

- [ ] 10.1 Point the remote implementation at the live `sources/index.json` and confirm it decodes
- [ ] 10.2 Confirm the Sources tab shows real per-source status on a physical iPhone
- [ ] 10.3 Temporarily point at a 404 URL and confirm the degraded path renders correctly on device
- [ ] 10.4 Confirm ETag revalidation on a second Sources tab visit in a new session
- [ ] 10.5 Break one source in the pipeline, wait for it to be marked `stale`, and confirm the tab reflects it honestly rather than dropping the source

## 11. Documentation

- [ ] 11.1 Document in `pipeline/README.md` that per-source `event_count` in the index is pre-dedup and will legitimately differ from the count shown in the app
- [ ] 11.2 Add a doc comment on `SourceHealthRepository` explaining why it is deliberately separate from `EventRepository`
