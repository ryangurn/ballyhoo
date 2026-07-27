## Why

Sharing an event today shares somebody else's web page. `EventDetailView` puts a single `ShareLink(item: url)` in the toolbar, where `url` is the event's upstream `listing_url`. Tap share on a Calagator listing and your friend receives a Calagator URL. Nothing in the message says the event came from sociallist, nothing brings the recipient back into the app, and if the event has no `listing_url` the share button silently isn't there at all.

That is the wrong artifact in three separate ways. It loses the app: a recipient who already has sociallist installed lands in Safari instead of on the event they were sent. It loses the framing: sociallist's value is the merged, de-duplicated view across ten sources, and a bare upstream URL discards all of it. And it loses attribution in the one place attribution is most likely to be scrutinized — Calagator's CC BY licence and Ticketmaster's terms both attach to redistributed listing data, and a URL with no accompanying text asserts nothing about where the data came from.

This change replaces the bare upstream URL with a deep link the app owns, and a share payload that stands on its own.

## What Changes

- Introduce a canonical deep-link grammar for a single event: `https://ryangurn.github.io/sociallist/e/?id=<event-id>`, with the event id in a **query parameter** rather than a path segment. The colon in `calagator:1250482638` and the fact that GitHub Pages has no per-event directory to serve both push the same way.
- Register a custom URL scheme `sociallist://event?id=<event-id>` carrying the identical grammar. It is the mechanism that works on day one, that works on simulator builds whose bundle id is `devplaceholder.*`, and that the web landing page can attempt before falling back.
- **Do not ship Universal Links in this change, and say why in the design rather than leaving it as an unexplained omission.** GitHub Pages cannot serve the `apple-app-site-association` file with `Content-Type: application/json`, and Apple requires exactly that. This was verified against live sites, not assumed. The HTTPS link format above is nevertheless the format we mint from day one, precisely so that every link shared before Universal Links exist keeps working and upgrades in place the day they do.
- Add a static landing page at `gh-pages:/e/index.html` so an HTTPS deep link opened by someone without the app reaches something honest instead of GitHub's 404. One hand-written file, not a pipeline artifact, not a per-event page.
- Add an `EventLink` value type that parses and formats both URL forms, and a `DeepLinkRouter` that owns pending-link state so a link can arrive before the feed has loaded without being dropped.
- Lift tab selection and the Discover navigation path out of view-local `@State` so an inbound link has somewhere to route to. Today `TabView` has no selection binding and each tab owns a private `selectedEvent`.
- Replace the single toolbar `ShareLink` with two deliberately different actions: **Share event**, whose payload is a self-contained text block (title, date and time, venue, `via <Source>`, the upstream listing URL, and the deep link), and a secondary **Share <Source> listing** that shares the bare upstream URL for the case where a clean link with the upstream site's own preview card is what the recipient actually wants.
- Define what happens when a shared link outlives the event it points at. The feed is a rolling window of roughly 3,650 events; a link is durable and the event is not. The app resolves against the full unfiltered feed, and on a miss shows a single honest "no longer listed" state rather than guessing why.

## Capabilities

### New Capabilities

- `event-deep-linking`: the inbound half. The canonical link grammar and its two URL forms, parsing and rejection rules, the Universal Links prerequisite and why the entitlement is deliberately absent, resolution against the unfiltered feed, the not-found state, routing on cold launch versus warm foreground, and what happens when a link arrives before the feed is ready.
- `event-sharing`: the outbound half. What a share payload contains and why, the mandatory attribution line, the deliberate exclusion of event descriptions from the payload, the separate upstream-listing share action, and the behaviour when an event has no upstream URL to offer.

### Modified Capabilities

None. `event-data-access` is untouched. Resolving an event by id is a lookup over `allEvents`, which the store already exposes; it needs no new repository method, no new feed field, and no change to the published schema. The one rule worth pinning — that resolution reads the unfiltered set rather than `filteredEvents` — is a property of deep linking, not of data access, so it lives in the new spec.

## Impact

- **New files:**
  - `sociallist/Models/EventLink.swift` — the link grammar: format an `Event` (or a bare id) into either URL form, parse either form back into an id, reject everything else.
  - `sociallist/Data/DeepLinkRouter.swift` — an `@Observable` router holding the pending link, the resolved destination, and the not-found state.
  - `sociallist/Features/Detail/EventSharePayload.swift` — payload composition and the attribution line.
  - `sociallist/Features/Detail/EventNotFoundView.swift` — the "no longer listed" destination.
- **Modified files:**
  - `sociallist/SociallistApp.swift` — construct the router, inject it, and attach `onOpenURL`.
  - `sociallist/Features/Feed/DiscoverView.swift` — `NavigationStack` gains a path binding driven by the router; `selectedEvent` stops being private view state.
  - `sociallist/Features/Detail/EventDetailView.swift` — the toolbar share item becomes the payload share, plus the secondary listing share in an overflow menu.
- **New non-Swift artifact:** `e/index.html` on the `gh-pages` branch. Hand-written and committed once. The pipeline neither generates nor touches it, so this does not add per-run churn to a branch that already carries a 3.0 MB `events.json`.
- **Project-level settings the user performs, not the agent:** registering `sociallist` as a URL scheme under `CFBundleURLTypes`. `sociallist.xcodeproj` picks up new source files automatically, but URL types are target configuration and `project.pbxproj` is hand-managed. The Associated Domains entitlement is *not* part of this change; the tasks record exactly what to add if and when the Universal Links prerequisite is met.
- **No new third-party dependencies.** `ShareLink` is iOS 16+, `onOpenURL` is iOS 14+, both are comfortably inside the iOS 17.0 floor and need no `@available` gate.
- **No network cost.** Resolution reads the already-loaded feed. Nothing is fetched to open a link.
- **No user data in a link.** A deep link contains a public event id and nothing else — no device identifier, no share token, no campaign parameter. There is no server to receive one and no intention of adding analytics to shares.
- **Non-goals:**
  - No Universal Links, no Associated Domains entitlement, no AASA file. Blocked on hosting; see design.
  - No per-event web pages and no server-rendered Open Graph tags. The landing page is one static file with generic metadata.
  - No resolution from the `archive` branch. Rejected in design for reasons specific to what that branch is for.
  - No deep links to anything other than a single event — no links to a filtered feed, a source, a date, or the map.
  - No QR codes, no invite flows, no share analytics, no App Clip.
