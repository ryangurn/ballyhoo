## ADDED Requirements

### Requirement: Per-source workflow isolation

Every upstream source SHALL be aggregated by a dedicated GitHub Actions workflow that is independent of every other source's workflow. A failure, retry, cancellation, or code change affecting one source's workflow SHALL NOT affect any other source's workflow.

#### Scenario: One source workflow crashes

- **WHEN** the Calagator source workflow fails partway through fetching
- **THEN** the Ticketmaster source workflow continues to run on its own schedule and is not blocked, delayed, or cancelled

#### Scenario: One source workflow is being iterated on

- **WHEN** a maintainer pushes changes only to `pipeline/sources/calagator/` or `.github/workflows/source-calagator.yml`
- **THEN** only the Calagator source workflow's next run is affected; the Ticketmaster workflow continues unchanged

#### Scenario: Adding a new source is additive

- **WHEN** a new source is introduced (its own module under `pipeline/sources/<new-source>/` and a new `.github/workflows/source-<new-source>.yml`)
- **THEN** no other source's workflow file or source module changes

### Requirement: Scheduled per-source cadence

Each source workflow SHALL run on its own schedule. A single successful source workflow run produces exactly one updated `sources/<source_id>.json` artifact.

#### Scenario: Hourly source execution

- **WHEN** a source workflow's scheduled trigger fires
- **THEN** the workflow executes end-to-end (fetch, normalize, validate, publish per-source file) exactly once

#### Scenario: Manual re-run of a single source

- **WHEN** a maintainer invokes one source workflow's manual dispatch
- **THEN** only that source's workflow runs; other source workflows and the merge workflow are unaffected until their own triggers fire

#### Scenario: Dry-run at source level

- **WHEN** a source workflow is dispatched with a dry-run input set to true
- **THEN** the workflow fetches, normalizes, and validates its output, uploads it as a workflow artifact, and SHALL NOT commit anything to the `gh-pages` branch

### Requirement: Merge workflow assembles the canonical feed

A dedicated merge workflow SHALL read every per-source file from `sources/*.json`, deduplicate events across sources, validate the result, and publish the canonical `events.json`. The merge workflow SHALL be the only workflow that writes `events.json`.

#### Scenario: Merge produces one canonical feed

- **WHEN** the merge workflow completes successfully
- **THEN** exactly one file is written or updated at `events.json` on `gh-pages`, containing events from every source whose per-source file is currently present

#### Scenario: Merge is triggered by source completion

- **WHEN** any source workflow completes successfully
- **THEN** the merge workflow is triggered via `workflow_run` and runs within a few minutes, propagating the fresh source data into the client feed

#### Scenario: Merge runs on a safety schedule

- **WHEN** no source workflow has completed for a period covering the safety-cron interval
- **THEN** the safety cron fires the merge workflow anyway, so a missed `workflow_run` never leaves the feed stale indefinitely

#### Scenario: Dry-run at merge level

- **WHEN** the merge workflow is dispatched with a dry-run input set to true
- **THEN** it reads current source files, produces a candidate `events.json` as a workflow artifact, and SHALL NOT commit anything to the `gh-pages` branch

### Requirement: Merge concurrency safety

The merge workflow SHALL never overlap with itself. Concurrent triggers SHALL either be queued in order or cancelled in favor of the newer trigger, so no two merge jobs race on the same `events.json`.

#### Scenario: Two source workflows finish nearly simultaneously

- **WHEN** two source workflows complete within seconds of each other, each triggering a merge
- **THEN** only one merge job runs at a time and the final `events.json` reflects both sources

### Requirement: Merge falls back to last-known-good per source

When the merge workflow reads per-source files, it SHALL use the last-known-good content of any source whose most recent workflow run failed.

#### Scenario: One source workflow failed

- **WHEN** the merge workflow runs while the Calagator source workflow's most recent run failed and did not update `sources/calagator.json`
- **THEN** the merge uses whatever content `sources/calagator.json` last held (from the previous successful Calagator run) alongside fresh Ticketmaster data

#### Scenario: Source has never succeeded

- **WHEN** the merge workflow runs and a source's file does not exist yet (first-ever run failed)
- **THEN** the merge proceeds without that source, records it in the run report, and does not fail

### Requirement: Normalized output conforms to the client schema

