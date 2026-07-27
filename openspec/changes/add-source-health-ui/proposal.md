## Why

The Sources tab exists to satisfy attribution obligations (Ticketmaster's ToS, Calagator's CC BY) and to give users honest context about where listings come from. Today it does neither reliably, because it derives the source list by grouping whatever events happen to be in the loaded feed.

That means a source that breaks becomes invisible. If Calagator's workflow fails for three days, its events age out of the merged feed, the grouping produces no Calagator bucket, and the Sources tab simply stops mentioning Calagator. The user sees a shorter list and has no way to know a source died — the tab quietly implies "these are all our sources" when it actually means "these are the sources that contributed to today's feed."

The pipeline already publishes exactly the data needed to fix this. `add-events-aggregation-pipeline` specifies `sources/index.json` with per-source `last_run_at`, `event_count`, and `status` (`ok` / `stale` / `error`). This change is the client half: fetch that index and render honest per-source status.

## What Changes

- Add a `SourceHealth` model and `SourceHealthIndex` envelope mirroring the pipeline's `sources/index.json` contract.
- Add a `SourceHealthRepository` protocol with mock and remote implementations, deliberately **separate** from `EventRepository` so a health-index failure can never degrade or block the event feed.
- Fetch the health index lazily when the Sources tab appears (and on pull-to-refresh), not on app launch — it's a rarely-visited tab and there's no reason to pay for it on every cold start.
- Rewrite `SourcesView` to render the union of (sources present in the health index) and (sources present in the loaded feed), so a source with zero current events still appears, correctly marked.
- Display per-source status calmly: `ok` shows nothing alarming, `stale` shows relative age of the last successful run, `error` shows "Currently unavailable". This is a transparency surface, not an ops dashboard.
- Keep the per-source event count sourced from the **loaded feed** (what the user is actually seeing) rather than the index's `event_count` (what the pipeline last fetched). The two can legitimately differ after dedup and date filtering, and showing the feed-derived number is the honest one.
- Degrade gracefully: if the health index can't be fetched, fall back to today's feed-derived behavior and show a subtle "couldn't load source status" note rather than an error state.

## Capabilities

### New Capabilities

- `source-health-display`: the client's fetch and presentation of per-source health — the health repository abstraction, lazy fetch lifecycle, graceful degradation, and the honest rendering rules for sources absent from the current feed.

### Modified Capabilities

None. `event-data-access` is untouched: health is fetched through its own repository protocol with its own failure semantics, deliberately not bolted onto `EventRepository`.

## Impact

- **New files:**
  - `sociallist/Models/SourceHealth.swift` — `SourceHealth`, `SourceStatus`, `SourceHealthIndex`, and decoding.
  - `sociallist/Data/SourceHealthRepository.swift` — protocol plus `MockSourceHealthRepository` and `RemoteSourceHealthRepository`.
- **Modified files:**
  - `sociallist/Data/EventStore.swift` — gains a health-index URL derived from the same base as the feed URL, and exposes health state to views. (Alternatively a small dedicated `SourceHealthStore`; decided in design.)
  - `sociallist/Features/Sources/SourcesView.swift` — substantially rewritten to merge feed-derived counts with index-derived status.
- **Dependency on `add-events-aggregation-pipeline`:** this change requires `sources/index.json` to exist at the published URL. It cannot ship before that change is live. The mock implementation lets the UI be built and reviewed beforehand.
- **No new third-party dependencies.** Apple frameworks only, consistent with the rest of the app.
- **No change to the event feed path.** `EventRepository`, the `Event` model, and every other view are untouched.
- **Network cost:** one additional small JSON fetch, only when the Sources tab is opened. The index is a handful of entries; expect well under 1 KB. ETag revalidation applies as with the feed.
- **Non-goals:**
  - No push notifications or alerts when a source goes stale.
  - No historical uptime charting or per-source error logs in the app.
  - No user-facing controls to disable or re-enable a source.
  - No "staging vs production" environment indicator (that belongs to `add-staging-feed` if we want it).
