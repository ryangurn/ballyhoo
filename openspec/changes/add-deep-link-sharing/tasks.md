## 1. Landing page (prerequisite — must land before anything is shareable)

- [ ] 1.1 Write `e/index.html` as a single hand-authored static page: reads `?id=` from the query string, attempts the equivalent `ballyhoo://event?id=…` URL to hand off to an installed app, and otherwise explains what Ballyhoo is and where to get it
- [ ] 1.2 Include a visible source-neutral note that the link points at an event aggregated by Ballyhoo, so a recipient can tell what they are looking at without the app
- [ ] 1.3 Give the page generic Open Graph and `<title>` metadata — per-event metadata is explicitly out of scope and would need server-side rendering
- [ ] 1.4 Handle a missing or empty `id` gracefully rather than rendering a broken state
- [ ] 1.5 Commit the page to the `gh-pages` branch by hand, outside the pipeline, so no workflow generates or rewrites it
- [ ] 1.6 Verify `https://ryangurn.github.io/ballyhoo/e/?id=calagator%3A1250482638` returns HTTP 200 with `text/html` and renders
- [ ] 1.7 Confirm a pipeline publish run leaves the page untouched and does not add it to the archive's per-run churn

## 2. Link grammar

- [ ] 2.1 Create `ballyhoo/Models/EventLink.swift` holding the scheme, host, and path constants in exactly one place
- [ ] 2.2 Implement formatting from an event id to the HTTPS form `https://ryangurn.github.io/ballyhoo/e/?id=<id>`, percent-encoding the colon as `%3A`
- [ ] 2.3 Implement formatting from an event id to the custom-scheme form `ballyhoo://event?id=<id>` using the same encoding
- [ ] 2.4 Add a convenience that formats directly from an `Event`
- [ ] 2.5 Implement parsing that accepts both forms, requires a non-empty `id`, percent-decodes it, and returns the id
- [ ] 2.6 Make parsing strict: reject other hosts, other paths, other custom-scheme hosts, and a missing or empty `id`
- [ ] 2.7 Make parsing forward-compatible: ignore unrecognized additional query parameters rather than rejecting the URL
- [ ] 2.8 Add round-trip tests over ids representative of the live feed — `calagator:1250482638`, `ticketmaster:vv1AaBbCc`, `obt:830`, `oregon_metro:4471`
- [ ] 2.9 Add rejection tests for `https://ryangurn.github.io/ballyhoo/events.json`, `ballyhoo://event`, `ballyhoo://event?id=`, and `ballyhoo://source?id=calagator`
- [ ] 2.10 Add a test asserting `?id=…&ref=newsletter` resolves to the id and ignores `ref`
- [ ] 2.11 Add a test asserting an id containing an already-encoded `%3A` parses identically to a raw colon, so both spellings resolve

## 3. Xcode target configuration — **performed by the user, not the agent**

- [ ] 3.1 **User:** register the URL scheme in the app target's Info settings — add a `CFBundleURLTypes` entry with URL Schemes `ballyhoo` and a URL identifier of `com.ryangurnick.ballyhoo`. `project.pbxproj` is hand-managed in this repo, so no agent edits it
- [ ] 3.2 **User:** confirm the scheme is registered on a simulator build, whose bundle id is `devplaceholder.*` — URL schemes are not bundle-id scoped, so the scheme works there even though a future association file would not
- [ ] 3.3 **User:** do **not** add an Associated Domains entitlement in this change; it would be inert without a valid association file. See section 12 for what to add if the prerequisite is ever met

## 4. Router and navigation lift

- [ ] 4.1 Create `ballyhoo/Data/DeepLinkRouter.swift` as an `@Observable`, `MainActor`-isolated type
- [ ] 4.2 Model the router's state explicitly: no pending link, a pending id awaiting feed load, a resolved event, event-not-found, and feed-load-failed
- [ ] 4.3 Add a tab-selection binding to `TabView` in `BallyhooApp`, replacing the current selection-less `TabView`
- [ ] 4.4 Lift `DiscoverView`'s private `selectedEvent` so the router can drive it, keeping the existing `navigationDestination(item:)` shape
- [ ] 4.5 Leave `EventMapView` and `SavedView` selection state exactly as it is — they are not deep-link destinations
- [ ] 4.6 Verify every existing navigation path still works before layering any deep-link behaviour on top: tapping a card in Discover, a pin callout in Map, a row in Saved, and back navigation from each

