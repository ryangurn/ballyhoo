## ADDED Requirements

### Requirement: Canonical link grammar

A single event SHALL be addressable by a canonical deep link that carries the event's `id` and nothing else. The link SHALL exist in exactly two forms over one grammar: an HTTPS form, `https://ryangurn.github.io/ballyhoo/e/?id=<event-id>`, and a custom-scheme form, `ballyhoo://event?id=<event-id>`. In both forms the event id SHALL be carried in a query parameter named `id`, percent-encoded, and SHALL NOT be carried in a path segment.

#### Scenario: Formatting an event into both forms

- **WHEN** the app produces a deep link for the event `calagator:1250482638`
- **THEN** the HTTPS form is `https://ryangurn.github.io/ballyhoo/e/?id=calagator%3A1250482638` and the custom-scheme form is `ballyhoo://event?id=calagator%3A1250482638`, both carrying the same id

#### Scenario: The colon is percent-encoded

- **WHEN** a link is generated for any event id containing the `{source_id}:{upstream_id}` colon
- **THEN** the colon appears as `%3A` in the emitted URL, so link detectors and messaging clients do not truncate the URL at the colon

#### Scenario: Round-tripping through either form

- **WHEN** an event id is formatted into either URL form and then parsed back
- **THEN** the recovered id is byte-identical to the original, including for ids containing underscores such as `oregon_metro:4471`

### Requirement: Link parsing is strict and forward-compatible

Inbound URL parsing SHALL accept only the two canonical forms and SHALL reject anything else rather than inferring an event id. Unrecognized additional query parameters SHALL be ignored rather than causing rejection.

#### Scenario: A URL for an unrelated path is rejected

- **WHEN** the app is opened with `https://ryangurn.github.io/ballyhoo/events.json`
- **THEN** parsing fails, no deep-link routing occurs, and the app opens normally to its default state

#### Scenario: A link with no id is rejected

- **WHEN** the app is opened with `ballyhoo://event` or with `ballyhoo://event?id=`
- **THEN** parsing fails and the app opens normally rather than presenting a not-found state

#### Scenario: Unknown extra parameters are tolerated

- **WHEN** the app is opened with `https://ryangurn.github.io/ballyhoo/e/?id=calagator%3A1250482638&ref=newsletter`
- **THEN** the link resolves to event `calagator:1250482638` and the unrecognized `ref` parameter is ignored

#### Scenario: An unknown custom-scheme host is rejected

- **WHEN** the app is opened with `ballyhoo://source?id=calagator`
- **THEN** parsing fails, because only the `event` host is defined by this grammar

### Requirement: Universal Links are not claimed without a verified association file

The app SHALL NOT declare an Associated Domains `applinks:` entitlement for a domain that does not serve a valid `apple-app-site-association` file. The HTTPS link form SHALL nevertheless be the form produced for sharing, so that links minted before Universal Links are available become Universal Links without any change to the grammar or to previously shared links.

#### Scenario: HTTPS links are shared before Universal Links exist

- **WHEN** a user shares an event while no association file is published
- **THEN** the shared link is the HTTPS form, and it opens the landing page in a browser rather than the app

#### Scenario: Previously shared links upgrade in place

- **WHEN** a valid association file is later published and the Associated Domains entitlement is added
- **THEN** links shared before that point open directly in the app, because their URLs were already the canonical HTTPS form

#### Scenario: The custom scheme works without any hosting

- **WHEN** a `ballyhoo://event?id=...` URL is opened on a device or simulator with the app installed
- **THEN** the app launches and routes to the event, independent of any association file, domain, or network availability

### Requirement: Resolution reads the unfiltered feed

An inbound event id SHALL be resolved against the complete set of events the app has loaded, not against the user's currently filtered view. Active search text, category selections, the free-only toggle, and the date window SHALL NOT affect whether a deep link resolves.

#### Scenario: A link resolves while filters exclude the event

- **WHEN** a deep link arrives for a music event while the user has the category filter set to Food & Drink
- **THEN** the event resolves and its detail is presented, and the user's filters are left unchanged

#### Scenario: A link resolves for an event outside the active date window

- **WHEN** a deep link arrives for an event three weeks out while the date window is set to Today
- **THEN** the event resolves and its detail is presented

### Requirement: A link received before the feed is ready is held, not dropped

When a deep link arrives while the event feed has not reached a terminal load state, the app SHALL retain the pending event id and resolve it once the feed reaches a terminal state. The app SHALL present the destination immediately in a loading state rather than showing nothing.

