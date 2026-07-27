## Context

We committed to a build-time aggregation architecture during the shell change: no first-party server, no API keys in the binary, all events delivered as a static JSON file. The shell exists but reads mock fixtures. This design turns that architecture from a diagram into running code.

The client already knows the schema (`event-data-access` capability), already goes through a repository protocol, and already has a stub `RemoteEventRepository` waiting for a URL. This change fills in the other side of the contract: the workflows that fetch, normalize, dedupe, and publish.

Rather than one monolithic workflow that runs every source in-process, the pipeline is **one GitHub Actions workflow per source, plus a merge workflow that stitches per-source outputs into the canonical feed**. This is a deliberate split. Each source has its own quirks — Calagator is a clean JSON endpoint, Ticketmaster needs a keyed HTTP API, future sources will need scraping, retries, backfills, or per-source runners. Baking them into one workflow makes every source's blast radius the whole pipeline. Splitting them makes each source a small, independently-schedulable, independently-fixable unit.

We are deliberately shipping only two sources in this change (Calagator + Ticketmaster). Two is enough to exercise the whole topology — one open JSON feed, one keyed HTTP API — and every additional source is a small, testable follow-up.

## Goals / Non-Goals

**Goals:**

- **One workflow per upstream source**, so failure, iteration, cadence, and secrets are isolated per source.
- **One merge workflow** that reads every per-source output, deduplicates, and publishes the canonical `events.json`.
- Merge is triggered on `workflow_run` from any source workflow, so fresh source data reaches the client within a few minutes, with an hourly safety cron to self-heal missed triggers.
- Deterministic, stable event IDs so client bookmarks survive across runs of both the source and merge workflows.
- A published feed the client can consume verbatim via its existing `FeedDecoder`.
- Per-source files at `sources/<source_id>.json` are a **supported public contract**, not an implementation detail — documented, schema-validated, safe for the Sources tab to consume.
- A per-source health index at `sources/index.json` so tooling and future UIs can see which sources are healthy.
- Cheap client revalidation via ETag on GitHub Pages.
- Local reproducibility — a maintainer can run any single source's pipeline or the merge locally with real inputs.
- Low-drama secret handling — API keys live in GitHub Actions secrets, scoped only to the source workflow that needs them.

**Non-Goals:**

- No dedicated aggregation server, no queue, no database. Everything is a Python module and a GitHub Actions workflow.
- No image hosting. If an upstream provides an image URL, we pass it through. We do not proxy or resize.
- No incremental per-source fetching. Each source workflow does a full refresh. The volumes are small enough that this is fine.
- No client-side pagination or partial feeds. One canonical file for everything.
- No support for Eventbrite / portland.gov / library / venues in this change (each is a follow-up).
- No live analytics / observability beyond GitHub Actions logs, job summaries, and `sources/index.json`.
- **No archive history compaction.** Tiered retention keeps the archive's working tree bounded, but rewriting the `archive` branch's git history to reclaim space is explicitly deferred. See the Decisions and Risks sections for what makes this safe to defer, and for why no runway figure is quoted for it.

## Decisions

