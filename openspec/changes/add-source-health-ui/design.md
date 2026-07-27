## Context

`add-events-aggregation-pipeline` publishes `sources/index.json` alongside the merged feed, carrying each configured source's `source_id`, `last_run_at`, `event_count`, and `status` (`ok` / `stale` / `error`). Nothing on the client reads it.

Meanwhile `SourcesView` builds its list by grouping `store.upcomingEvents` by `\.source`. That produces a list of "sources that contributed to the current feed", which the UI presents as if it were "our sources". When a source breaks and its events age out, the source vanishes from the tab with no explanation. The tab is at its least informative exactly when a user would most benefit from information.

This change wires the client to the health index and rewrites the tab to be honest about what it knows.

## Goals / Non-Goals

**Goals:**

- A source that is broken or stale stays visible in the Sources tab, correctly labeled.
- Health fetching can never degrade the event feed — separate protocol, separate failure path.
- Only pay for the health fetch when the user actually opens the tab.
- Fall back cleanly to today's behavior when health is unavailable, with attribution intact.
- Keep the visual language calm. This is transparency for a user browsing events, not an on-call dashboard.
- Decode defensively so pipeline-side additions never break shipped clients in the field.

**Non-Goals:**

- No push notifications or in-app alerts about source health.
- No uptime history, error logs, or charts.
- No user controls to enable/disable sources.
- No environment (staging/production) indicator — that belongs to `add-staging-feed`.
- No change to how events themselves are fetched, decoded, filtered, or displayed.

## Decisions

**A separate `SourceHealthRepository` protocol, not an extension of `EventRepository`.**
Health is a different artifact with different failure semantics, a different fetch cadence, and a different criticality. If health fetching lived on `EventRepository`, a health failure would sit in the same error path as a feed failure and would tempt implementations to fail the whole load. A separate protocol makes the independence structural rather than a matter of discipline. Alternative considered: add a `fetchHealth()` method to `EventRepository`. Rejected — couples two unrelated concerns and makes the mock/remote pair harder to reason about.

**A dedicated lightweight `SourceHealthStore`, not new state on `EventStore`.**
`EventStore` is already the largest type in the app and owns the feed, filters, and bookmarks. Health has its own load state, its own lifecycle (lazy, tab-scoped), and its own failure mode. Putting it on `EventStore` would mean `EventStore.state` has to represent two independent loads, or we add a parallel `healthState` and the type keeps growing. A small `@Observable SourceHealthStore` injected into the environment alongside `EventStore` keeps both types coherent. Alternative considered: put it on `EventStore` for convenience. Rejected on cohesion grounds; the cost of a second small store is low.

**Lazy fetch on Sources tab appearance, cached for the session.**
Sources is a rarely-visited tab. Fetching health on cold launch would add a request to the critical path for data almost no user will look at. Fetch on first appearance, cache in the store for the session, re-fetch only on explicit refresh. Alternative considered: fetch alongside the feed at launch. Rejected as wasteful. Alternative considered: re-fetch on every appearance. Rejected — a user toggling tabs shouldn't generate repeated requests for data that changes hourly at most.

**Health index URL is derived from the feed URL, not configured separately.**
The remote feed URL is `<base>/events.json`; the health index is `<base>/sources/index.json`. Deriving the second from the first means there is exactly one place to configure the environment, which matters once `add-staging-feed` lands and there are two bases. Alternative considered: a second hardcoded URL. Rejected — two independently-editable URLs will drift, and someone will eventually point a staging build at production health.

**Render the union of index sources and feed sources.**
The index is authoritative for "which sources exist"; the feed is authoritative for "what you can browse right now". Neither alone is sufficient: the index can lag behind a newly added source, and the feed omits broken ones. Union with dedup by source id handles both directions, and the spec pins the behavior for each case.