#### Scenario: Cold launch from a deep link

- **WHEN** the app is launched by a deep link and the feed has not yet loaded
- **THEN** the destination is presented in a loading state, and once the feed loads the event's detail appears without any further user action

#### Scenario: Warm foreground with a loaded feed

- **WHEN** a deep link arrives while the app is already running with a loaded feed
- **THEN** the event resolves immediately and its detail is presented

#### Scenario: The pending link survives a slow feed

- **WHEN** a deep link arrives during a feed load that takes several seconds
- **THEN** the pending id is still resolved when the load completes, rather than being discarded

### Requirement: Feed failure is distinguished from a missing event

A deep link that cannot be resolved because the feed failed to load SHALL present a load-failure state offering a retry. It SHALL NOT present the event-not-found state.

#### Scenario: Deep link opened with no network

- **WHEN** the app is cold-launched by a deep link and the feed request fails
- **THEN** the destination shows that events could not be loaded and offers a retry, rather than reporting that the event no longer exists

#### Scenario: Retry after a failed load resolves the link

- **WHEN** the user taps retry on that state and the feed then loads successfully
- **THEN** the originally pending event id is resolved and its detail is presented

### Requirement: An event no longer in the feed produces an honest not-found state

When the feed has loaded successfully and contains no event with the requested id, the app SHALL present a not-found state that reports the event is no longer listed and that events drop out of the feed once they have passed. The state SHALL NOT assert a specific cause it cannot verify. It SHALL name the originating source, derived from the id's `{source_id}` prefix, and SHALL offer a route back to browsing.

#### Scenario: A link to an event that has aged out

- **WHEN** a deep link arrives for `calagator:1250482638` and the loaded feed contains no such event
- **THEN** the app reports that the event is no longer listed, names Calagator as its source, and offers a way back to the feed

#### Scenario: The state does not diagnose a cause

- **WHEN** an event is absent because its source workflow broke rather than because the event passed
- **THEN** the presented message is the same, because the app cannot distinguish the two and an incorrect explanation is worse than none

#### Scenario: An unrecognized source prefix degrades gracefully

- **WHEN** a deep link carries an id whose prefix matches no source the app knows about
- **THEN** the not-found state is still presented, omitting the source name rather than failing

### Requirement: Deep-link routing is deterministic

An inbound deep link SHALL route to a single, predictable destination regardless of which tab is selected when it arrives. When multiple links arrive in succession, the most recent SHALL replace the previous destination rather than accumulating navigation history.

#### Scenario: A link arrives while another tab is selected

- **WHEN** a deep link arrives while the user is on the Map or Saved tab
- **THEN** the app switches to the Discover tab and presents the event's detail there

#### Scenario: A second link replaces the first

- **WHEN** a second deep link arrives while a deep-linked event detail is already presented
- **THEN** the presented detail is replaced by the new event rather than pushed on top of it

#### Scenario: Back from a deep-linked detail lands on the feed

- **WHEN** the user dismisses a deep-linked event detail
- **THEN** they land on the Discover feed rather than on an unrelated or empty screen

### Requirement: HTTPS deep links resolve to a landing page when the app is absent

The HTTPS deep-link path SHALL be served by a static landing page so that a link opened by someone without the app reaches an explanatory page rather than an HTTP 404. The page SHALL be a single static file that is not regenerated by the publishing pipeline.

#### Scenario: Link opened without the app installed

- **WHEN** an HTTPS deep link is opened in a browser on a device that does not have the app
- **THEN** the page loads successfully and explains what the link is and where to get the app

#### Scenario: Link opened on a device that has the app

- **WHEN** the landing page loads on a device with the app installed
- **THEN** it attempts the equivalent `ballyhoo://` URL so the app can take over

#### Scenario: The page is not a pipeline artifact

- **WHEN** the publishing pipeline runs
- **THEN** it neither generates nor rewrites the landing page, and no per-event pages are published

### Requirement: Deep links carry no user data

A deep link SHALL contain only a publicly published event identifier. It SHALL NOT contain a device identifier, a user identifier, a share token, a timestamp, or any campaign or referral parameter, and no record of a share SHALL be transmitted anywhere.

#### Scenario: Two users share the same event

- **WHEN** two different users share the same event from two different devices
- **THEN** the two links are byte-identical, because neither carries anything that distinguishes the sender

#### Scenario: Sharing makes no network request

- **WHEN** a user shares an event
- **THEN** the app issues no request as a result of the share
