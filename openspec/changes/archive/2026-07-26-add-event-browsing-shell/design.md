## Context

sociallist is a new Portland-events app with no first-party backend. The team decided that:

- All event data will come from a single static JSON file published by a future build-time pipeline (GitHub Actions cron) that aggregates five upstream sources.
- No API keys ship in the app binary; nothing in the app makes upstream calls directly.
- The app should feel like a modern iOS 17+ information app on iPhone and iPad, portrait-only.

The pipeline itself is a separate change that will land next. This design covers only the app shell: the client that will eventually consume that feed. That means the shell has to be built against mock data now, but its data-access shape must be the same contract the pipeline eventually satisfies — otherwise this becomes throwaway work.

## Goals / Non-Goals

**Goals:**

- Establish the normalized `Event` model that the pipeline will target as its output contract.
- Provide a browsing surface (feed + filters + search + saved + map) rich enough to evaluate the UX with realistic Portland fixtures.
- Keep the data source pluggable so the mock-to-remote swap is a single line of code with no view or view-model changes.
- Ship an interface that adapts cleanly to Dark and Light appearances and to iPhone and iPad size classes.
- Cover source-attribution obligations (Ticketmaster's terms, Calagator's license) with a first-class UI surface, not a footnote.

**Non-Goals:**

- No aggregation pipeline in this change. `RemoteEventRepository` is a stub against a placeholder URL.
- No live network calls. `ENABLE_APP_SANDBOX = YES` stays untouched; no ATS or network entitlements adjusted yet.
- No persistence layer beyond a small set of saved-event IDs in `UserDefaults`. Events themselves are not cached to disk — the whole feed is small and cheap to redownload.
- No push notifications, no calendar export, no ticket purchase flow.
- No authentication, accounts, or personalization beyond local bookmarks.

## Decisions

**Repository protocol with mock and remote implementations, selected by an enum.**
Event access is defined by the `EventRepository` protocol. `EventStore` owns exactly one repository, chosen at construction from a `FeedSource` enum with `.mock` and `.remote(URL)` cases. `.production` in the source file is the single line that switches modes. Alternative considered: environment-variable-driven fetcher in `EventStore` directly. Rejected because it couples the mock path to the store and makes testing harder — a protocol lets us stub the store trivially in previews or unit tests.

**Single normalized `Event` type across all upstream sources, with mandatory `Source`.**
Each event decodes into one Swift type regardless of provenance. Provenance is captured as a required, non-optional `Source` value carried through to the UI. Alternative considered: separate `CalagatorEvent`, `TicketmasterEvent`, etc. with a protocol on top. Rejected because it pushes source-shape leakage into views and makes filtering, sorting, and search logic branch per source. Attribution requirements are satisfied by making `Source` mandatory and rendering it in cards, detail, and a dedicated Sources tab.

**Stable event `id` derived from source id + upstream id.**
Bookmarks key off `event.id`, so the pipeline must guarantee IDs are byte-stable across regenerations for unchanged events. This is a contract for the pipeline, but the shell enforces it by making `id` non-optional and by not attempting any client-side ID normalization.

**Feed envelope carrying `generatedAt` timestamp.**
The static JSON file is `{ "generated_at": ISO8601, "events": [...] }`. `generatedAt` is displayed in Sources so users can see freshness, and it lets the pipeline signal "no changes" trivially via ETag on the CDN. Alternative considered: bare `[Event]` array. Rejected — no room for pipeline metadata.

**ISO-8601 decoding with both fractional-seconds and second-precision fallbacks.**
Upstream sources emit ISO-8601 in both shapes. `FeedDecoder` tries `withFractionalSeconds` first, then plain internet datetime, then throws with the offending string in the error message. Alternative considered: mandate a single format at the pipeline layer. Deferred — makes the client more forgiving during pipeline iteration.

**`@Observable` + `MainActor` isolation, not `ObservableObject`.**
`EventStore` is `@Observable` (iOS 17+) with the project's default MainActor isolation. Alternative considered: pre-Observation `ObservableObject` for compatibility. Rejected — iOS 17 is the deployment target; Observation is a strict win on ergonomics and update cost.

**`UserDefaults` for saved-event IDs.**
Bookmarks are a `Set<String>` of event IDs, persisted in `UserDefaults` under `saved_event_ids`. Alternatives considered: SwiftData, Core Data, a file on disk. Rejected — the data is tiny (a set of short strings), never syncs, and any storage layer beyond UserDefaults is overkill for v1. If bookmarks grow to include annotations, ratings, or iCloud sync, we'll revisit.

**Deterministic gradient fallback for events without artwork.**
Most community listings have no image URL. Rather than a grey box, the card generates a two-color gradient derived from a hash of `event.id`. Same event always renders the same gradient. Category symbol overlays the gradient. Alternative considered: a shared set of stock images. Rejected — feels generic across a mixed feed and cannot signal category.

**Day-bucketed feed with editorial rails on top.**
Discover shows two horizontal rails ("Tonight", "Free in the next 48 hours") above the main day-grouped list. Rails give the feed an editorial hook without editorial work; they're computed from the same event set on the fly. Alternative considered: a single chronological list with no rails. Rejected — a bare list makes the feed feel like a spreadsheet.

**iOS 17 minimum, `@available` for anything newer.**
Deployment target is iOS 17.0 to maximize reach. Any iOS 18+ or iOS 26+ API is used only inside `#available` / `@available` gates with an iOS 17-compatible fallback path. The subagent that built the shell caught `Tab` (iOS 18) and `MKAddress` (iOS 26) during a real-device build and rewrote both to iOS 17 equivalents.

## Risks / Trade-offs

- **Mock data drift.** The mock fixtures shape the `Event` model, but the pipeline's real upstream data will surface edge cases the mocks don't cover (nested venues, sparse fields, weird timezones). → Mitigation: `FeedDecoder` is deliberately lenient about date formats and the model uses `Optional` liberally for anything non-essential (venue, image, ticketURL, organizer).
- **Static-file architecture doesn't scale to per-user personalization.** As soon as the app wants "events near me right now", a client-side filter over a national or long-tail feed becomes wasteful. → Mitigation: for v1 the feed is Portland-only, so total size stays small. When personalization arrives, we'll revisit whether to shard the feed by neighborhood or introduce query params.
- **No cache invalidation strategy beyond ETag.** If the CDN caches too aggressively or if we push a bad feed, the app can go stale or show broken data. → Mitigation: the shared URL cache handles ETag revalidation. If we hit a bad feed, the pipeline can push a corrected one within minutes.
- **`UserDefaults` bookmarks aren't backed up separately from app data.** If the user deletes and reinstalls, bookmarks are lost. → Acceptable for v1; iCloud key-value sync is a small follow-up when we care.
- **`INFOPLIST_KEY_UISupportedInterfaceOrientations = UIInterfaceOrientationPortrait` locks iPad to portrait too.** iPad users usually expect landscape. → Explicit product decision (portrait-only); revisit if iPad usage is meaningful.
