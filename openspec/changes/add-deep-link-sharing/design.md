## Context

`EventDetailView` has one share affordance: `ShareLink(item: url)` in the toolbar, conditional on `event.url` being non-nil, where `event.url` decodes from the feed's `listing_url`. It shares somebody else's page and says nothing about sociallist.

Replacing that with a link the app owns runs immediately into two facts about how this project is built, and both of them are load-bearing.

The first is hosting. There is no first-party backend by design. The pipeline publishes `events.json` to GitHub Pages at `https://ryangurn.github.io/sociallist/` — a **project page served under a path**, from the `gh-pages` branch of `ryangurn/sociallist`. The domain root is a different thing entirely: `https://ryangurn.github.io/` is served from a user-page repository named `ryangurn/ryangurn.github.io`, which today does not exist. Both the root and the project page's index currently return 404; only the published JSON files resolve.

The second is time. The feed is a rolling window — 30 to 365 days depending on the source, roughly 3,650 events, 3.0 MB. Events enter it and events leave it. A link, once shared, is a durable artifact sitting in someone's message history. The two have completely different lifetimes, and the design has to decide what happens at the point where they disagree rather than discovering it in the field.

Everything below follows from those two facts.

## Goals / Non-Goals

**Goals:**

- Mint one canonical link format now that will not have to change later, so no link shared today breaks when the hosting story improves.
- Make a shared event legible to a recipient who does not have the app, has never heard of the app, and is reading it in a text message.
- Keep attribution attached to shared data, because for Calagator and Ticketmaster that is a licence condition and not a courtesy.
- Route an inbound link deterministically regardless of whether the app was cold-launched by it, foregrounded by it, or already sitting on some other tab.
- Never drop a link because the feed happened not to be loaded yet.
- Be honest, and specific, about which of Universal Links, custom schemes, and both is actually available — and about what it would cost to change the answer.
- Distinguish "we could not load the feed" from "this event is gone." They look the same from the router's seat and feel completely different to a user.

**Non-Goals:**

- Universal Links in this change. Blocked, with a named prerequisite. See the first decision.
- A web presence. The landing page is a fallback, not a product surface, and is deliberately one file.
- Per-event Open Graph metadata, which would require server-side rendering or per-event static generation.
- Reading the `archive` branch to resurrect an aged-out event. Rejected below.
- Deep links to anything but a single event.
- Any form of share tracking, share token, or attribution parameter.

## Decisions

**Universal Links are not available on GitHub Pages, and the blocker is the Content-Type, not the path.**

It is tempting to conclude that the project-page path is what kills this — the site lives at `/sociallist/` and Apple wants the association file at the domain root. That is a real obstacle but it is the *solvable* one, and getting it right matters because it changes what the fix would have to be.

Apple requires the file at exactly `https://<domain>/.well-known/apple-app-site-association`, served over HTTPS, no redirects, `Content-Type: application/json`, under 128 KB, and since iOS 14 fetched by Apple's own CDN rather than by the device. Crucially, only the *file* has to be at the root. The `components` array inside it can scope matching to any paths on that domain, including `/sociallist/e/*`. So a file at `https://ryangurn.github.io/.well-known/apple-app-site-association` could legitimately authorize links under the project page. The root is served by `ryangurn/ryangurn.github.io`, which does not exist yet, but creating it is an afternoon's work. Awkward — the association file for this app would live in a different repository from the app and the feed, and nothing would keep them in sync — but not fatal.

The Content-Type is fatal. GitHub Pages assigns `Content-Type` from the file extension and offers no per-file header configuration; there is no `_headers` support, no `netlify.toml` equivalent, nothing. The association file must have **no extension**, so Pages falls through to `application/octet-stream`. Apple's `swcd` daemon discards it and the failure is silent — links simply open in Safari with no diagnostic anywhere on the device.