Every per-source file SHALL contain events that conform to the shared `Event` schema owned by the `event-data-access` capability. The merge workflow SHALL validate the merged `events.json` against the same schema before publishing.

#### Scenario: Per-source schema validation

- **WHEN** a source workflow finishes normalization
- **THEN** the resulting per-source JSON is validated against `pipeline/schema/per-source.schema.json`, and validation failure blocks the per-source publish

#### Scenario: Merge-level schema validation

- **WHEN** the merge workflow assembles `events.json`
- **THEN** the resulting JSON is validated against `pipeline/schema/events.schema.json`, and validation failure blocks the merged publish

#### Scenario: Every event carries a source

- **WHEN** any event appears in a per-source file or in the merged feed
- **THEN** its `source` field is populated with the correct source identifier

#### Scenario: Timestamps are ISO-8601 in America/Los_Angeles offset

- **WHEN** an event has a local Portland start time
- **THEN** the emitted `start_at` is an ISO-8601 timestamp with an explicit offset resolvable to America/Los_Angeles (e.g. `-07:00` in summer, `-08:00` in winter)

### Requirement: Stable event identity across runs

Event IDs SHALL be deterministic and stable across runs of both the source workflow and the merge workflow, so that client bookmarks continue to resolve.

#### Scenario: Same upstream event, later run

- **WHEN** an event that appeared in a source workflow's run N is still present in run N+1 with no upstream ID change
- **THEN** its emitted `id` in run N+1 is byte-identical to run N, both in the per-source file and in the merged feed

#### Scenario: ID composition

- **WHEN** any source workflow generates an event ID
- **THEN** the ID incorporates both the source identifier and the upstream ID (e.g. `calagator:12345`, `ticketmaster:vv1234ABCDE`), never a random or run-time value

### Requirement: Deduplication at merge time

The merge workflow SHALL detect and merge events that appear in more than one source, retaining a single canonical entry per real-world event in the merged feed while preserving the per-source files unchanged.

#### Scenario: Same event listed on Calagator and Ticketmaster

- **WHEN** two per-source files contain events matching the same venue and start time within a small tolerance
- **THEN** the merged `events.json` emits one entry whose ID reflects the preferred source (Ticketmaster wins for ticketed events, Calagator wins for free community events)

#### Scenario: Attribution after merge

- **WHEN** the merge collapses two source entries into one
- **THEN** the merged event's `source` field still points to a real source, both origins are preserved in a `merged_sources` field, and per-source files still contain their original unmerged entries so no source ever appears to "lose" data

#### Scenario: Merge does not modify per-source files

- **WHEN** the merge workflow runs
- **THEN** it reads `sources/*.json` and writes `events.json` (and `sources/index.json`), but never rewrites any `sources/<source_id>.json`

### Requirement: No secrets leak into artifacts

Upstream API credentials SHALL be sourced only from GitHub Actions secrets, SHALL be scoped only to the workflow that needs them, and SHALL NOT appear in any published artifact, commit message, or workflow log.

#### Scenario: Secret scoping

- **WHEN** the Ticketmaster source workflow runs
- **THEN** it is the only workflow that reads `TICKETMASTER_API_KEY`; the Calagator source workflow and the merge workflow have no access to it

#### Scenario: Secret redaction in logs

- **WHEN** a source fetcher logs its outbound requests
- **THEN** any API key value is redacted or omitted from the log line

#### Scenario: Published artifacts contain no credentials

- **WHEN** any per-source file or the merged `events.json` is published
- **THEN** it contains no field named or containing an API key, access token, or authorization header

### Requirement: Upstream terms compliance

Each source workflow SHALL respect its upstream's terms of service and licensing requirements.

#### Scenario: Ticketmaster attribution

- **WHEN** a Ticketmaster event is included in that source's per-source file
- **THEN** its `source` field identifies Ticketmaster so the client can display the required attribution, and the pipeline README documents the ToS obligations

#### Scenario: Calagator license attribution

- **WHEN** a Calagator event is included in that source's per-source file
- **THEN** its `source` field identifies Calagator, and the pipeline README documents the CC BY license terms

#### Scenario: Rate limits are respected per source

- **WHEN** a source workflow hits an upstream that has a documented rate limit
- **THEN** it stays comfortably under the limit at the source's own cadence (Ticketmaster's 5,000/day free tier is not exceeded even with 24 hourly runs plus manual dispatches)