**Counts come from the feed; status and freshness come from the index.**
The index's `event_count` is what the pipeline fetched at last run — before dedup across sources and before the client's date filtering. Showing it would mean the number in the Sources tab doesn't match what the user can actually find by browsing. Feed-derived counts are the honest ones. The index's count is still useful diagnostically, but not to a user, so it isn't displayed. Alternative considered: show both ("47 fetched, 43 shown"). Rejected as clutter for a user-facing surface.

**Unknown status values degrade to "unknown", not to an error.**
`SourceStatus` decodes from a string with an `unknown` fallback case rather than a strict enum that throws. If the pipeline later adds a `degraded` status, shipped clients render that source without status treatment instead of failing to decode the entire index. Same reasoning as the feed's tolerance for unknown fields.

**Status presentation is calm by default.**
`ok` gets no badge at all — a wall of green checkmarks is noise, and the absence of a warning is the clearest possible signal of health. `stale` and `error` get treatment. This mirrors how the rest of the app handles state (the feed doesn't badge every event as "confirmed").

**Graceful degradation is the existing behavior plus a footnote.**
When health is unavailable, the tab renders exactly what it renders today — feed-derived sources with counts — plus an unobtrusive line noting status couldn't be loaded. No error state, no blocked tab, no retry prompt beyond the refresh control that already exists. Attribution obligations are met by the feed-derived list alone, so degradation is never a compliance problem.

**Mock health repository ships with the mock event repository.**
`FeedSource.mock` should imply mock health, so previews and mock runs never show a health index that disagrees with the mock feed's sources. The mock fixture deliberately includes one healthy, one stale, and one errored source so all three presentation paths are exercised in previews without network access.

## Risks / Trade-offs

- **This change cannot ship before `add-events-aggregation-pipeline` is live.** The remote implementation has nothing to fetch until `sources/index.json` exists. → Mitigation: build and review the whole UI against the mock repository; the remote implementation is a thin `URLSession` call added last. Sequencing is a scheduling constraint, not a technical risk.
- **Feed-derived counts and index counts will visibly differ if anyone compares them.** A curious user inspecting the raw JSON might wonder why the tab says 43 and the index says 47. → Acceptable; the index is a pipeline artifact, and the discrepancy is correct behavior (dedup and filtering). Documented in the pipeline README.
- **Session-scoped caching means a source that recovers mid-session still shows stale until refresh.** → Acceptable and expected; the refresh control is right there, and health changes on an hourly cadence at most.
- **A source removed from the pipeline entirely will linger in the feed-derived list until its events age out.** → Correct behavior — those events are still browsable, so the source still needs attribution.
- **Two stores in the environment instead of one.** Slightly more wiring in `SociallistApp` and in previews. → Small and worth it for cohesion.
- **The union rule means an index listing a never-launched source shows it with zero events.** Could look odd during pipeline development. → Acceptable; the pipeline only writes index entries for configured sources, and a configured source with zero events is genuinely worth surfacing.

## Migration Plan

1. Land the models and the repository protocol with the mock implementation only.
2. Rewrite `SourcesView` against the mock; verify all four presentation paths (ok, stale, error, unknown) and the degraded path in previews.
3. Add the remote implementation and the URL derivation.
4. Once `add-events-aggregation-pipeline` is live and `sources/index.json` is populated, point the remote implementation at it and verify on device.
5. Verify the degraded path against a real failure by temporarily pointing at a 404 URL.

**Rollback:** revert `SourcesView` to its feed-derived implementation. The models and repository become dead code and can be deleted in the same revert. No persisted state, no migration, no server coordination.

## Open Questions

- Should a stale or errored source's events, if any remain in the feed, be visually marked in the Discover feed too? Leaning no — it would put operational noise into the main browsing surface, and the events themselves are still valid.
- Should the tab show the merge run's `generated_at` separately from per-source freshness? The tab already shows "Last updated" from the feed; adding per-source freshness may make the existing row redundant or confusing. Worth resolving during implementation once both are on screen together.
- Is "Currently unavailable" the right phrasing for `error`, or is something softer better given most users won't care why? Defer to implementation and a look at it on device.