## 5. Inbound routing

- [ ] 5.1 Attach `onOpenURL` once at the `WindowGroup` in `BallyhooApp` and route the URL through `EventLink`
- [ ] 5.2 On a parse failure, take no action at all — the app opens to its default state with no error surfaced
- [ ] 5.3 On a parse success, hand the id to the router rather than to any view
- [ ] 5.4 Resolve against `store.allEvents`, never `filteredEvents`, so active filters cannot hide a linked event
- [ ] 5.5 Leave the user's filters, search text, and date window untouched when routing
- [ ] 5.6 Hold a pending id when `store.state` is `.idle` or `.loading`, and resolve it when the store reaches a terminal state
- [ ] 5.7 Present the destination immediately while pending, in a loading state, so the app visibly reacts to the tap
- [ ] 5.8 On `.loaded` with no matching id, transition to event-not-found
- [ ] 5.9 On `.failed`, transition to feed-load-failed — never to event-not-found
- [ ] 5.10 Switch to the Discover tab whenever a link resolves, regardless of which tab was selected
- [ ] 5.11 Make the most recent link replace the current destination rather than pushing onto it
- [ ] 5.12 Clear the router's pending state once a destination has been presented, so a backgrounded-and-resumed app does not re-navigate

## 6. Not-found and load-failure destinations

- [ ] 6.1 Create `ballyhoo/Features/Detail/EventNotFoundView.swift`
- [ ] 6.2 Write copy that states the event is no longer listed and that events drop out of the feed once they have passed, without asserting which of those happened
- [ ] 6.3 Derive the source name from the id's `{source_id}` prefix and name it when it matches a known `Source`; omit it silently when it does not
- [ ] 6.4 Offer a route back to browsing the current feed
- [ ] 6.5 Build the distinct feed-load-failed state with a retry that reloads the feed and re-resolves the still-pending id
- [ ] 6.6 Confirm by inspection that no code path can present not-found while `store.state` is `.failed`

## 7. Share payload

- [ ] 7.1 Create `ballyhoo/Features/Detail/EventSharePayload.swift` composing the payload as a `String`
- [ ] 7.2 Compose in order: title, then date and time with venue, then the attribution line, then the deep link on its own final line
- [ ] 7.3 Format the date and time in the app's existing style, honoring `isAllDay` so an all-day event does not advertise a meaningless start time
- [ ] 7.4 Omit the venue segment cleanly when the event has no venue, leaving no dangling separator
- [ ] 7.5 Always emit the attribution line naming `event.source.name`, and append the upstream `listing_url` to it when one exists
- [ ] 7.6 Omit only the URL, never the source name, when `listing_url` is nil
- [ ] 7.7 Never include `event.summary` in the payload
- [ ] 7.8 Add tests covering: an event with venue and listing URL, one with neither, an all-day event, and one whose source has no known URL

## 8. Share affordances

- [ ] 8.1 Replace the toolbar's `ShareLink(item: url)` in `EventDetailView` with a `ShareLink` over the composed payload string
- [ ] 8.2 Remove the `if let url = event.url` guard around the share control so every event is shareable
- [ ] 8.3 Supply a `SharePreview` carrying the event title and its thumbnail, so the share sheet looks correct even where the recipient's client renders no card
- [ ] 8.4 Add the secondary share action for the upstream listing, sharing `event.url` as a `URL` so the upstream site's own preview card is used
- [ ] 8.5 Label the secondary action with the source name, e.g. "Share Ticketmaster listing", rather than a generic label
- [ ] 8.6 Hide the secondary action when `event.url` is nil
- [ ] 8.7 Do not add a share action for `ticket_url`
- [ ] 8.8 Keep the primary share a single tap; put the secondary action behind the overflow so the common case is not slowed down

## 9. Previews

- [ ] 9.1 Add a `#Preview` for `EventNotFoundView` with a recognized source prefix
- [ ] 9.2 Add a `#Preview` for `EventNotFoundView` with an unrecognized source prefix
- [ ] 9.3 Add a `#Preview` for the feed-load-failed destination
- [ ] 9.4 Add a `#Preview` for the pending/loading destination
- [ ] 9.5 Update any `#Preview` that injects `EventStore` to also inject a `DeepLinkRouter`, or add a shared preview helper that injects both
- [ ] 9.6 Verify every new preview renders in both Light and Dark appearance

