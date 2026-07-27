## Why

The event-browsing shell ships with mock fixtures. The whole app is worthless until it shows real Portland events, and the architecture we committed to (no first-party backend, no API keys in the binary) means the events have to arrive via a build-time pipeline that publishes a static feed. Ship the pipeline now, wire the client to it, prove the whole loop with two upstream sources; more sources land as separate changes.

Each upstream source has its own quirks — Calagator is an open JSON endpoint, Ticketmaster is a keyed HTTP API, future sources will need scraping. Rather than stuffing every source into a single workflow, we run **one GitHub Actions workflow per source**, plus a lightweight **merge workflow** that stitches the per-source outputs into the single `events.json` the app consumes. This isolates failure, iteration, and cadence per source at the cost of a small merge step — a trade we make gladly because the alternative (one monolithic pipeline where any change touches every source) gets untenable fast as we add more sources.

## What Changes

- Introduce **one scheduled GitHub Actions workflow per source**. Each workflow fetches, normalizes, and validates that source's events, then publishes a per-source file at `sources/<source_id>.json` on the `gh-pages` branch. A failure in one source's workflow is invisible to the others.
- Introduce a **merge workflow** that reads every `sources/*.json`, deduplicates across sources, validates the result, and publishes the single canonical `events.json` at the stable public URL. The merge workflow is triggered on `workflow_run` completion of any source workflow (fresh source data reaches the client within minutes), with an hourly safety cron as a self-heal.
- Ship two source workflows in this change:
  - **Calagator**: open JSON at `https://calagator.org/events.json`, no auth.
  - **Ticketmaster Discovery API**: free API key, scoped to Portland; well under the 5,000/day quota.
- Publish the merged feed at a stable URL served by GitHub Pages: `https://ryangurn.github.io/sociallist/events.json`. ETag / Last-Modified revalidation is automatic on GitHub Pages, so the app's shared `URLSession` cache does conditional GETs cheaply.
- Publish per-source artifacts at `https://ryangurn.github.io/sociallist/sources/<source_id>.json` as a **supported public contract**. Documented, schema-validated, safe for the Sources tab (or third parties) to consume in the future.
- Publish per-source health metadata at `sources/index.json` (last-run timestamp, event count, status per source).
- Retain **immutable historical snapshots** of every published artifact — the merged feed and every per-source file — on a dedicated public `archive` branch, readable via `raw.githubusercontent.com`. Snapshots are gzipped, content-hash deduplicated, and organized in two retention tiers: every changed snapshot for the last 7 days, plus one snapshot per day retained indefinitely. Archiving is a non-fatal step, so an archive failure can never roll back or block a live publish.
- **Explicitly defer** any archive history-compaction workflow. Tiered retention bounds the archive's working tree without one; reclaiming git history is separate future work, deferred open-endedly because the rate at which history grows is not yet known well enough to justify a date. See design for why the two runway figures previously quoted here were withdrawn.
- Wire the client's `.production` `FeedSource` from `.mock` to `.remote(URL)` pointing at the merged feed.
- Establish the full contract for both published artifacts: JSON envelope shape, `generated_at` timestamps, event ID stability across runs, portability across future source additions.
- Add per-source resilience via workflow isolation: one source's workflow failing SHALL NOT block, delay, or corrupt any other source's workflow, and the merge SHALL fall back to that source's last-known-good file.
- Document source-specific attribution and terms compliance (Ticketmaster's ToS, Calagator's CC BY license) in each source workflow's README block and in the pipeline README.
- Store secrets (`TICKETMASTER_API_KEY`) as GitHub Actions repository secrets, scoped only to the workflow that needs them. **No secrets ever ship in the app binary.**
- Provide a manual `workflow_dispatch` trigger and a `--dry-run` mode on both source workflows and the merge workflow, so any step can be previewed without publishing.

## Capabilities

### New Capabilities