This was measured rather than assumed. On this project's own `gh-pages` branch, `https://ryangurn.github.io/sociallist/.nojekyll` returns `200` with `application/octet-stream` while `README.md` in the same directory returns `text/markdown; charset=utf-8`, which isolates the behaviour to the missing extension. Two live third-party sites that are serving a real association file from GitHub Pages today — `ydbendasan.github.io` and `commitchallenge.github.io` — both return `200` with `application/octet-stream`. Their Universal Links do not work either; they just have no way to find out.

So the answer to "Universal Links, custom scheme, or both" is **both, in sequence, and only the custom scheme ships now**. The unblock condition is specific and worth writing down so it is not rediscovered: a host that can set a per-file `Content-Type`. In practice that means a custom domain fronted by Cloudflare Pages, Netlify, or a Cloudflare Worker, at which point the AASA also stops living in a stranger repository. Estimated cost: a domain registration and a redeploy target. That is a decision about whether this project wants to own a domain, which is a bigger question than deep linking and should not be smuggled in underneath it.

Alternative considered: ship the `applinks:ryangurn.github.io` entitlement anyway, on the theory that Apple's enforcement of the Content-Type is inconsistently reported and it might just work. Rejected. The entitlement requires a provisioning-profile change, the failure mode is silent, and "it worked on my device in 2021" is not a basis for a user-facing feature. Worse, if it worked intermittently we would ship links whose behaviour varied by device and by CDN cache state, which is harder to support than links that consistently open in Safari.

Alternative considered: skip HTTPS links entirely and share `sociallist://` URLs. Rejected, decisively — see the next decision.

**The shared link is an HTTPS URL from day one, even though it is not yet a Universal Link.**

`sociallist://event?id=calagator:1250482638` in an iMessage is inert text. Messages will not linkify an unrecognized scheme, Slack and Discord render it as literal characters, and a recipient without the app sees a string that looks like a mistake. Since essentially no recipient has the app, a share payload built around a custom scheme optimizes for the case that almost never happens.

`https://ryangurn.github.io/sociallist/e/?id=calagator%3A1250482638` is a normal web URL. Every messaging client linkifies it, it is tappable, and it resolves to a page. Today that page is a landing page rather than an app launch; the day the hosting prerequisite is met, the identical URL becomes a Universal Link and links minted years earlier start opening the app. Nothing about the grammar, the router, or the payload changes at that point — only an entitlement and a file on a domain.

That upgrade-in-place property is the entire reason to pick the HTTPS form now rather than switching to it later, and it is worth paying a landing page for.

The custom scheme still gets registered, for three jobs that the HTTPS URL cannot do: it works on day one with no hosting at all; the landing page can attempt it to hand off to an installed app; and it is the only deep-link mechanism that functions in the simulator, where builds carry a `devplaceholder.*` bundle id that could never satisfy an association file naming `com.ryangurnick.sociallist`. That last one is not a footnote — without the custom scheme, deep-link routing would be untestable outside a device build.

**The event id goes in a query parameter, not a path segment.**

Event ids are shaped `{source_id}:{upstream_id}` — `calagator:1250482638`, `ticketmaster:vv1AaBbCc`, `obt:830`. A colon is legal inside a path segment under RFC 3986, so `/sociallist/e/calagator:1250482638` is a valid URL, and this is genuinely a close call.

Three things decide it for the query.

The colon is a hazard in text. Link detectors — `NSDataDetector`, and the autolinkers in Messages, Slack, and Discord — vary in where they end a URL, and a colon mid-path is exactly the kind of character that gets treated as a sentence boundary. Percent-encoding it to `%3A` in a path avoids the truncation but introduces a second problem: intermediaries normalize `%3A` back to `:` in paths inconsistently, so the app would have to accept both spellings. In a query string, `%3A` is unambiguous and universally left alone.

GitHub Pages is a static file server with no rewrite rules. A path-based format needs either a real directory per event — 3,650 directories regenerated on every publish, on a branch whose publish cost the pipeline already tracks carefully — or a custom 404 page abused as a router, which returns HTTP 404 to every deep link and makes the fallback page indistinguishable from a genuine miss. A query parameter against a single `e/index.html` needs neither. The static host we already have serves it correctly with one file.

