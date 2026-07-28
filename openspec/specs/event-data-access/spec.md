# Event data access

## Purpose

Defines how the Ballyhoo app reads events from its data layer. All views consume events through a single normalized model and a repository protocol that hides whether the data comes from in-memory fixtures or the published static feed. This capability owns the schema contract between the app and the future build-time aggregation pipeline.

## Requirements

### Requirement: Normalized event schema

The app SHALL represent every event with a single normalized `Event` type regardless of which upstream source it originated from. The type SHALL carry a stable identifier, a title, an optional summary, a start time, an optional end time, an optional venue, zero or more categories, price information, an optional image URL, optional listing and ticket URLs, an optional organizer, and a required source.

#### Scenario: Events from different sources share one type

- **WHEN** the feed contains events that originated from Calagator, Ticketmaster, and a civic calendar
- **THEN** all of them decode into the same `Event` type with no source-specific fields

#### Scenario: Identifier is stable across pipeline runs

- **WHEN** the pipeline regenerates the feed and an event is unchanged upstream
- **THEN** that event's `id` is byte-identical to the previous run, so a saved bookmark still resolves

### Requirement: Source attribution is mandatory

Every `Event` SHALL carry a non-optional `Source` identifying where it came from.

#### Scenario: Attribution survives into the UI

- **WHEN** an event sourced from Ticketmaster is displayed in any surface
- **THEN** the originating source name is available for display, satisfying Ticketmaster's attribution terms and Calagator's license

### Requirement: Repository abstraction

All event reads SHALL go through an `EventRepository` protocol. The app SHALL provide a mock implementation backed by in-memory fixtures and a remote implementation that reads the published static feed.

#### Scenario: Swapping the data source

- **WHEN** the build-time pipeline begins publishing a real feed
- **THEN** switching the app from fixtures to live data requires changing only which `EventRepository` the root view constructs, with no change to any view

#### Scenario: No direct upstream access

- **WHEN** any view or view model needs event data
- **THEN** it obtains it from an `EventRepository`, and no code path contacts Calagator, Ticketmaster, or any other upstream source directly

### Requirement: Feed envelope and decoding

The static feed SHALL be decoded from a top-level envelope carrying a generation timestamp and the event array. Decoding SHALL accept ISO-8601 timestamps both with and without fractional seconds.

#### Scenario: Timestamps with fractional seconds

- **WHEN** the feed contains a start time of `2026-08-01T19:30:00.000-07:00`
- **THEN** it decodes successfully

#### Scenario: Timestamps without fractional seconds

- **WHEN** the feed contains a start time of `2026-08-01T19:30:00-07:00`
- **THEN** it decodes successfully

#### Scenario: Malformed timestamp is reported

- **WHEN** the feed contains an unparseable date string
- **THEN** decoding throws a `DecodingError` naming the offending value rather than silently substituting a default date

### Requirement: Loading states are explicit

The repository SHALL expose loading, loaded, and failed states so the UI can distinguish "no events yet" from "no events match your filters".

#### Scenario: Empty feed versus over-filtered feed

- **WHEN** the feed loads successfully but the active filters exclude every event
- **THEN** the UI can present a "no matches, try widening your filters" state rather than a generic empty state
