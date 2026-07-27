## Why

Once `add-events-aggregation-pipeline` ships, the fastest way to break real users is a bad source normalizer. Upstream data is messy — Calagator's community submissions have inconsistent tags, Ticketmaster's classifications shift, future scrapers will chase moving HTML — and the only current safety nets are unit tests against captured fixtures (which miss new upstream shapes) and `--dry-run` workflow dispatches (which produce a workflow artifact, not a browsable feed on a device).

We need a way to iterate on source code against real upstream data and see the result in the actual app, without any risk of poisoning the production feed. That's what a staging feed gives us: a parallel, dev-only publish path fed from a `staging` branch, consumed by dev builds of the client.

## What Changes

- Introduce a `staging` git branch as the source of truth for staging pipeline code. Pipeline maintainers push experimental normalizer or workflow changes there.
- Every existing pipeline workflow (source workflows + merge workflow) SHALL accept an `environment` input (`production` | `staging`) on `workflow_dispatch`, plus a `ref` input for staging that defaults to `staging`. When `environment: staging`, the workflow checks out the specified ref, runs its normal pipeline, and publishes to a `staging/` prefix on `gh-pages` instead of the root.
- Introduce a `.github/workflows/staging-refresh.yml` workflow that triggers on push to the `staging` branch. It fans out `workflow_dispatch` calls to every source workflow with `environment: staging, ref: staging`, then to the merge workflow. Push a change to `staging`, and within minutes the staging feed rebuilds.
- Publish staging artifacts at:
  - `https://ryangurn.github.io/sociallist/staging/events.json` — merged staging feed
  - `https://ryangurn.github.io/sociallist/staging/sources/<source_id>.json` — per-source staging files
  - `https://ryangurn.github.io/sociallist/staging/sources/index.json` — staging health metadata
- Staging publishes SHALL NEVER write to production paths, and production publishes SHALL NEVER write to staging paths. The two feeds are fully independent.
- Client side: add a new `Debug-Staging` Xcode build configuration with a `STAGING` compilation condition. `FeedSource.production` resolves to the staging URL when built under that configuration.
- Client side: add a launch-argument override (`-feedEnvironment staging`) so QA can force staging on any build without a rebuild. The compilation condition wins by default; the launch argument overrides it either direction.
- Staging retains the same schema validation, secret handling, and last-known-good behavior as production. The only differences are the URL prefix and the branch/ref the pipeline code is checked out from.
- Production workflows continue to run from `main` on their existing schedules. Nothing about production behavior changes.

## Capabilities

### New Capabilities

- `staging-feed`: the developer-facing staging environment — separate URLs, environment-input dispatch on pipeline workflows, `staging` branch triggering, and client-side selection via build configuration or launch argument.

### Modified Capabilities

None at the spec level. `event-aggregation-pipeline` and `feed-publication` remain unchanged in their production contracts — the staging behavior is entirely additive and lives in its own capability. The workflow YAML files gain a new input, but that's implementation, not spec-level behavior of the production capabilities.

## Impact

- **New workflow file:** `.github/workflows/staging-refresh.yml` — triggers on push to `staging`, dispatches every source workflow and the merge workflow with `environment: staging, ref: staging`.
- **Existing workflow files modified:** all three of `source-calagator.yml`, `source-ticketmaster.yml`, `merge-feed.yml` gain an `environment` (default: `production`) and `ref` (default: current) input on `workflow_dispatch`, and pass those through to `python -m pipeline.*`.
- **Pipeline code change:** `pipeline/common/publish.py` gains awareness of the target environment and computes the path prefix (`""` for production, `"staging/"` for staging). No other pipeline module changes.
- **Client change:**
  - New Xcode build configuration `Debug-Staging` (duplicate of `Debug` with `STAGING` in `SWIFT_ACTIVE_COMPILATION_CONDITIONS`).
  - `sociallist/Data/EventStore.swift`: `FeedSource.production` becomes a computed static that reads the launch argument first, then the compilation condition, then falls back to the production URL.
  - New scheme `sociallist (Staging)` that uses the `Debug-Staging` configuration for Run.
- **`gh-pages` branch layout gains:**
  - `staging/events.json`
  - `staging/sources/<source_id>.json`
  - `staging/sources/index.json`
  - `staging/history.json` (staging's floor-check history, kept independent of production's)
- **No production data path change.** Every production URL and file stays where it was, produced by workflows checking out `main` on their existing schedules.
- **Actions minutes budget:** staging runs are event-driven (push to `staging`), typically infrequent (a maintainer iterating on a normalizer). Even under heavy iteration (~10 pushes/day × 3 workflows × 1 min) the added cost is a few dozen minutes per day at most. Well under any budget concern.
- **Repo settings:** No new secrets required. `TICKETMASTER_API_KEY` is reused — staging fetches from the same upstream, respecting the same rate limit (the staging cadence is push-driven, so it's not a meaningful add).
- **Non-goals:**
  - No automatic promotion from `staging` → `main`. Promotion is a normal git merge, review, and PR flow.
  - No multi-tier staging (single staging environment only).
  - No TestFlight or preview build distribution — this proposal is about the feed, not the app binary.
  - No staging monitoring dashboards beyond the same `sources/index.json` shape at `/staging/sources/index.json`.