And it costs nothing later. Apple's `components` matching supports a `?` dictionary alongside path patterns, so `{"/": "/sociallist/e/*", "?": {"id": "?*"}}` expresses this format exactly whenever the association file becomes possible.

Alternative considered: drop the colon and use a slug like `calagator-1250482638`. Rejected because the colon form is the id, and translating at the link boundary means two representations that can drift, plus an ambiguity the moment a `source_id` or an `upstream_id` contains a hyphen — `obt` and `oregon_metro` already coexist and nothing forbids it.

**Both URL forms share one grammar and one parser.**

`EventLink` is a small value type that formats an event id into either form and parses either form back. Everything downstream sees a validated id and never a `URL`. The parser is strict: it accepts only the two known hosts-and-paths, requires a non-empty `id`, percent-decodes it, and rejects anything else rather than guessing. Unknown extra query parameters are ignored, so a future `?id=...&ref=x` does not break a shipped client.

The scheme and host are constants in one place. A staging variant, if `add-staging-feed` ever wants one, is a change to that constant and to nothing else.

**The landing page is one hand-written static file, not a generated artifact.**

`gh-pages:/e/index.html` handles the case of an HTTPS deep link opened by someone without the app. It reads `?id=` client-side, attempts the `sociallist://` scheme to hand off to an installed app, and otherwise shows what the app is, a link to it, and a way to reach the underlying listing.

It is committed by hand, once, and the pipeline never touches it. That distinction matters: the `gh-pages` branch is cloned on every workflow run, and every source workflow plus the merge workflow publishes to it. Adding thousands of per-event files regenerated hourly would slow every run forever and, via the archive, cost storage indefinitely. One static file costs nothing.

Deciding *how much* the page shows is the interesting part. To render the event's title it would have to fetch `events.json` — 3.0 MB uncompressed, roughly 473 KB gzipped — to display one row. On a phone, on cellular, to read a title. Reasonable people differ here; the recommendation is that the first version does not fetch the feed, because the share payload already carries the title, date, and venue as text, so the recipient has read them before ever tapping. The page's job is only to answer "what is this link and what do I do with it." Fetching the feed to duplicate what the message already said is a lot of bytes for very little. Flagged as an open question, because if the page turns out to be a real acquisition surface the calculus changes.

**No resolution from the `archive` branch.**

Every published snapshot is committed to the `archive` branch and is publicly readable over `raw.githubusercontent.com`, so resurrecting an aged-out event from history looks available. Three reasons not to.

The archive is not indexed by event. Snapshots are whole-feed gzipped blobs, so answering "does this snapshot contain `calagator:1250482638`" means downloading and decompressing an entire feed — around 473 KB — and you do not know which snapshot to try. The daily tier retains one per day indefinitely, so a backward search over an event that aged out three weeks ago is twenty-one downloads with no early termination on a genuine miss. Several megabytes to fail.

The archive is explicitly a debugging and audit artifact. `add-events-aggregation-pipeline` says so, and its retention policy is written on that basis: two tiers, gzip chosen deliberately at the cost of browsability, and — the important part — a **deferred history-compaction workflow that rewrites the branch with an orphan commit and force-pushes**. That compaction currently has no date on it — the pipeline change withdrew its runway estimate as unmeasured — but an open timeline is not reassurance here, since it is planned work that will eventually run, and the deferral could end on any week. If shipped clients read that branch, a maintenance operation the pipeline design already plans to perform silently breaks deep links in the field, with no App Store release able to fix the ones already sent. Turning an internal artifact into a client API contract is a much larger commitment than the feature justifies, and it would be made implicitly.

And it mostly would not help. The dominant reason an event is missing is that it already happened. Recovering its record from the archive lets the app say "this happened on June 6" instead of "this is no longer listed" — a marginal improvement in wording, bought with megabytes of traffic and a permanent coupling.

