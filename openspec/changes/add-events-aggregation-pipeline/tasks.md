## 1. Pipeline project scaffolding

- [ ] 1.1 Create `pipeline/` directory with `pyproject.toml` declaring Python 3.12+ and dependencies (`requests`, `python-dateutil`, `jsonschema`, `beautifulsoup4`)
- [ ] 1.2 Add `pipeline/README.md` with local-run instructions for each source and the merge, source-addition guide, and per-upstream attribution notes (Ticketmaster ToS, Calagator CC BY)
- [ ] 1.3 Add `pipeline/.env.local.example` documenting env vars (`TICKETMASTER_API_KEY`)
- [ ] 1.4 Choose and document `uv` as the dependency manager; add `uv.lock` after first install
- [ ] 1.5 Extend the top-level `.gitignore` to cover `pipeline/.env.local`, `pipeline/dist/`, `pipeline/__pycache__/`, `pipeline/.venv/`, `gh-pages-worktree/`

## 2. Shared schemas and models

- [ ] 2.1 Author `pipeline/schema/events.schema.json` (JSON Schema draft 2020-12) for the merged feed envelope: `{ generated_at, events[] }`, modeling every `Event` field the Swift model consumes
- [ ] 2.2 Author `pipeline/schema/per-source.schema.json` for per-source files: `{ generated_at, source_id, status, events[] }`
- [ ] 2.3 Author `pipeline/schema/sources-index.schema.json` for the `sources/index.json` health file
- [ ] 2.4 Verify the merged-feed schema by validating current Swift `MockEventRepository` fixtures against it (extract fixtures once as a golden file for CI)
- [ ] 2.5 Add `pipeline/common/models.py` with dataclass definitions mirroring the Swift `Event` shape
- [ ] 2.6 Add `pipeline/common/io.py` with JSON encoders that emit snake_case keys and ISO-8601 timestamps with explicit America/Los_Angeles offsets
- [ ] 2.7 Add `pipeline/common/validate.py` that wraps `jsonschema` with helpful error messages

## 3. Shared publish + git helpers

