## ADDED Requirements

### Requirement: Health index is fetched independently of the event feed

Per-source health SHALL be retrieved through its own repository abstraction, separate from `EventRepository`, so that a failure fetching health can never block, delay, or degrade the event feed.

#### Scenario: Health fetch fails while the feed succeeds

- **WHEN** the health index request fails but the event feed loaded successfully
- **THEN** the app continues to display all events normally, and only the per-source status presentation degrades

#### Scenario: Feed fetch fails while health succeeds

- **WHEN** the event feed fails to load but the health index is available
- **THEN** the Sources tab can still list the configured sources and their status, even though no event counts are available

#### Scenario: Health is not fetched on app launch

- **WHEN** the app cold-launches and the user has not opened the Sources tab
- **THEN** no health index request is made

### Requirement: Health index is fetched lazily and refreshable

The health index SHALL be fetched when the Sources tab first appears, and SHALL be re-fetchable on an explicit user refresh.

#### Scenario: First appearance triggers a fetch

- **WHEN** the user opens the Sources tab for the first time in a session
- **THEN** the app requests the health index and shows a loading indicator in the source list area while it is in flight

#### Scenario: Subsequent appearances reuse the result

- **WHEN** the user navigates away from the Sources tab and returns within the same session
- **THEN** the previously fetched health index is reused rather than re-requested

#### Scenario: Explicit refresh re-fetches

- **WHEN** the user performs a pull-to-refresh or taps the refresh control on the Sources tab
- **THEN** both the event feed and the health index are re-requested

### Requirement: Sources absent from the feed remain visible

The Sources tab SHALL render the union of sources present in the health index and sources present in the loaded feed. A source that contributed zero events to the current feed SHALL still be listed if it appears in the health index.

#### Scenario: A broken source stays listed

- **WHEN** a source's workflow has been failing long enough that none of its events remain in the merged feed, but it is still listed in the health index
- **THEN** that source appears in the Sources tab with a zero event count and its reported status, rather than disappearing from the list

#### Scenario: A source in the feed but not the index

- **WHEN** the loaded feed contains events from a source that is absent from the health index
- **THEN** that source is still listed with its feed-derived event count and an unknown status, never omitted

#### Scenario: No duplicate entries

- **WHEN** a source appears in both the health index and the loaded feed
- **THEN** it is rendered exactly once, combining its feed-derived count with its index-derived status

### Requirement: Event counts come from the loaded feed

Per-source event counts displayed to the user SHALL be derived from the events currently loaded in the app, not from the health index's reported count.

#### Scenario: Counts reflect what the user can actually browse

- **WHEN** the health index reports that a source contributed 47 events at its last run, but only 43 of those survive deduplication and date filtering in the loaded feed
- **THEN** the Sources tab displays 43 for that source

#### Scenario: Zero count for a source with no surviving events

- **WHEN** a source is present in the health index but none of its events are in the loaded feed
- **THEN** the Sources tab displays a count of zero for that source

### Requirement: Status is presented calmly and legibly

Each source's status SHALL be presented in plain language appropriate to a user-facing transparency surface, not as raw operational data.

#### Scenario: Healthy source

- **WHEN** a source's status is `ok`
- **THEN** it is presented without alarming visual treatment; freshness may be shown but no warning or error styling is applied

#### Scenario: Stale source

- **WHEN** a source's status is `stale`
- **THEN** it is presented with a cautionary treatment and a human-readable age of its last successful run (for example, "Last updated 3 days ago")

#### Scenario: Errored source

- **WHEN** a source's status is `error`
- **THEN** it is presented with a clear but non-alarming message indicating the source is currently unavailable

#### Scenario: Unknown status

- **WHEN** a source's status cannot be determined because it is absent from the health index
- **THEN** no status treatment is applied and the source is presented as it is today, with only its name, origin, and count

### Requirement: Graceful degradation when health is unavailable

When the health index cannot be fetched, the Sources tab SHALL fall back to the existing feed-derived presentation without surfacing an error state that blocks the tab.

#### Scenario: Health fetch fails

- **WHEN** the health index request fails for any reason
- **THEN** the Sources tab renders the feed-derived source list exactly as it does without this feature, plus an unobtrusive note that source status could not be loaded

#### Scenario: Health fetch failure is retryable

- **WHEN** the health index failed to load and the user performs an explicit refresh
- **THEN** the app retries the health index request

#### Scenario: Attribution survives degradation

- **WHEN** the health index is unavailable
- **THEN** every source contributing to the loaded feed is still listed with its name and origin, so attribution obligations continue to be met

### Requirement: Health index decoding tolerates unknown fields and statuses

The client SHALL decode the health index without failing on fields or status values it does not recognize, so pipeline-side additions do not break shipped clients.

#### Scenario: Unknown field in a source entry

- **WHEN** the health index contains a per-source field the current client build does not know about
- **THEN** the entry decodes successfully and the unknown field is ignored

#### Scenario: Unrecognized status value

- **WHEN** a source's status is a value the current client build does not recognize
- **THEN** that source is treated as having an unknown status and is rendered without status treatment, rather than causing the whole index to fail decoding

### Requirement: Mock health implementation for previews and mock feeds

A mock health repository SHALL be available so the Sources tab can be developed, previewed, and exercised without network access, consistent with the existing mock event repository.

#### Scenario: Preview renders with mock health

- **WHEN** the Sources tab is rendered in an Xcode preview
- **THEN** it displays representative source health covering at least one healthy, one stale, and one errored source

#### Scenario: Mock feed pairs with mock health

- **WHEN** the app is configured to use the mock event repository
- **THEN** it also uses the mock health repository, so the two never disagree about which sources exist