Alternative considered: have the pipeline publish a small `event-index.json` mapping id to a minimal record with a longer retention than the feed. Rejected for this change as scope that belongs to the pipeline, not the client, and as a real ongoing cost — the index would need its own retention policy, its own staleness semantics, and its own place in the merge workflow. Worth revisiting if aged-out links turn out to be common, which is measurable once links exist.

**The answer to aged-out events is prevention in the payload, not recovery in the app.**

Since the link cannot be made to resolve forever, the *message* is made to survive the link. The share payload is a self-contained text block:

```
Portland Old Time Music Gathering
Fri, Jan 16 · 7:30 PM · Alberta Rose Theatre
via Calagator — https://calagator.org/events/1250482638
https://ryangurn.github.io/sociallist/e/?id=calagator%3A1250482638
```

A recipient who opens that in six months gets the event's name, when it was, where it was, who listed it, and a link to the original — all of it without the deep link resolving to anything. The deep link is the best case, not the only case. This is what makes the aged-out problem tolerable rather than merely acknowledged, and it is why the payload is text rather than a bare URL.

The app's not-found state can then be short and honest: this event is no longer listed, events drop out once they have passed, here is the feed. It deliberately does **not** claim the event has passed, because the app cannot distinguish "it happened" from "its source broke and its events fell out" from "the id changed" — and a confident wrong explanation is worse than a vague right one. The id's prefix does identify the source, so naming it ("It came from Calagator") is safe and mildly useful.

**Share a `String`, not a `URL`, and accept the lost preview card.**

`ShareLink(item: someURL, message:)` delivers `message` inconsistently — Mail uses it as a body, several destinations drop it. If attribution rode on `message`, attribution would be destination-dependent, and CC BY compliance would depend on which app the user tapped in the share sheet. That is not an acceptable way to satisfy a licence. Sharing a `String` that already contains everything makes the payload atomic: whatever the destination does with it, the text arrives intact.

The cost is real. A URL-typed share gets a rich link preview in Messages and the "Copy Link" affordance in the sheet; a text share containing a URL usually does not render a card. Mitigations: put the deep link on its own final line, which is where clients are most likely to still preview it, and supply a local `SharePreview` with the event title and thumbnail so the *share sheet itself* looks right even though the recipient's card may not. Whether Messages previews a trailing URL inside a longer text block is destination behaviour that changes between iOS releases, so it is worth checking on device rather than reasoning about — logged as an open question.

**The payload carries facts, not descriptions.**

Title, start date and time, venue name, `via <Source>`, upstream URL, deep link. Not `summary`. Two reasons. Descriptions are long and turn a scannable message into a wall. And redistribution of upstream description text is where licence terms actually bite — Calagator's CC BY is satisfied by the attribution line, but Ticketmaster's terms are considerably less generous about republishing their content, and a share payload posted into a public channel is republication. Facts about when and where a public event occurs are not anyone's property; a marketing blurb is. Omitting the description costs nothing and removes the question.

**Sharing the upstream listing stays as a separate, secondary action.**

The primary action shares the sociallist payload. A secondary **Share <Source> listing** shares the bare upstream URL as a `URL`, which is a genuinely different artifact: it renders the upstream site's own preview card, and for a Ticketmaster event that card — with the artist image, the venue, and a buy button one tap away — is very often exactly what the recipient wants. Collapsing the two would mean either losing that card or losing attribution, and there is no reason to choose.

It is labelled by destination rather than generically, so the user knows where the link goes before they send it. When `event.url` is nil the action is absent; the primary share still works and simply omits the upstream line, which is strictly better than today's behaviour of having no share button at all.

The `ticket_url`, where it differs from `listing_url`, is not a third share action. Two share actions is already close to the limit of what a toolbar overflow should offer, and a ticket link is reachable from the listing.

**Routing goes through an `@Observable DeepLinkRouter` in the environment, and always lands on Discover.**

`onOpenURL` is attached once at the `WindowGroup`, parses through `EventLink`, and hands the id to the router. The router — not any view — owns the pending id, the resolved destination, and the not-found state.

