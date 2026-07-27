## ADDED Requirements

### Requirement: Stable published URLs

The merged feed SHALL be published at a single, stable HTTPS URL that the client hard-codes as its `.production` remote source. Per-source files SHALL be published at stable HTTPS URLs derived deterministically from their source identifiers.

#### Scenario: Merged-feed URL does not change

- **WHEN** any pipeline workflow (source or merge) runs on any schedule
- **THEN** the merged feed is always overwritten at the same URL path (`/events.json`), never a versioned or timestamped path

#### Scenario: Per-source URL is derived from source id

- **WHEN** a source with identifier `<source_id>` publishes its file
- **THEN** the file is served at `/sources/<source_id>.json`, and this URL is stable across every run of that source's workflow

#### Scenario: Public HTTPS access

- **WHEN** any client requests the merged feed URL or a per-source URL
- **THEN** the response is served over HTTPS with no authentication required

### Requirement: JSON envelope shape

Both the merged feed and every per-source file SHALL be JSON objects with a top-level envelope carrying a generation timestamp and the event array, matching the shape expected by the client's `EventFeed` type.

#### Scenario: Merged-feed envelope

- **WHEN** the merged feed is fetched
- **THEN** the response body is a JSON object with keys `generated_at` (ISO-8601 timestamp of the merge run) and `events` (array), matching the client's decoder

#### Scenario: Per-source file envelope

