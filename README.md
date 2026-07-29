# Ballyhoo

An iOS app for finding out what is happening in Portland, Oregon — concerts, markets,
gallery openings, library talks, city meetings, ballet, volunteer days. Free, no
accounts, no tracking, no ads.

Ten sources are aggregated into one feed of around 5,700 upcoming events across roughly
700 venues. The app reads that feed and nothing else.

## There is no server

The whole project rests on one decision: aggregation happens at build time, in GitHub
Actions, and the app downloads a static JSON file from GitHub Pages.

That falls out of two constraints. Upstream API keys cannot ship inside an app binary,
and rate limits are per-key — one Ticketmaster key serving every install would cap the
entire user base at once. Moving aggregation to a scheduled job solves both. It also
means a broken scraper is repaired by a commit here rather than an App Store release,
which matters when ten upstreams can each change shape without warning.

The cost is that the feed is as fresh as the last run rather than live, which is the
right trade for events that were scheduled weeks ago.

```
upstream sites ──▶ one workflow per source ──▶ sources/<id>.json ──┐
                                                                    ├──▶ merge ──▶ events.json ──▶ iOS app
                                                     (gh-pages branch)
```

## Layout

```
ballyhoo/            SwiftUI app — SwiftUI, @Observable, iOS 17.6+, iPhone and iPad
ballyhoo.xcodeproj/  Xcode project
ballyhooUITests/     Drives the App Store screenshot capture
fastlane/            Build, TestFlight and App Store automation (see fastlane/README.md)
pipeline/            Python aggregation pipeline (see pipeline/README.md)
.github/workflows/   One workflow per source, plus the merge
design/              App icon artwork, light and dark
openspec/            Spec-driven change workflow: proposals, specs, tasks
```

## Sources

Each has its own module, its own workflow, and its own quirks documented in
`pipeline/README.md`. They fail independently — one source breaking leaves the other
nine publishing.

| Source | What it covers | Cadence |
|---|---|---|
| Willamette Week | The alt-weekly's Get Busy calendar, via CitySpark | hourly |
| DoPDX | Music, nightlife, art shows | hourly |
| Ticketmaster | Ticketed concerts and touring shows | hourly |
| PDX Parent | Neighborhood farmers markets | 6-hourly |
| Oregon Metro | Regional government meetings and events | hourly |
| Portland Farmers Market | The market organization's own calendar | 6-hourly |
| Hollywood Farmers Market | A single market's calendar | 6-hourly |
| Portland Parks | Free city parks programming | hourly |
| Calagator | Long-running Portland tech community calendar | hourly |
| Oregon Ballet Theatre | Performances, via Tessitura | hourly |

Sources are staggered across the hour so they do not all publish at once. The merge runs
after any source completes, and on its own schedule as a backstop.

## The published feed

Served from the `gh-pages` branch. These are a supported contract, not internals:

| URL | What |
|---|---|
| [`events.json`](https://ryangurn.github.io/ballyhoo/events.json) | The merged feed. The app reads only this. |
| [`sources/<id>.json`](https://ryangurn.github.io/ballyhoo/sources/index.json) | One source's unmerged output |
| `sources/index.json` | Per-source health: last run, event count, status |
| `merge-report.json` | The last merge's dedup decisions and problems |
| `history.json` | Recent event counts, for the anomaly floor check |

Historical snapshots live on the `archive` branch, kept per-run for a week and daily
after that.

Every event is normalized into one shape regardless of origin — identifier, title,
start and end, venue with coordinates where known, categories, price, image, and a link
back to the source listing. The JSON Schemas in `pipeline/schema/` are the contract
between the pipeline and the app, and CI validates against them.

## Working on it

**The app.** Open `ballyhoo.xcodeproj` and run. It reads the live feed by default;
`MockData.swift` backs the SwiftUI previews and can be swapped in via `EventStore`.

**The pipeline.** Needs [uv](https://docs.astral.sh/uv/).

```sh
cd pipeline
uv sync
uv run pytest                              # ~480 tests, no network
uv run python -m pipeline.sources.calagator --out /tmp/out   # one source, live
```

Sources that need a key read it from `pipeline/.env.local`, which is gitignored; in CI
the same values come from Actions secrets. Most sources need no credentials at all.

**Releases.** fastlane, driven by an App Store Connect API key rather than an Apple ID
so nothing stops to ask for a 2FA code.

```sh
bundle install
bundle exec fastlane build          # clean compile, no credentials needed
bundle exec fastlane beta           # TestFlight
```

Screenshots, upload lanes, the environment variables each needs, and a one-time Xcode
step that has to happen before screenshots work are in
[`fastlane/README.md`](fastlane/README.md).

## Two rules worth knowing before contributing

**Fail loudly.** A source that cannot parse its upstream raises and fails the run rather
than publishing a shrunken feed. The merge additionally refuses to publish if the event
count collapses against its recent baseline, because a silent partial feed is worse than
a stale one.

**Identify honestly.** Every request carries
`ballyhoo-pipeline/0.1 (github.com/ryangurn/ballyhoo)` so any operator can see who we are
and get in touch. We do not impersonate browsers to get around bot protection. Where a
site signals it does not want automated traffic, the answer is to stop reading it.

## Development workflow

Changes are specified before they are built, using [OpenSpec](https://github.com/Fission-AI/OpenSpec).
`openspec/specs/` holds current behavior, `openspec/changes/` holds proposals in flight,
and completed changes are archived rather than deleted so the reasoning survives.