This requires lifting state that is currently view-local. `TabView` in `SociallistApp` has no selection binding, and each of Discover, Map, and Saved owns a private `selectedEvent` driving its own `navigationDestination(item:)`. An inbound link has nowhere to write. So tab selection becomes a binding, and Discover's selection becomes router-driven.

Every link routes to **Discover**, even if the user is on Map or Saved. One predictable destination is worth more than context preservation here: back from a deep-linked detail should land somewhere that makes sense, and an event detail pushed onto the Saved stack pops back to a list that may not contain it. Discover always contains browsing.

Alternative considered: present the detail as a sheet over whatever tab is showing, preserving context entirely. Rejected because the app has no sheet-based detail anywhere else and introducing one only for deep links means the same screen behaves differently depending on how it was reached.

**A link that arrives before the feed is loaded is held, not dropped.**

Cold launch is the common case and the hard one: `onOpenURL` fires while `store.state` is `.idle` or `.loading`, and `allEvents` is empty. Resolving immediately means every cold-launched link resolves to "not found," which is the single most likely way to get this wrong.

So the router stores the pending id and resolves when the store reaches a terminal state. While pending, the destination is presented immediately in a loading state rather than left invisible — the user tapped a link and should see the app react. On `.loaded`, the pending id resolves to an event or to not-found. On `.failed`, the destination shows a **load failure with retry**, not not-found. Those two states must not be conflated: one says the network is down, the other says the event is gone, and telling a user their friend's link is dead when the real problem is airplane mode is a bug worth pinning in the spec.

Warm foreground is the easy case and falls out of the same code path, because a loaded store resolves the pending id synchronously on the next observation cycle.

Last link wins. Two links in quick succession replace rather than stack, and a link arriving while a detail is already showing replaces the detail. Nobody wants a deep-link stack.

**The URL scheme is registered by the user, and the entitlement is not added at all.**

`CFBundleURLTypes` is target configuration in `project.pbxproj`, which is hand-managed here. The tasks state the exact scheme string and identifier for the user to enter, rather than pretending an agent will edit it. The Associated Domains entitlement is not added in this change — it would be inert without a valid association file, and an inert entitlement is a thing someone finds in six months and cannot explain. The tasks record what to add, and when, as a separate gated step.

## Risks / Trade-offs

- **A recipient without the app taps an HTTPS deep link and gets a plain landing page, not the event.** This is the expected path for essentially every share until Universal Links are possible, and the page cannot show the event without downloading a 3.0 MB feed. → Mitigation: the share payload already carries title, date, venue, and the upstream URL as text, so the recipient has the event before they tap. The page's job is only to explain the link. Accepting a weak landing page is the price of minting upgradeable URLs now, and it is cheaper than minting `sociallist://` links that are inert text for everyone.
- **A shared link's preview card in Messages may be missing or generic**, because the payload is text and the landing page has no per-event Open Graph tags. → Mitigation: deep link on its own final line to maximize the chance of a preview; local `SharePreview` so the sender's share sheet looks correct. Per-event OG tags need server-side rendering or per-event static generation, both rejected above. Verify the actual behaviour on device before assuming the worst.
- **Links minted now will point at a URL that 404s if the landing page is never committed.** The page lives on `gh-pages`, a branch this change does not otherwise touch and which three workflows publish to. → Mitigation: commit the landing page *before* shipping the share change, and treat it as a hard prerequisite in the task ordering rather than a follow-up. A 404 is a worse first impression than the upstream URL we share today.
- **The Universal Links prerequisite may never be met**, in which case the HTTPS format's upgrade path is theoretical and we paid for a landing page to get nothing. → Accepted. The alternative was custom-scheme-only links that are inert text in every message, which is worse *today* and not just worse later. The HTTPS format is the better artifact even if it stays a plain web link forever.
- **Claiming `applinks:ryangurn.github.io` later claims the entire user subdomain**, including any other project page under it. → Noted for whoever implements it. Not a problem now, and scoping via `components` limits the app's actual match to `/sociallist/e/*`, but the entitlement itself is domain-wide and worth understanding before adding it.
- **Lifting tab selection and Discover's navigation path into shared state touches the app's root navigation**, which every tab depends on and which currently works. A regression here is visible everywhere. → Mitigation: the change is mechanical (`@State` moves up, becomes a binding), Map and Saved keep their own local selection and are not touched, and the tab-switching and back-navigation paths are explicitly listed as verification tasks.
- **An event whose upstream source changes its id format gets a dead link even while the event is still in the feed.** Id stability is already a hard requirement for saved bookmarks, so this is not a new exposure — but shared links extend the blast radius from one user's bookmarks to other people's messages. → Mitigation: none available at the client. Worth noting in the pipeline's README that id stability now also underwrites shared links, so the bar for changing an id-derivation rule is higher than it was.
- **The not-found state will sometimes fire for an event that is merely temporarily absent** — a source broke, its events fell out, and the pipeline will restore them next run. The user is told it is no longer listed, which is true now and false in an hour. → Accepted, and the reason the copy avoids diagnosing a cause. A retry affordance on the not-found state would let a curious user re-check cheaply; deferred as an open question rather than built speculatively.
- **Two share actions where there was one adds a menu to a toolbar that had a button.** Slightly more friction for the common case. → Acceptable: the primary action stays a single tap, and the secondary is behind the overflow. It also fixes the existing bug where an event without a `listing_url` had no share affordance at all.