- **WHEN** a per-source file is fetched
- **THEN** the response body is a JSON object with keys `generated_at` (ISO-8601 timestamp of that source's workflow run), `source_id` (matching the URL segment), `status` (one of `ok`, `stale`, or `error`), and `events` (array)

#### Scenario: Empty feed is still valid

- **WHEN** every upstream source returned zero events for a merge run (edge case, not a failure)
- **THEN** the merged feed is still valid JSON with `generated_at` set and `events` as an empty array — but the pipeline SHALL prefer to preserve the last-known-good feed (see last-known-good preservation)

### Requirement: Per-source health index

The pipeline SHALL publish a per-source health metadata file at a stable URL, listing every configured source's last-run status.

#### Scenario: Index is present alongside per-source files

- **WHEN** any client or third party fetches `/sources/index.json`
- **THEN** the response is a JSON object listing each configured source with its `source_id`, `last_run_at`, `event_count`, `status`, and the URL of its per-source file

#### Scenario: Index is updated whenever a source publishes

- **WHEN** a source workflow publishes its per-source file
- **THEN** the source's entry in `sources/index.json` is updated to reflect the new `last_run_at`, `event_count`, and `status`

### Requirement: Cache-friendly delivery

Every published artifact SHALL be delivered with response headers that let clients revalidate cheaply.

#### Scenario: ETag support

- **WHEN** a client resends a request with an `If-None-Match` header for a previously seen ETag
- **THEN** the server responds `304 Not Modified` when the artifact has not changed since that ETag was issued

#### Scenario: Last-Modified support

- **WHEN** a client resends a request with an `If-Modified-Since` header
- **THEN** the server responds `304 Not Modified` when the artifact has not changed since that timestamp

#### Scenario: Reasonable max-age

- **WHEN** any artifact is delivered
- **THEN** the `Cache-Control` header allows short-term caching (in the low minutes) so repeated fetches don't re-download the same bytes, without exceeding the pipeline's refresh cadence

### Requirement: Freshness signals

Every published artifact SHALL carry a UTC timestamp identifying the run that produced it, so clients can display freshness to users and health tooling can detect staleness.

#### Scenario: Merged-feed freshness

- **WHEN** the client displays the Sources tab
- **THEN** the `generated_at` timestamp on the merged feed is within a few seconds of the wall-clock time when the merge run completed

#### Scenario: Per-source freshness

- **WHEN** a per-source file is fetched
- **THEN** its `generated_at` timestamp reflects the source workflow run that produced it, not the merge run

#### Scenario: Detecting a stale source in the index

- **WHEN** a source has not published for a threshold period (e.g. its workflow failed for several runs in a row)
- **THEN** `sources/index.json` reports that source's `status` as `stale` and includes the age of its last successful run

### Requirement: Last-known-good preservation

The publish step of both source workflows and the merge workflow SHALL only overwrite the live artifact when the current run produced a non-degenerate result.

#### Scenario: Source workflow with zero events

- **WHEN** a source workflow completes but returned zero events after normalization (edge case)
- **THEN** the previous per-source file remains in place unchanged and the source's index entry is marked `stale`

#### Scenario: Merge workflow with all sources stale

- **WHEN** the merge workflow runs and every source is currently `stale` (no source has published recently)
- **THEN** the previous merged `events.json` remains in place unchanged

#### Scenario: Merge workflow suspects a bad run

- **WHEN** a merge run's total event count falls dramatically below the last-known-good feed (e.g. below a floor tied to the recent baseline)
- **THEN** the merge workflow flags the run as suspect and refuses to overwrite the live merged feed without a manual override input

### Requirement: Historical snapshots are retained

Every published artifact — the merged feed and every per-source file — SHALL be archived as an immutable, timestamped historical snapshot, so that any previously published state can be inspected after the fact.

#### Scenario: Merged feed is archived on publish

- **WHEN** the merge workflow publishes an updated `events.json`
- **THEN** a timestamped snapshot of that exact content is written to the archive, identified by its capture time

#### Scenario: Per-source files are archived on publish

- **WHEN** a source workflow publishes an updated `sources/<source_id>.json`
- **THEN** a timestamped snapshot of that exact content is written to the archive under that source's own path

#### Scenario: Snapshots are immutable

- **WHEN** a snapshot has been written to the archive
- **THEN** its content is never modified in place; a later run writes a new snapshot rather than overwriting an existing one

#### Scenario: Archives are publicly readable

- **WHEN** any person or tool requests an archived snapshot at its published URL
- **THEN** it is served over HTTPS with no authentication required

### Requirement: Unchanged content is not re-archived

The archive SHALL NOT accumulate byte-identical consecutive snapshots of the same artifact.

#### Scenario: Content is unchanged since the last snapshot

- **WHEN** a workflow publishes an artifact whose content is byte-identical to that artifact's most recent archived snapshot
- **THEN** no new snapshot is written, and the run reports that archiving was skipped as unchanged

#### Scenario: Content has changed

- **WHEN** a workflow publishes an artifact whose content differs from the most recent archived snapshot
- **THEN** a new snapshot is written

### Requirement: Tiered archive retention

The archive SHALL retain fine-grained recent history and coarse-grained long-term history, so that the browsable archive stays bounded in size without a separate cleanup process.

#### Scenario: Recent tier keeps every change

- **WHEN** an artifact changes multiple times within a single day
- **THEN** each changed snapshot is retained in the recent tier for that day

#### Scenario: Recent tier is bounded by age

- **WHEN** a recent-tier snapshot becomes older than the recent-tier retention window
- **THEN** it is removed from the archive's current state during a subsequent publish

#### Scenario: Daily tier retains one snapshot per day

- **WHEN** a day has elapsed and had at least one successful publish
- **THEN** exactly one snapshot for that artifact and day is retained in the daily tier, representing the last successful publish of that day

#### Scenario: Daily tier is retained indefinitely

- **WHEN** a daily-tier snapshot ages beyond the recent-tier window
- **THEN** it is retained; no automated process removes daily-tier snapshots

### Requirement: Archive is discoverable without cloning

The archive SHALL publish machine-readable manifests so its contents can be enumerated without listing directories or cloning a repository.

#### Scenario: Manifest lists available snapshots

- **WHEN** a tool fetches the manifest for a given artifact and month
- **THEN** it receives a listing of the snapshots available for that artifact and month, including each snapshot's capture time, content hash, and event count

#### Scenario: Manifests are bounded in size

- **WHEN** the archive has accumulated snapshots over multiple years
- **THEN** no single manifest file grows without bound; manifests are partitioned so each covers a bounded time range

### Requirement: Archiving never blocks publishing

A failure to archive SHALL NOT cause a publish to fail or a live artifact to be rolled back.

#### Scenario: Archive write fails after a successful publish

- **WHEN** the live artifact publishes successfully but the archive write fails for any reason
- **THEN** the live artifact remains published, the workflow reports the archive failure in its run report, and the failure does not mark the publish as unsuccessful

#### Scenario: Archive failure is visible

- **WHEN** archiving fails
- **THEN** the run summary clearly reports that the snapshot was not captured, so the gap is discoverable

### Requirement: Schema versioning path

Both the merged feed and per-source files SHALL be extensible so future source additions or model additions do not break existing client builds or downstream consumers in the field.

#### Scenario: Unknown fields are ignored

- **WHEN** the pipeline emits an event with a new optional field that the current client build does not know about
- **THEN** the client's `FeedDecoder` decodes the event successfully, ignoring the unknown field

#### Scenario: Breaking schema changes carry a version bump

- **WHEN** a required field is renamed or removed in a way the current client cannot decode
- **THEN** the change ships as a versioned URL path (e.g. `/events.v2.json`, `/sources/v2/<source_id>.json`), and the old URLs keep serving the old shape until deprecated