- `event-aggregation-pipeline`: the family of per-source GitHub Actions workflows plus the merge workflow — source workflow structure, cadence, isolation, normalization, deduplication at merge time, and manual/scheduled triggers.
- `feed-publication`: the contract for the published artifacts — the canonical merged `events.json` (client-facing) plus per-source `sources/<source_id>.json` files (supported public contract). Covers URL stability, JSON envelope shape, `generated_at` freshness, cache/ETag behavior, and last-known-good preservation.

### Modified Capabilities

None. `event-data-access` already specifies that the remote implementation "reads the published static feed"; the transition from the stub to a live URL is an implementation detail, not a requirement change.

## Impact

- **New files:**
  - `.github/workflows/source-calagator.yml` — Calagator source workflow.
  - `.github/workflows/source-ticketmaster.yml` — Ticketmaster source workflow.
  - `.github/workflows/merge-feed.yml` — merge workflow, triggered by `workflow_run` from any source workflow plus an hourly safety cron.
  - `pipeline/` — Python 3 source, organized so each source is self-contained:
    - `pipeline/common/` — shared models, IO, schema validation helpers.
    - `pipeline/sources/calagator/` — fetch, normalize, tests, entrypoint `python -m pipeline.sources.calagator`.
    - `pipeline/sources/ticketmaster/` — same shape.
    - `pipeline/merge/` — dedupe, validate, publish, entrypoint `python -m pipeline.merge`.
    - `pipeline/schema/` — JSON Schemas: `per-source.schema.json`, `events.schema.json`.
  - `pipeline/README.md` — how to run any pipeline locally, how to add a source, attribution notes.
- **New branch:** `gh-pages`, orphan branch, receives:
  - `events.json` (merged, canonical, client-facing)
  - `sources/<source_id>.json` (per-source raw output)
  - `sources/index.json` (per-source health metadata)
- **New branch:** `archive`, orphan branch, not served by GitHub Pages, publicly readable via `raw.githubusercontent.com`. Receives gzipped immutable snapshots in two tiers:
  - `events/recent/<YYYY-MM-DD>/<HHMMSS>Z.json.gz` and `events/daily/<YYYY>/<MM>/<DD>.json.gz`
  - `sources/<source_id>/recent/...` and `sources/<source_id>/daily/...`
  - Monthly manifests (`index.json`, uncompressed) listing capture time, content hash, event count, and size
- **Repo settings:** GitHub Pages enabled from `gh-pages` branch root. `TICKETMASTER_API_KEY` added as a repository secret, referenced only from the Ticketmaster source workflow.
- **Client change:** `sociallist/Data/EventStore.swift` — `FeedSource.production` flips from `.mock` to `.remote(URL(string: "https://ryangurn.github.io/sociallist/events.json")!)`. Still the only Swift file that changes.
- **Actions minutes:** two source workflows × hourly × ~1 min each = ~48 min/day source runs. Merge workflow triggered per source completion (~2/hour × ~1 min) + hourly safety cron = ~72 min/day merge runs. Total ~2 hours/day, well under free-tier limits on public repos.
- **External dependencies added to pipeline (Python):** `requests`, `python-dateutil`, `beautifulsoup4` (for structured microdata in later scrape sources), `jsonschema` (CI validation). No dependency on any hosted service beyond GitHub and the upstream sources themselves.
- **No client-side impact beyond the one-line source swap.** The `Event` model, `EventRepository` protocol, and every view stay untouched.
- **Archive storage growth:** unquantified for now. A changed merged snapshot costs its full 473 KB gzipped in git history, measured per-object against the live `archive` branch, but how many changed snapshots a day there are is unmeasured under the now-working content-hash dedup. The earlier figures of 11 MB/day and then 23 MB/day were both wrong and have been withdrawn; the rate is expected to be materially below the latter. Tiered pruning keeps the browsable working tree at a few hundred files regardless. Compaction is deferred; see design, and task 15.6 for the measurement that will settle the rate.
- **Non-goals for this change:** Eventbrite (JSON-LD scraping + pagination), civic sources (portland.gov, Multnomah County Library, Oregon Metro), per-venue scrapers (OMSI, Holocene, Portland Mercado). Each becomes its own OpenSpec proposal that adds one workflow YAML file and one source module. Also excluded: the archive history-compaction workflow, deliberately deferred.