## 10. Verification

- [ ] 10.1 Warm foreground: with the app running and the feed loaded, run `xcrun simctl openurl booted "ballyhoo://event?id=<id>"` and confirm the detail appears
- [ ] 10.2 Cold launch: terminate the app, run the same command, and confirm the destination presents in a loading state and then resolves without further input
- [ ] 10.3 Cross-tab: select the Map tab, open a link, and confirm the app switches to Discover and presents the detail there
- [ ] 10.4 Back navigation: dismiss a deep-linked detail and confirm the user lands on the Discover feed
- [ ] 10.5 Successive links: open two different links back to back and confirm the second replaces the first with no stacking
- [ ] 10.6 Filtered state: apply a category filter that excludes the target event, open its link, and confirm it still resolves and the filters are unchanged
- [ ] 10.7 Not found: open a link for a fabricated id such as `calagator:0` and confirm the honest not-found state with Calagator named
- [ ] 10.8 Unknown source: open a link for `nosuchsource:1` and confirm not-found renders without a source name
- [ ] 10.9 Load failure: disable networking, cold-launch from a link, and confirm the load-failure state with retry appears rather than not-found; restore networking, tap retry, and confirm the event resolves
- [ ] 10.10 Malformed links: open `ballyhoo://event`, `ballyhoo://source?id=x`, and an unrelated HTTPS URL on the domain, and confirm the app opens normally with nothing presented
- [ ] 10.11 Share payload on device: share an event to Messages, Mail, and the clipboard, and confirm attribution and every field arrive intact in all three
- [ ] 10.12 Share an event with no `listing_url` and confirm the primary action is present and the secondary is absent
- [ ] 10.13 Share an all-day event and confirm the payload reads sensibly
- [ ] 10.14 Copy a shared HTTPS link into Safari on a device without the app and confirm the landing page renders; repeat with the app installed and confirm the `ballyhoo://` handoff fires
- [ ] 10.15 Answer the open question: check whether iMessage renders a link preview for a URL on the last line of a multi-line text share, and record the result in the design's Open Questions
- [ ] 10.16 Build clean: `xcodebuild -project ballyhoo.xcodeproj -scheme ballyhoo -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build`

## 11. Documentation

- [ ] 11.1 Add a doc comment on `EventLink` recording that the HTTPS form is deliberately shared before Universal Links exist, so links minted now upgrade in place
- [ ] 11.2 Add a doc comment on `DeepLinkRouter` explaining why feed-load-failed and event-not-found are separate states
- [ ] 11.3 Note in `pipeline/README.md` that event id stability now underwrites shared links as well as saved bookmarks, so changing an id-derivation rule breaks links already sitting in other people's messages
- [ ] 11.4 Document the landing page on the `gh-pages` README: hand-maintained, not generated, and why no per-event pages exist

## 12. Universal Links — gated, do not start until the prerequisite is met

- [ ] 12.1 Prerequisite: move the published site to a host that can set a per-file `Content-Type`. GitHub Pages cannot, and serves an extensionless file as `application/octet-stream`, which Apple silently rejects. In practice this means a custom domain fronted by Cloudflare Pages, Netlify, or a Worker
- [ ] 12.2 Confirm the prerequisite empirically before doing anything else: `curl -sSI https://<domain>/.well-known/apple-app-site-association` must show HTTP 200, `Content-Type: application/json`, and no `Location` header
- [ ] 12.3 Author the association file with `appIDs` set to `<TEAMID>.com.ryangurnick.ballyhoo` and `components` scoped to the deep-link path and its `id` query parameter, not to the whole domain
- [ ] 12.4 **User:** add the Associated Domains capability and the `applinks:<domain>` entitlement to the app target, and regenerate the provisioning profile
- [ ] 12.5 **User:** during development, use `?mode=developer` on the entitlement to bypass Apple's CDN, and remove it before submitting
- [ ] 12.6 Verify with Apple's App Search API validation tool and by tapping a link on a physical device
- [ ] 12.7 Confirm links shared before this step now open the app, since their URLs were already the canonical HTTPS form and no app-side change is needed
- [ ] 12.8 Confirm the custom scheme still works, since it remains the only mechanism available on simulator builds carrying a `devplaceholder.*` bundle id