## Migration Plan

1. Commit `e/index.html` to `gh-pages` by hand. Confirm `https://ryangurn.github.io/sociallist/e/?id=calagator%3A1250482638` returns 200 and renders. This is a prerequisite, not a follow-up — no link should be shareable before its URL resolves.
2. Land `EventLink` with its parser and formatter, plus round-trip tests, ahead of any UI. It is pure value-type logic and is the piece everything else depends on.
3. Have the user register the `sociallist` URL scheme in the Xcode target.
4. Land `DeepLinkRouter` and the navigation lift. Verify every existing navigation path still works before adding any deep-link behaviour on top.
5. Wire `onOpenURL` and the resolution paths. Test cold launch, warm foreground, feed-not-yet-loaded, feed-failed, and not-found via `xcrun simctl openurl` against the custom scheme.
6. Replace the share affordances last, once the links they produce are known to resolve.
7. If and when the hosting prerequisite is met: add the association file at the new domain root, add the Associated Domains entitlement, and verify. No app-side code changes — `EventLink` already produces the URLs.

**Rollback:** restore the single `ShareLink(item: url)` in `EventDetailView`. Links already shared keep resolving to the landing page, which is why the landing page should outlive any rollback of the app-side change. The router, `EventLink`, and the navigation lift can stay in place harmlessly, or be reverted together; nothing persists to disk and no server state exists to unwind. The URL scheme registration is worth leaving registered.

## Open Questions

- Should the landing page fetch `events.json` to render the event properly? 473 KB gzipped to show one title, against a share payload that already contains that title. Leaning no for the first version, but if the page is ever treated as an acquisition surface rather than a fallback, the answer flips.
- Does iMessage generate a link preview for a URL on the last line of a multi-line text share? This determines whether the trailing-line placement is worth anything or whether we should reconsider the `String`-versus-`URL` trade-off. Answerable in five minutes on a device and not worth reasoning about further.
- Should the not-found state offer a retry that reloads the feed? Cheap to add and occasionally correct, but it invites the user to keep tapping at an event that is genuinely gone. Better decided after seeing how often not-found actually fires.
- Is `via Calagator — <url>` the right attribution form, or should the payload name sociallist explicitly as the sender? "Shared from sociallist" is self-promotional in a way the rest of the app is not, but without it the recipient has no idea what the second link is. Worth looking at as real text in a real conversation.
- Does this project want a custom domain? Deep linking is not a good enough reason on its own, but it is now one of several — Universal Links, per-file headers, and an association file that lives in the same repository as the app all arrive together with one. Worth deciding deliberately rather than as a side effect of this change.