**Python 3 for the pipeline runtime, not Swift.**
The pipeline is not part of the shipped app; there is no reason to force it onto Swift on Linux. Python has better libraries for the tasks (`requests`, `python-dateutil`, `jsonschema`, `beautifulsoup4` for scrape sources we'll add later), is native on GitHub-hosted Ubuntu runners with no setup, and is easy to run locally. Alternative considered: TypeScript / Node. Rejected because Python's stdlib and ecosystem are stronger for HTTP + JSON + JSON Schema, and we don't want a `node_modules/` in this repo.

**One workflow per source; one merge workflow. Not one monolithic workflow.**
The core structural decision. Each source has its own YAML file under `.github/workflows/source-<source_id>.yml`, its own Python module under `pipeline/sources/<source_id>/`, its own tests, its own schedule, and its own secrets. A merge workflow at `.github/workflows/merge-feed.yml` reads every `sources/*.json` and produces `events.json`. Alternative considered: one workflow that runs every source in-process with a big `try/except` around each. Rejected because a per-source workflow gives us (a) clean Actions history readable as a per-source status board, (b) real isolation — one source's changes never risk another source's cadence, (c) trivial per-source cadence tuning (just change one file's cron), (d) per-source secret scoping, (e) trivial source additions (drop two new files, no other code changes). The cost — a merge step and some concurrency care — is small.

**Merge trigger: `workflow_run` on every source workflow completion, plus an hourly safety cron.**
Fresh source data reaches the client within minutes of the source finishing, without any client-side wait. The safety cron is a self-heal: if a `workflow_run` trigger is ever dropped (they do occasionally miss), the hourly cron picks it back up. Alternative considered: cron only. Rejected — feels sluggish; every source refresh could wait up to an hour before hitting the client. Alternative considered: `workflow_run` only. Rejected — one missed trigger leaves the feed stale until someone notices.

**Merge concurrency: `concurrency: merge-feed, cancel-in-progress: true`.**
When two source workflows finish within seconds of each other, the older merge is cancelled in favor of the newer one. The newer merge reads whatever per-source files are on disk, so it inherently includes both sources' updates. Alternative considered: `cancel-in-progress: false` (queue merges). Rejected — under bursty triggers we'd accumulate a backlog of nearly-identical merges. Cancelling in progress is cheaper and gives a fresher final result.

**Same repo, aggregators under `pipeline/`, per-source files and merged feed on the `gh-pages` branch of the same repo.**
Keeps everything discoverable. The alternative of a separate `sociallist-data` repo means two repos to keep in sync, an extra deploy key or PAT to manage, and two places to look for issues. The pipeline directory is cleanly separated from the app, so it isn't clutter.

**GitHub Pages from `gh-pages` orphan branch. Merged feed at `/events.json`, per-source files at `/sources/<source_id>.json`, health index at `/sources/index.json`.**
Zero extra infra, native to Actions, ETag-friendly by default on GitHub Pages. Alternative considered: Cloudflare Pages. Rejected — extra account, extra tokens, no meaningful benefit at our traffic. Alternative considered: Cloudflare R2 / S3 bucket. Rejected — more flexible than we need and adds bill/monitoring surface. If GitHub Pages ever pushes back, R2 is a straightforward migration because the client only knows the merged-feed URL.

**Per-source hourly cadence (`0 * * * *`) for both sources in v1.**
Fresh enough for "tonight" events, well under any upstream rate limit, easy to reason about. Alternative considered: differentiate — Ticketmaster hourly, Calagator every 6 hours. Rejected for v1 because we don't know the real cadence-vs-freshness curve yet; land one number, observe, tune. Per-source workflows make this trivial to change later.

**Per-source workflow entrypoint is `python -m pipeline.sources.<source_id>`.**
Each source's `__main__.py` fetches, normalizes, validates, and (unless dry-run) commits its per-source file. Self-contained. Local run is one shell command. Adding a source means creating one directory and one YAML file — no changes to any other source's code.

**Merge workflow entrypoint is `python -m pipeline.merge`.**
Reads every `sources/*.json`, dedupes across sources, validates the assembled `events.json` against the shared JSON Schema, computes the floor check, and (unless dry-run) commits the merged feed and the updated `sources/index.json`.

**Per-source files are a first-class supported contract.**
They're published to a stable public URL, schema-validated, and documented. Reasoning: (a) they're publicly served by GitHub Pages regardless — pretending they're private is a lie, (b) making them a supported contract lets the future Sources tab consume them for per-source freshness display without inventing a new API, (c) they're a useful debugging surface — if the merged feed looks wrong, you can inspect any single source's output directly, (d) third parties who care about only one source can subscribe to just that URL. The cost is a schema commitment for `sources/<source_id>.json`, which we'd need internally anyway.

**Ticketmaster: send no segment filter at all.**
The Discovery API's top-level taxonomy has six segments — Music, Sports, Arts & Theatre, Family, Film, and Miscellaneous — and we want all of them. The non-obvious part is that the correct implementation is to omit the `segmentName` parameter entirely, not to pass all six names.

Measured against live Portland data (25 mi radius, 90-day window): the unfiltered query returns **548** events, while the six segment-filtered queries sum to only **503**. Passing an exhaustive segment list would silently drop roughly 8% of events — presumably those whose classification doesn't match a single top-level segment name cleanly. Any explicit allow-list is therefore lossy by construction, even a complete one.

Keeping everything is also cheaper than expected. Portland's actual distribution is Music 349, Arts & Theatre 85, Sports 54, Miscellaneous 15, and **Family and Film are both zero** — Ticketmaster simply has no Portland inventory in those segments. So including them costs nothing, and the pre-measurement worry that Film would flood us with chain movie showtimes was unfounded. Sports at 54 is likewise not the deluge it was assumed to be.

The client is still the right place to filter: the app's `Category` enum already has a case per segment and Discover already has filter chips, so a user who doesn't want Blazers games can uncheck Sports. Filtering in the pipeline would make that choice for everyone, irreversibly, and lose data for the excluded period unrecoverably.

**Never filter by `segmentId`.**
If we ever do need to narrow, use human-readable `segmentName` values. Opaque IDs like `KZFzniwnSyZfZ7v7nJ` fail silently — one wrong character drops an entire category with no compile-time or runtime signal — whereas a wrong name is obvious in review. This is a guardrail for future changes, not current behavior; today we send no segment filter.

**Bound Ticketmaster volume by a 365-day time window, fetched in a single unsliced query.**
`startDateTime = now`, `endDateTime = now + 365 days`, configurable. Measured volume against live data:

| Window (25 mi) | Events | | Radius (90 d) | Events |
|---|---|---|---|---|
| 30 days | 227 | | 15 mi | 498 |
| 90 days | 548 | | 25 mi | 548 |
| 180 days | 673 | | 50 mi | 577 |
| 365 days | **723** | | 75 mi | 585 |

Both curves flatten hard. Extending 90 → 365 days adds only 175 events (+32%) because Ticketmaster inventory thins out far in the future, but those 175 are precisely the early-announced tours worth surfacing. Widening 25 → 75 miles adds only 37 events (+7%) while pulling in Salem and Vancouver, so 25 miles stays.

Critically, **a full year at the widest radius still lands near 760 — well under the API's 1,000-item deep-pagination ceiling** (`size * page < 1000`). That means no per-segment or per-date query slicing is needed; one paginated query per run suffices. Alternative considered: slice queries per segment to gain headroom. Rejected because segment-sliced queries are lossy (see above) and unnecessary at this volume. If we ever approach the ceiling, date-slicing is the correct escape hatch since it loses nothing.

**Guard loudly against the 1,000-item ceiling rather than trusting today's headroom.**
The fetcher reads `page.totalElements` from the first response and fails the run with an explicit error if it exceeds a threshold (default 900). Silent truncation at the 1,000th item is the worst possible failure here — the feed would look fine while quietly missing events, with no signal anywhere. A loud failure forces the date-slicing conversation at the moment it becomes necessary rather than months later.

**Event IDs are `{source_id}:{upstream_id}`.**
`calagator:12345`, `ticketmaster:vv1234ABCDE`. Deterministic, human-readable, guaranteed stable if upstream IDs are stable. Never regenerated based on title/date/venue — that would break bookmarks the moment an event's details are edited upstream. If a source ever provides no stable ID, we fall back to hashing `{source_id}:{normalized_title}:{start_iso}:{venue_slug}`, and this fallback is a per-source decision, isolated to that source's normalizer.

**Dedupe happens only at merge time — and will rarely fire.**
Source workflows produce their unmerged, un-deduplicated output. The merge workflow is the only place that reasons about cross-source overlap. Match heuristic: normalized venue name + start time within a 30-minute bucket. Source preference: Ticketmaster wins for ticketed events (has canonical ticket URLs), Calagator wins otherwise. The merged event retains all origins in `merged_sources`. Per-source files always show both entries — no source ever appears to "lose" data locally.

Sampling the live Ticketmaster data shows it is almost entirely large touring acts (Megan Moroney, Andrea Bocelli, Weezer, Childish Gambino, Matt Rife), which is a different universe from Calagator's community submissions. The two sources are complementary rather than overlapping, so cross-source dedup is insurance against future sources rather than a mechanism these two need. Build it — a later civic or venue source will overlap Calagator heavily — but treat it as lower priority than getting either source correct, and don't over-tune the heuristic against two sources that barely collide.

**Archives live on a dedicated `archive` branch, not on `gh-pages`.**
Every published artifact is snapshotted to an orphan `archive` branch, publicly readable via `raw.githubusercontent.com/<owner>/sociallist/archive/...`. Alternative considered: `gh-pages/archive/`, which would give clean `ryangurn.github.io` URLs. Rejected for two reasons: GitHub Pages has a soft 1 GB site size limit that archives would consume quickly, and every publishing workflow clones `gh-pages` on every run — bloating it slows every run forever. A separate branch keeps the serving path lean and lets workflows shallow-clone each branch independently. Archives are a debugging and audit artifact, so `raw.githubusercontent.com` is a perfectly adequate public URL.

**Tiered retention from day one: per-run for 7 days, one-per-day forever.**
Two tiers under each artifact:
- `recent/<YYYY-MM-DD>/<HHMMSS>Z.json.gz` — every changed snapshot, pruned after 7 days.
- `daily/<YYYY>/<MM>/<DD>.json.gz` — one snapshot per day, retained indefinitely.

The daily tier is maintained without a rollup job: each publish overwrites the current day's daily entry, so at any moment it holds that day's latest snapshot, and when the date rolls over it naturally freezes as "the last successful publish of that day." Alternative considered: archive everything and add a cleanup workflow later. Rejected because at per-run granularity the archive reaches multiple GB within weeks, and "we'll clean it up later" becomes urgent far sooner than it sounds. Alternative considered: daily-only from the start. Rejected because intra-day resolution is exactly what you need when diagnosing "the feed looked wrong this morning."

**Pruning bounds the working tree, not git history. History compaction is the genuinely deferred work.**
Deleting a file from a branch removes it from the current tree but leaves it in the commit history forever. So tiered pruning keeps the archive *browsable* (a few hundred files instead of tens of thousands) and makes a future compaction cheap, but it reclaims nothing from the `archive` branch's `.git`, which keeps every snapshot that was ever written. Pruning is therefore not a bound on history at all; the only thing that bounds history is not writing a snapshot in the first place, which is what the content-hash dedup below now does.

What one snapshot costs is settled. The merged feed is 1,900 events across five sources, 2.4 MB uncompressed and **473 KB gzipped**, and that gzipped figure is what a changed merged snapshot costs in history. Gzip defeats git's delta compression almost entirely — per-object accounting on the real branch shows every snapshot whose content changed at all beyond its `generated_at` stamp cost between 99.9% and 100.5% of its blob size, because one changed byte early in the stream diverges everything after it. Only snapshots that are byte-identical apart from the timestamp collapse into a delta, and those cost about 60 bytes. So growth is the number of genuinely-changed snapshots per day times their full size, and the merged snapshot dominates that product.

**How many changed snapshots there are per day is the part we do not know, and the two figures previously written here were both wrong.** The first, roughly 11 MB/day and fifteen to eighteen months of runway, was extrapolated from a two-source feed of about 110 KB gzipped and went stale when the feed grew past fourfold. The second, roughly 23 MB/day and six to eight months, was measured per-object rather than extrapolated, but it rested on a premise that has since been disproved: that Ticketmaster's payload changes on every fetch, which on its own would guarantee one full 473 KB merged snapshot every hour and put a hard floor near 14 MB/day. It does not change every fetch. The 704 image URLs that differed between two archived runs were a single deploy — `43499b2`, the image memory fix — landing between those runs and rewriting every URL once. That was verified rather than inferred: today's live payload run through the old selector reproduces 704 of 704 URLs from the 07:12Z snapshot, and run through the new selector reproduces 704 of 704 from the 07:30Z snapshot, while direct polling — five back-to-back fetches, nineteen over five minutes, and nine full-corpus polls a minute apart — returns byte-identical `images` arrays, ordering included. A one-time deploy artefact was read as periodic churn, and the hourly floor it implied never existed. Anyone re-deriving a rate from those same two snapshots will reach the same wrong answer, so the deploy is the first thing to rule out next time.

The other half of the calculation moved at the same time. When the 23 MB/day figure was taken, content-hash dedup could not fire at all (see below), so every archived run wrote something; it now genuinely declines an unchanged snapshot. Both the numerator and the denominator therefore moved downward, and neither has been measured since. The honest position is that the rate is expected to be **materially lower than 23 MB/day** — the disproved premise accounted for roughly half of that figure on its own, and working dedup removes writes on top of it — but the actual rate is **currently unmeasured**, so no runway is asserted here. Task 15.6 settles it by observing the branch over a real window with dedup active rather than extrapolating from cadence, and this paragraph should be rewritten from that measurement rather than from a third estimate. Two things are known without measuring, and they bound the answer from both ends: the rate cannot fall to zero, because the daily tier opens one entry per artifact per day even when content has not changed, and it remains proportional to the gzipped merged feed, so it still rises as the feed grows and as sources land.

The deferred cleanup action is therefore a periodic orphan-commit rewrite of the `archive` branch (replace history with a single commit containing the current tree, force-push), not a file-deletion job. It is deliberately out of scope here; the retention policy above is what makes that action cheap and safe when we write it.

**Snapshots are gzipped.**
JSON with repeated keys compresses roughly 6–10×, which is the difference between a manageable archive and an unmanageable one at this volume. The cost is that snapshots aren't directly viewable in a browser. Acceptable for a debugging artifact — `curl <url> | gunzip | jq` is a normal workflow, and it's documented in the archive branch's README. Manifests stay uncompressed so the archive is discoverable without any tooling.

**Content-hash dedup before writing a snapshot.**
Each artifact's most recent content hash is tracked in its manifest. If the new content hashes identically, no snapshot is written. The check was unreachable as first written and is worth recording as a caution: the hash covered the entire published payload including the `generated_at` stamp, which is fresh on every run and therefore could never match, so across eighteen live runs it skipped exactly nothing. What delivered the saving instead was an accident of `dump_json` sorting keys — `generated_at` sorts after `events`, so a timestamp-only change perturbed just the tail of the gzip stream and git stored the whole snapshot as a delta of around 60 bytes. That was luck rather than design, and it would have ended silently the day someone added a field sorting before `events`. The hash now covers the substantive payload with the timestamp removed, so the intended mechanism is the one doing the work: against two consecutive live runs, the second declined a 122 KB gzipped write it would previously have made. Anywhere earlier notes credit dedup with bounding the archive, that credit belonged to gzip and git, and only now belongs to the check.

Two edges come with a skip that actually fires. The manifest records `content_sha256` alongside `sha256` — the first is what dedup compares, the second still checksums the stored bytes — and an entry predating the fix carries only `sha256`, so it reads as no match and costs one redundant snapshot rather than silently skipping a real one. And unchanged content is skipped only once the current day already has a daily-tier entry, because that tier promises one snapshot per day and an artifact sitting still for a week would otherwise leave a week of holes. That day-opening write is marked `unchanged` in the manifest. It is also why dedup cannot drive archive growth to zero on a quiet day, which matters for the sizing above.

**Archiving happens inline in each publishing workflow, as a non-fatal step.**
After a workflow successfully publishes its live artifact to `gh-pages`, it writes the snapshot to `archive`. If that write fails, the failure is logged and reported in the run summary but does not fail the job — the live publish already succeeded, and that is what users depend on. Alternative considered: a separate `archive-snapshot.yml` triggered by `workflow_run`, fetching the artifact from its public URL. Rejected because GitHub Pages invalidation lag means the archive workflow could snapshot the *previous* content, silently recording history that never matched what was published.

**Manifests are partitioned by month.**
`daily/<YYYY>/<MM>/index.json` and `recent/index.json` list available snapshots with capture time, content hash, event count, and byte size. Monthly partitioning keeps each manifest bounded regardless of how long the archive runs. A single root manifest would grow without bound and be rewritten on every publish.

**Schema validation is a publish gate at both levels.**
Per-source workflows validate against `pipeline/schema/per-source.schema.json` before publishing their file. Merge workflow validates against `pipeline/schema/events.schema.json` before publishing. Validation failure exits non-zero, the previous artifact stays live, the Actions run is marked failed.

**Last-known-good preservation at both levels.**
A source workflow that returns zero events after a successful fetch does not overwrite its per-source file (probably an upstream weirdness rather than reality). A merge workflow whose total event count is below a floor (~40% of the median of the last N successful merges) refuses to publish without an `override_floor` input. The floor state is stored on `gh-pages` alongside the feed.

**Publish is `git commit + push` to `gh-pages` from each workflow.**
Simple, no extra tools, GitHub Pages picks it up automatically. Uses `GITHUB_TOKEN` with `contents: write` — no PAT needed. Every workflow uses the same publish helper (`pipeline.common.publish`), and each workflow only writes the file(s) it owns:
- Source workflows write `sources/<source_id>.json` and their entry in `sources/index.json`.
- Merge workflow writes `events.json` and also updates the aggregate freshness fields in `sources/index.json`.

**Concurrency for the `gh-pages` branch.**
Each workflow uses a `concurrency` group scoped to what it writes:
- `source-<source_id>` for each source workflow (prevents that source from overlapping itself).
- `merge-feed` for the merge workflow with `cancel-in-progress: true`.
There is no shared lock across all workflows — but every workflow does a `git fetch && git rebase --autostash origin/gh-pages` before pushing, and retries on push conflict. Race windows are seconds; the retry loop covers them.

**Secrets live in Actions repository secrets, never in workflows or code.**
`TICKETMASTER_API_KEY` is the only secret needed. It's referenced only from `source-ticketmaster.yml` via `${{ secrets.TICKETMASTER_API_KEY }}`, passed as an env var to Python, and never logged. The Calagator workflow and the merge workflow have no reason to read it, and don't. The pipeline's shared logging helper redacts anything matching a secret pattern before writing the run report.

**Dry-run mode at every workflow.**
Every workflow (each source, and the merge) accepts a boolean `dry_run` input via `workflow_dispatch`. When true, the workflow runs its full pipeline, uploads its candidate output as a workflow artifact, and skips the commit to `gh-pages`. Lets us safely test any source or the merge in isolation.

**Local reproducibility.**
Each source module is runnable directly: `uv run python -m pipeline.sources.calagator --output /tmp/calagator.json`. Merge is runnable directly: `uv run python -m pipeline.merge --sources-dir ./gh-pages/sources --output /tmp/events.json`. `pipeline/README.md` documents both.

**Client wiring is a one-line change.**
`sociallist/Data/EventStore.swift` today has `static let production = FeedSource.mock`. That flips to `.remote(URL(string: "https://ryangurn.github.io/sociallist/events.json")!)`. No new files. No new dependencies. `RemoteEventRepository` already uses `URLSession.shared`, whose URL cache honors ETag automatically.

## Risks / Trade-offs

- **Ticketmaster's ToS is stricter than a typical API.** Their Discovery API allows non-commercial redistribution of event data with attribution but the terms are worth re-reading before shipping. → Mitigation: only redistribute fields their ToS explicitly allows; render "Powered by Ticketmaster" in the client per their brand guidelines; document the compliance stance in `pipeline/README.md` and in `pipeline/sources/ticketmaster/README.md`; keep API usage well under their 5,000/day free tier (24 hourly runs × ~1 request/run ≈ 24 requests/day, plus a comfortable margin for manual dispatches).
- **Calagator's data quality is uneven.** Community-submitted events sometimes have missing venues, weird timezones, or already-passed dates. → Mitigation: the Calagator normalizer drops events with no start time and events whose start is already >7 days in the past. Everything else passes through and lets the client filter.
- **Dedupe heuristic will misfire at merge time.** Two very different events at the same venue starting within 30 minutes of each other could be collapsed. → Mitigation: log every merge decision in the run report. Per-source files preserve unmerged data, so a misfire is recoverable without losing anything. If we see systematic false positives, tighten the window or add title similarity as a secondary check.
- **`workflow_run` triggers can be dropped by GitHub Actions.** Documented but rare. → Mitigation: the hourly safety cron on the merge workflow catches any missed trigger within the hour.
- **`gh-pages` commit contention.** Two workflows could try to push at nearly the same instant. → Mitigation: each workflow only writes files it owns (no cross-writes), `git rebase --autostash` before push, retry-on-conflict wrapper on the push step. Empirically this is a non-issue at our workflow frequency.
- **GitHub Pages can be slow to invalidate.** Sometimes a minute-plus delay between commit and the new content being served. → Acceptable for a build-time architecture; freshness at the minute level is fine.
- **Actions minutes budget.** Two hourly source workflows + a merge triggered per source completion + hourly safety merge ≈ 2 hours/day. Well under free-tier limits on public repos.
- **`gh-pages` branch history grows over time.** Every hour is potentially multiple commits (per source + merge). → Mitigation: periodically force-push a squashed history — but honestly, the size is small and the commit-per-run audit trail is useful. Revisit only if it becomes a problem.
- **A bad pipeline commit could ship a broken merged feed.** → Mitigation: schema validation gate at both source and merge levels; floor check on merge; manual override required to publish anyway; the JSON Schemas are unit-tested against the mock fixtures so schema drift is caught immediately.
- **The `archive` branch's git history grows without bound even with tiered pruning, at a rate we have not yet measured.** Pruning bounds the working tree, not history. → Mitigation: the tiered layout makes a future orphan-commit compaction trivial and safe, and that is what the deferral rests on rather than on any particular runway. Both figures previously recorded here (11 MB/day, then 23 MB/day) were wrong, the second because it assumed hourly Ticketmaster churn that turned out to be a one-time deploy, so the honest statement is that the rate is expected to be materially lower than 23 MB/day against GitHub's ~5 GB recommended ceiling but is currently unmeasured. Task 15.6 measures it. The risk worth naming is therefore not the growth itself but the temptation to re-derive a runway from cadence a third time instead of observing the branch.
- **Ticketmaster volume could grow past the 1,000-item deep-pagination ceiling.** Today's ~723 events at a 365-day window leaves roughly 28% headroom, but a busier Portland or expanded Ticketmaster inventory would erode it, and truncation at the 1,000th item is silent. → Mitigation: the fetcher reads `page.totalElements` on the first response and fails the run loudly above a 900 threshold. The escape hatch is date-slicing the query, which loses nothing (unlike segment-slicing).
- **Every publishing workflow now touches two branches.** More clone work per run, and a second place a push can conflict. → Mitigation: both branches are shallow-cloned into separate worktrees; archive writes are disjoint per workflow (each source writes only its own archive path, merge writes only the events archive), so the same rebase-and-retry helper covers both. Archive failures are non-fatal, so the added surface can't break publishing.
- **Gzipped snapshots aren't browsable in a web browser.** → Acceptable for a debugging artifact; documented with a `curl | gunzip | jq` one-liner in the archive branch README, and manifests stay uncompressed so the archive is navigable without tooling.
- **A long pipeline outage leaves gaps in the daily tier.** No run means no snapshot for that day. → Correct behavior; the manifest reflects what actually happened rather than interpolating, and a gap is itself diagnostic information.
- **Per-source files are a public contract now.** If we later want to change the per-source envelope, we're committed to a versioned URL for backwards compatibility. → Acceptable — the envelope is minimal (`generated_at`, `source_id`, `status`, `events`) and unlikely to change disruptively.

## Migration Plan

1. Land the pipeline code, both source workflows, and the merge workflow. Do not enable schedules yet.
2. Register a Ticketmaster Discovery API key. Add as `TICKETMASTER_API_KEY` in repo secrets.
3. Manually create and push an orphan `gh-pages` branch with a placeholder `events.json`, an empty `sources/` directory, and a stub `sources/index.json`.
4. Enable GitHub Pages on the `gh-pages` branch in repo settings.
5. Manually dispatch the Calagator source workflow with `dry_run: true`; verify the artifact.
6. Manually dispatch the Calagator source workflow with `dry_run: false`; verify `sources/calagator.json` publishes and `sources/index.json` updates.
7. Repeat 5–6 for Ticketmaster.
8. Manually dispatch the merge workflow with `dry_run: false`; verify `events.json` publishes.
9. Verify the URL, ETag, and freshness of both the merged feed and one per-source file.
10. Enable the schedules on all three workflows.
11. Flip `FeedSource.production` in Swift and rebuild locally. Confirm the app decodes and renders real events.
12. Commit the Swift change. The pipelines continue to run.

**Rollback:** revert step 12's commit. `FeedSource.production` goes back to `.mock`. The pipelines keep running but the app ignores them.

## Open Questions

- When exactly should we write the deferred archive-compaction workflow? The previous pass answered this with a date, on the strength of a six-to-eight-month runway; that runway has been withdrawn along with the premise it rested on, so the answer reverts to an open-ended deferral. This is a genuine change of posture and not just a missing number: the case for putting compaction on the calendar was entirely that the ceiling was close, and nothing currently says it is. Task 15.6 supplies the measurement that decides it, and the decision rule is worth fixing in advance so the result is not argued with after the fact — if the observed rate leaves comfortably more than a year, the deferral stands untouched and gets re-checked when the feed grows again; if it leaves materially less, compaction gets a scheduled date then. Picking that rule now is also the cheapest defence against a third estimate.
- Is 7 days the right recent-tier window? It covers "what happened over the weekend" comfortably. Longer windows cost working-tree size but no additional history growth, since history grows at the per-run rate regardless of pruning. Cheap to revisit.
- Does a 365-day window make the Discover feed feel cluttered with events ten months out? The date-window filter chips should handle it, but it is worth looking at on device once real data is flowing. Narrowing the window is a one-line config change if it reads badly.

Resolved since this document was first written: the staging-feed question became the `add-staging-feed` change; the Sources-tab health question became the `add-source-health-ui` change; the Ticketmaster segment and time-horizon questions were settled by measuring live Portland data (see Decisions); and the question of how much Calagator contributes was overtaken by events, since it lands 27 events beside Ticketmaster's 704 and DoPDX's 1,128, and the per-snapshot sizing above is now measured across all five live sources rather than extrapolated from Ticketmaster alone, though the daily rate that sizing feeds into remains open.
- Do we want a workflow for the JSON Schema itself (e.g. a "publish schema" workflow) so third parties integrating against per-source files always see the current schema? Deferring; the schema is in the repo at `pipeline/schema/`, that's discoverable enough.
