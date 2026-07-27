## Why

sociallist is a new, empty SwiftUI project. Before investing in the build-time
aggregation pipeline, we want to see and react to the actual browsing experience —
the pipeline is only worth building if the app around it is worth using.

Building the UI first also forces us to pin down the normalized `Event` schema from
the consumer side. The pipeline's output contract is easier to get right when it is
derived from what the screens actually need, rather than from whatever shape the
upstream sources happen to return.

The constraint that shapes everything: the app has no backend and never will. Upstream
rate limits are per-key, not per-user, so a shipped API key would cap the entire user
base (Ticketmaster's free tier is 5,000 calls/day in total). The app must therefore read
a single pre-aggregated static file, and nothing in the UI layer may assume it can
query an upstream source directly.

## What Changes

- Introduce a normalized `Event` model that is the contract between the future pipeline
  and the app, plus the `EventFeed` envelope the static JSON file will carry.
- Put all event access behind an `EventRepository` protocol with two implementations:
  a mock repository with realistic Portland fixtures, and a remote repository stubbed
  against the eventual static feed URL. Swapping them is a one-line change.
- Build the browsing UI: a feed of event cards, date/category/price filtering, search,
  an event detail view, a map, and saved events persisted locally.
- Establish a design token layer so the palette and type ramp are reviewable in diffs.

Explicitly not in this change: the GitHub Actions pipeline, any real network calls, any
upstream scraper or API client.

## Capabilities

### New Capabilities

- `event-data-access`: The normalized event schema, the feed envelope, and the
  repository abstraction that keeps mock and remote sources interchangeable.
- `event-feed`: The primary browsing surface — a chronological, grouped feed of events
  with source attribution and image fallbacks.
- `event-filtering`: Narrowing the feed by date window, category, and price, plus
  free-text search.
- `event-detail`: The full record for a single event, including venue, map, and
  outbound links to the source listing.
- `saved-events`: Bookmarking events and browsing them in a dedicated tab, persisted
  across launches.

### Modified Capabilities

None. This is the first change in the project.

## Impact

- `sociallist/Models/` — `Event`, `Venue`, `Price`, `Source`, `Category`, `EventFeed`.
- `sociallist/Data/` — `EventRepository` protocol, mock and remote implementations,
  `EventStore` observable state, saved-event persistence.
- `sociallist/Design/` — design tokens, category tints, deterministic placeholder artwork.
- `sociallist/Features/` — feed, filtering, detail, saved, and map views.
- `sociallist/ContentView.swift` — replaced by a real tabbed root view.
- No new dependencies. Apple frameworks only.
- No entitlement changes. The app makes no network calls in this change, so
  `ENABLE_APP_SANDBOX = YES` needs no adjustment yet; the remote repository is a stub.