- [ ] 3.1 Add `pipeline/common/publish.py` implementing the `gh-pages` publish helper: clone the branch into a worktree, write the target file(s), `git add` + `git commit` with a source/merge-specific message, `git fetch && git rebase --autostash origin/gh-pages`, `git push` with retry-on-conflict
- [ ] 3.2 Add `pipeline/common/index.py` for reading, updating, and writing `sources/index.json` (used by every workflow to update its own source's entry, or by merge to update aggregate freshness)
- [ ] 3.3 Add `pipeline/common/log.py` with a secret-redacting logger that redacts anything matching `TICKETMASTER_API_KEY` or `sk-` / bearer patterns before writing to stdout or the run report
- [ ] 3.4 Generalize the publish helper to target a named branch and worktree, so the same code publishes to `gh-pages` and to `archive`

## 4. Archive helper

- [ ] 4.1 Add `pipeline/common/archive.py` exposing a single `archive_snapshot(artifact_name, content_bytes, captured_at)` entrypoint
- [ ] 4.2 Compute the content SHA-256 and compare against the artifact's most recent recorded hash; skip writing and report "unchanged" when identical
- [ ] 4.3 Write the recent-tier snapshot, gzipped, to `<artifact>/recent/<YYYY-MM-DD>/<HHMMSS>Z.json.gz`
- [ ] 4.4 Write (overwriting) the daily-tier snapshot, gzipped, to `<artifact>/daily/<YYYY>/<MM>/<DD>.json.gz` so it always holds the day's latest and freezes naturally at midnight
- [ ] 4.5 Prune recent-tier date directories older than the retention window (default 7 days, configurable in one place)
- [ ] 4.6 Update the monthly manifest at `<artifact>/daily/<YYYY>/<MM>/index.json` with capture time, SHA-256, event count, and byte size; keep manifests uncompressed
- [ ] 4.7 Update `<artifact>/recent/index.json` listing currently retained recent-tier snapshots
- [ ] 4.8 Unit-test: identical content twice writes one recent snapshot; changed content writes two; daily entry reflects the latest write of the day
- [ ] 4.9 Unit-test: pruning removes only directories beyond the window and never touches the daily tier
- [ ] 4.10 Unit-test: a snapshot path can never escape its artifact's archive subtree

## 5. Source: Calagator

- [ ] 5.1 Create `pipeline/sources/calagator/` directory
- [ ] 5.2 Add `fetch.py` that GETs `https://calagator.org/events.json` (no auth), with sane timeouts and retry-on-5xx
- [ ] 5.3 Add `normalize.py` producing `Event` records with `source_id = "calagator"` and `id = f"calagator:{upstream_id}"`
- [ ] 5.4 Map Calagator's tags to the app's `Category` values via a static mapping table in `categories.py` (log unknown tags for later triage)
- [ ] 5.5 Drop events with no start time and events whose start is more than 7 days in the past
- [ ] 5.6 Add `__main__.py` orchestrating fetch → normalize → validate against `per-source.schema.json` → (unless `--dry-run`) publish `sources/calagator.json`, update `sources/index.json`, then archive the snapshot as a non-fatal step
- [ ] 5.7 Unit-test the Calagator normalizer against captured sample responses in `pipeline/sources/calagator/tests/fixtures/`
- [ ] 5.8 Add per-source `README.md` noting the CC BY license terms and any Calagator-specific gotchas

## 6. Source: Ticketmaster Discovery API

- [ ] 6.1 Create `pipeline/sources/ticketmaster/` directory
- [ ] 6.2 Add `config.py` with the tunable knobs in one place: geo scope (`latlong=45.5152,-122.6784`, `radius=25`, `unit=miles`), fetch window (default 365 days), and the deep-pagination guard threshold (default 900)
- [ ] 6.3 Add `fetch.py` issuing a single query bounded by `startDateTime = now` and `endDateTime = now + window`. Send **no** `segmentName` parameter — an exhaustive six-name allow-list measurably returns fewer events (503) than an unfiltered query (548), so any segment filter is lossy by construction
- [ ] 6.4 Read `page.totalElements` from the first response and abort the run with an explicit error if it exceeds the guard threshold. The API refuses to serve past the 1,000th item (`size * page < 1000`), and truncation there is silent — a loud failure is the only way to notice
- [ ] 6.5 Page through results using the maximum supported page size, stopping at exhaustion (measured volume is ~723 at a 365-day window, so a single query suffices; no segment- or date-slicing needed at current scale)
- [ ] 6.6 Handle rate limiting: back off on `429`, and log request count plus the `Rate-Limit-Available` response header per run so quota consumption is visible against the 5,000/day allowance
- [ ] 6.7 Add `normalize.py` producing `Event` records with `source_id = "ticketmaster"` and `id = f"ticketmaster:{upstream_id}"`; carry ticket URL through to `ticket_url`
- [ ] 6.8 Add a segment → `Category` mapping: Music → `.music`, Sports → `.sports`, Arts & Theatre → `.arts`, Family → `.family`, Film → `.film`, Miscellaneous → `.community`. Family and Film are currently empty in Portland but map them anyway so future inventory lands correctly
- [ ] 6.9 Add genre-level refinement where a genre maps more precisely than its segment, and a sane fallback for genres that do not: the live data includes `Other` (23 of 200 sampled) and `Ice Shows`, neither of which has an obvious `Category`. Never drop an event for lacking a clean mapping; fall back to the segment's category and log the genre
- [ ] 6.10 Guard against the segment-vs-genre name collision: `Family` and `Miscellaneous` exist at both levels (genre `KnvZfZ7vAkF` "Family" sits under the Film segment, meaning family films). Map on the correct classification level, never on bare name
- [ ] 6.11 Add a `--histogram` flag that fetches, prints a breakdown by segment and genre with counts and sample titles, and exits without normalizing or publishing — the tool used to derive the current config, kept for re-tuning as volume shifts
- [ ] 6.12 Add `__main__.py` orchestrating fetch → normalize → validate against `per-source.schema.json` → (unless `--dry-run`) publish `sources/ticketmaster.json`, update `sources/index.json`, then archive the snapshot as a non-fatal step
- [ ] 6.13 Unit-test the Ticketmaster normalizer against captured sample responses in `pipeline/sources/ticketmaster/tests/fixtures/`, covering the four segments that actually appear (Music, Arts & Theatre, Sports, Miscellaneous) plus an `Other` genre and a missing-genre case
- [ ] 6.14 Unit-test that the deep-pagination guard fires: feed a mocked response with `totalElements` above the threshold and assert the run aborts rather than truncating
- [ ] 6.15 Add per-source `README.md` documenting the Discovery API ToS obligations, required "Powered by Ticketmaster" attribution, why no segment filter is sent, and the 1,000-item ceiling with date-slicing as the escape hatch

## 7. Merge workflow logic

- [ ] 7.1 Create `pipeline/merge/` directory with `__main__.py` as the entrypoint
- [ ] 7.2 Read every `sources/<source_id>.json` from the local `gh-pages` worktree; skip sources with no file (never-succeeded) and log them in the run report
- [ ] 7.3 Add `dedupe.py` grouping candidate events by normalized venue name + start time bucket (±30 minutes); apply source preference (Ticketmaster wins for ticketed, Calagator wins otherwise); preserve both origins in `merged_sources`
- [ ] 7.4 Emit a per-run merge log so we can audit false positives. Expect very few merges with these two sources — sampling shows Ticketmaster is almost entirely large touring acts while Calagator is community submissions, so they barely overlap. Resist over-tuning the heuristic against two sources that rarely collide; a later civic or venue source will exercise it properly
- [ ] 7.5 Sort the final event list by `start_at` ascending
- [ ] 7.6 Validate the assembled `events.json` against `pipeline/schema/events.schema.json`; validation failure exits non-zero
- [ ] 7.7 Compute the floor check: compare current event count against the median of the last N successful merges (stored in `gh-pages/history.json`); refuse to publish if below the floor unless `--override-floor` is set
- [ ] 7.8 (Unless `--dry-run`) publish `events.json`; update aggregate freshness fields in `sources/index.json`; append the run's count to `history.json`; then archive the merged snapshot as a non-fatal step
- [ ] 7.9 Ensure an archive failure is caught, logged, surfaced in the run report, and does not fail the job or roll back the live publish
- [ ] 7.10 Unit-test dedupe with hand-crafted overlap cases (same venue same time; same venue different time; different venue same time; three-way overlap)

## 8. Source workflows

- [ ] 8.1 Create `.github/workflows/source-calagator.yml`:
  - Triggers: `schedule.cron: '0 * * * *'` (hourly) and `workflow_dispatch` with `dry_run: bool` input
  - Permissions: `contents: write`
  - `concurrency: source-calagator, cancel-in-progress: false`
  - Steps: checkout, setup Python (with cache), install pipeline deps, shallow-checkout `gh-pages` and `archive` into separate subdirectory worktrees, run `python -m pipeline.sources.calagator` (passing `--dry-run` when the input is true), upload the candidate output as a workflow artifact
- [ ] 8.2 Add job summary output rendering the Calagator run report as Markdown
- [ ] 8.3 Create `.github/workflows/source-ticketmaster.yml` mirroring 8.1 but with:
  - `TICKETMASTER_API_KEY: ${{ secrets.TICKETMASTER_API_KEY }}` in the run env, scoped only to the Python step
  - `concurrency: source-ticketmaster, cancel-in-progress: false`
- [ ] 8.4 Add job summary output rendering the Ticketmaster run report as Markdown
- [ ] 8.5 Verify with a `--dry-run` dispatch on each source workflow that the workflow reads its secret (if any) and never logs it

## 9. Merge workflow

- [ ] 9.1 Create `.github/workflows/merge-feed.yml`:
  - Triggers: `workflow_run` on completion of `source-calagator` OR `source-ticketmaster` (only on `success` conclusion); `schedule.cron: '0 * * * *'` as a safety net; `workflow_dispatch` with `dry_run: bool` and `override_floor: bool` inputs
  - Permissions: `contents: write`
  - `concurrency: merge-feed, cancel-in-progress: true`
  - Steps: checkout, setup Python, install pipeline deps, shallow-checkout `gh-pages` and `archive` into separate subdirectory worktrees, run `python -m pipeline.merge` (with `--dry-run` / `--override-floor` derived from inputs), upload the candidate `events.json` as a workflow artifact
- [ ] 9.2 Add job summary rendering the merge run report as Markdown (per-source counts read, dedupe decisions, final event count, floor check result)
- [ ] 9.3 Verify that when a source workflow is added or removed in `pipeline/sources/`, no change to the merge workflow YAML is required

## 10. Branch bootstrap

- [ ] 10.1 Create an orphan `gh-pages` branch locally with:
  - `README.md` explaining it's machine-managed
  - `.nojekyll` so GitHub Pages serves files directly without a Jekyll build
  - `events.json` seed (valid envelope, empty events array)
  - `sources/index.json` seed (empty sources list)
  - `history.json` seed for the floor check
- [ ] 10.2 Push the branch
- [ ] 10.3 Enable GitHub Pages in repo settings; source: `gh-pages` branch, root directory
- [ ] 10.4 Verify the seed merged feed is reachable at `https://ryangurn.github.io/sociallist/events.json`
- [ ] 10.5 Verify GitHub Pages sends ETag and Last-Modified headers by hitting the URL with `curl -I`
- [ ] 10.6 Create an orphan `archive` branch locally with a `README.md` documenting: that it is machine-managed, the two-tier layout, the retention policy, that snapshots are gzipped, and the `curl <raw-url> | gunzip | jq` read one-liner
- [ ] 10.7 Push the `archive` branch; confirm it is NOT configured as a Pages source
- [ ] 10.8 Verify an archived snapshot is publicly readable via `https://raw.githubusercontent.com/ryangurn/sociallist/archive/<path>`
- [ ] 10.9 Confirm workflows shallow-clone each branch independently so `archive` growth never slows a `gh-pages` publish

## 11. Secrets configuration

- [ ] 11.1 Register for a free Ticketmaster Discovery API key
- [ ] 11.2 Add the key as `TICKETMASTER_API_KEY` in repo Actions secrets
- [ ] 11.3 Verify only `source-ticketmaster.yml` references it (grep across `.github/workflows/`)
- [ ] 11.4 Verify the workflow can read it end-to-end with a `dry_run` dispatch

## 12. End-to-end validation before flipping the client

- [ ] 12.1 Dispatch `source-calagator` with `dry_run: true`; download the artifact; sanity-check the candidate `sources/calagator.json`
- [ ] 12.2 Dispatch `source-calagator` with `dry_run: false`; confirm `sources/calagator.json` lands on `gh-pages` and `sources/index.json` updates the Calagator entry; confirm the merge workflow is triggered automatically by `workflow_run`; confirm `events.json` updates
- [ ] 12.3 Run the Ticketmaster source locally with `--histogram` and confirm it reproduces the pre-implementation baseline: ~723 events at a 365-day / 25-mile scope, distributed roughly Music 64%, Arts & Theatre 16%, Sports 10%, Miscellaneous 3%, with Family and Film empty. A large divergence means the fetcher is built wrong, not that Portland changed
- [ ] 12.4 Confirm `page.totalElements` is comfortably below the 900 guard threshold, and record the current headroom against the 1,000-item ceiling
- [ ] 12.5 Confirm the resulting merged feed size is reasonable for a mobile download (with five sources live it measures 2.4 MB uncompressed and 473 KB gzipped; check the actual gzipped transfer size GitHub Pages serves)
- [ ] 12.6 Dispatch `source-ticketmaster` with `dry_run: true`; sanity-check the artifact
- [ ] 12.7 Dispatch `source-ticketmaster` with `dry_run: false`; confirm parallel behavior to 12.2
- [ ] 12.8 Fetch the merged feed twice back-to-back with `curl -I -H 'If-None-Match: <etag>'`; confirm `304 Not Modified` on the second call
- [ ] 12.9 Fetch a per-source file with the same test; confirm `304`
- [ ] 12.10 Confirm `generated_at` values are sensible: per-source `generated_at` matches its source run, merged `generated_at` matches the merge run
- [ ] 12.11 Confirm every event ID is prefixed with `calagator:` or `ticketmaster:` and every event has a `source` field
- [ ] 12.12 Confirm `sources/index.json` reports both sources as `ok` with recent `last_run_at` and non-zero `event_count`
- [ ] 12.13 Confirm every Ticketmaster event mapped to a `Category`, and review the unmapped-genre log for gaps in the six-segment mapping table
- [ ] 12.14 Confirm each successful publish produced a recent-tier archive snapshot and updated that artifact's daily-tier entry
- [ ] 12.15 Dispatch a source workflow twice with no upstream change in between; confirm the second run skips archiving as unchanged and reports it
- [ ] 12.16 Confirm an archived snapshot round-trips: fetch via raw URL, gunzip, and validate it against the same JSON Schema the live artifact uses
- [ ] 12.17 Confirm the monthly manifest lists the new snapshots with correct capture time, hash, event count, and size
- [ ] 12.18 Simulate an archive failure (e.g. temporarily point the archive worktree at a bad path); confirm the live publish still succeeds, the job does not fail, and the run summary reports the missed snapshot

## 13. Client wiring

- [ ] 13.1 Flip `FeedSource.production` in `sociallist/Data/EventStore.swift` from `.mock` to `.remote(URL(string: "https://ryangurn.github.io/sociallist/events.json")!)`
- [ ] 13.2 Build and run on the simulator; confirm the Discover feed renders real Portland events
- [ ] 13.3 Build and run on a physical iPhone; confirm the same, and confirm ETag-based revalidation on a second cold launch (via a proxy or by inspecting `URLSession` logs)
- [ ] 13.4 Confirm the Sources tab displays the correct `generatedAt` freshness reflecting the last merge run

## 14. Documentation and follow-up hooks

- [ ] 14.1 Update top-level `README.md` with a "Data" section pointing at the pipeline directory, the merged feed URL, and the per-source URLs
- [ ] 14.2 Add "How to add a new source" section to `pipeline/README.md` covering: create `pipeline/sources/<new-source>/` (fetch, normalize, `__main__.py`, tests, README), add `.github/workflows/source-<new-source>.yml` (copy Calagator's YAML as a template), register in `pipeline/sources/__init__.py`, done
- [ ] 14.3 Document the archive in `pipeline/README.md`: branch layout, both retention tiers, raw URL scheme, the gunzip read one-liner, and how to restore a historical snapshot as the live feed
- [ ] 14.4 Record the deferred archive-compaction work explicitly — what it does (orphan-commit rewrite of the `archive` branch, force-push), why it is needed (pruning bounds the working tree but not git history), and the ~6–8 month runway before it matters — measured against the live `archive` branch at a 473 KB gzipped feed rather than estimated, so note the feed size the figure depends on
- [ ] 14.5 File follow-up OpenSpec change notes for Eventbrite, portland.gov, Multnomah County Library, Oregon Metro, and per-venue scrapers (each becomes its own proposal that adds one source module and one workflow file)

## 15. Observability soak

- [ ] 15.1 Enable schedules on all three workflows; confirm at least one full week of automated runs succeed unattended
- [ ] 15.2 Deliberately break the Calagator source (in a branch, e.g. bad URL) and confirm:
  - `source-calagator` fails
  - `source-ticketmaster` keeps running on schedule, unaffected
  - The merge workflow keeps publishing `events.json` using the last-known-good `sources/calagator.json`
  - `sources/index.json` shows Calagator as `stale` after the threshold
- [ ] 15.3 Deliberately return zero events from a source and confirm its per-source file is not overwritten (last-known-good preservation at source level)
- [ ] 15.4 Deliberately return dramatically fewer events across all sources and confirm the merge floor check refuses to publish without `override_floor: true`
- [ ] 15.5 After the soak week, confirm recent-tier pruning actually fired — snapshots older than the retention window are gone from the working tree while the daily tier is intact
- [ ] 15.6 Measure the `archive` branch's on-disk size after a week and extrapolate the growth rate; compare against the ~23 MB/day measured at a 473 KB gzipped feed and revise the compaction timeline if it is materially off
