## 1. Pipeline: environment-aware publish helper

- [ ] 1.1 Extend `pipeline/common/publish.py` to accept an `environment: Literal["production", "staging"]` parameter
- [ ] 1.2 Compute the target path prefix from the environment (`""` for production, `"staging/"` for staging); refuse to publish if a caller passes a target path that would escape the prefix
- [ ] 1.3 Update `pipeline/common/index.py` to accept the same environment and read/write the correct `sources/index.json` or `staging/sources/index.json`
- [ ] 1.4 Update `pipeline/merge/__main__.py` to read only from the environment's source directory (production reads `sources/`, staging reads `staging/sources/`) and to check the environment's own `history.json` for the floor check
- [ ] 1.5 Update each source module's `__main__.py` (`pipeline/sources/calagator/__main__.py`, `pipeline/sources/ticketmaster/__main__.py`) to accept a `--environment` CLI argument, defaulting to `production`
- [ ] 1.6 Update `pipeline/merge/__main__.py` to accept `--environment` too
- [ ] 1.7 Add unit tests confirming a staging publish never writes under a production path and vice versa
- [ ] 1.8 Skip the archive step entirely when the environment is staging, so the `archive` branch remains a faithful record of what production users actually received
- [ ] 1.9 Add a unit test confirming a staging run writes nothing to the `archive` branch

## 2. Source workflows: environment input

- [ ] 2.1 Add `environment` (default `production`) and `ref` (default empty; resolved to `staging` when environment is staging) inputs to `.github/workflows/source-calagator.yml` under `workflow_dispatch.inputs`
- [ ] 2.2 In the checkout step, when `environment == staging`, check out the resolved ref for the pipeline code; when `environment == production`, always check out the default branch
- [ ] 2.3 Pass `--environment ${{ inputs.environment || 'production' }}` to the `python -m pipeline.sources.calagator` call
- [ ] 2.4 Adjust the concurrency group name to `source-calagator-${{ inputs.environment || 'production' }}` so staging and production never collide with each other's own concurrency
- [ ] 2.5 Update the job summary to indicate the environment prominently
- [ ] 2.6 Repeat 2.1–2.5 for `.github/workflows/source-ticketmaster.yml`

## 3. Merge workflow: environment input

- [ ] 3.1 Add `environment` and `ref` inputs to `.github/workflows/merge-feed.yml` under `workflow_dispatch.inputs`
- [ ] 3.2 In the `workflow_run` trigger config, propagate the source workflow's environment: read the completed source workflow's inputs and re-dispatch merge with matching environment (via a small step that inspects `github.event.workflow_run.inputs.environment`)
- [ ] 3.3 When invoked from cron (which is production-only), always pass `environment: production`
- [ ] 3.4 Adjust the concurrency group name to `merge-feed-${{ inputs.environment || 'production' }}` with `cancel-in-progress: true`
- [ ] 3.5 Pass `--environment` and `--override-floor` inputs through to `python -m pipeline.merge`
- [ ] 3.6 Update the job summary to indicate the environment prominently

## 4. Staging fan-out workflow

- [ ] 4.1 Create `.github/workflows/staging-refresh.yml`
- [ ] 4.2 Triggers: `push: branches: [staging]` and `workflow_dispatch`
- [ ] 4.3 Permissions: `actions: write` (needs `workflow_dispatch` on other workflows), `contents: read`
- [ ] 4.4 Step: dispatch `source-calagator.yml` with `environment: staging, ref: staging` via `gh workflow run` or the `workflow-dispatch` action
- [ ] 4.5 Step: dispatch `source-ticketmaster.yml` with the same inputs
- [ ] 4.6 Do NOT dispatch merge directly; rely on the `workflow_run` trigger to fire it after each source completes (matches production behavior)
- [ ] 4.7 Add a job summary listing the workflows dispatched with a link to each run

## 5. gh-pages staging bootstrap

- [ ] 5.1 On the existing `gh-pages` branch, create the `staging/` subdirectory containing:
  - `events.json` seed (valid envelope, empty events array)
  - `sources/index.json` seed (empty sources list)
  - `history.json` seed for the staging floor check
- [ ] 5.2 Commit and push
- [ ] 5.3 Verify GitHub Pages serves each staging URL (`/staging/events.json`, `/staging/sources/index.json`) and returns `Content-Type: application/json` with ETag / Last-Modified headers

## 6. Create the staging branch

- [ ] 6.1 Create the `staging` branch from `main`
- [ ] 6.2 Push it
- [ ] 6.3 Add branch protection (optional): no direct force pushes from anyone else, but no PR requirement (maintainers push directly)

## 7. End-to-end staging validation

- [ ] 7.1 Push a trivial commit to `staging` (e.g. add a comment in `pipeline/sources/calagator/normalize.py`)
- [ ] 7.2 Confirm `staging-refresh.yml` fires and completes
- [ ] 7.3 Confirm both source workflows fire with `environment: staging, ref: staging`
- [ ] 7.4 Confirm the merge workflow fires via `workflow_run` with matching environment
- [ ] 7.5 Fetch `/staging/events.json`; confirm it contains real events and has a fresh `generated_at`
- [ ] 7.6 Fetch `/staging/sources/index.json`; confirm both sources are listed with recent `last_run_at`
- [ ] 7.7 Confirm `/events.json` (production) has NOT been touched by the staging run
- [ ] 7.8 Confirm ETag revalidation works on staging URLs

## 8. Client: Debug-Staging build configuration and scheme

- [ ] 8.1 In Xcode, duplicate the `Debug` build configuration as `Debug-Staging`
- [ ] 8.2 Add `STAGING` to `SWIFT_ACTIVE_COMPILATION_CONDITIONS` for the `Debug-Staging` configuration only
- [ ] 8.3 Create a new scheme `sociallist (Staging)` that uses `Debug-Staging` for the Run action
- [ ] 8.4 Share the new scheme in `sociallist.xcodeproj/xcshareddata/xcschemes/`

## 9. Client: environment resolution

- [ ] 9.1 In `sociallist/Data/EventStore.swift`, introduce a `FeedEnvironment` enum (`.production`, `.staging`) with per-case URLs
- [ ] 9.2 Rewrite `FeedSource.production` as a computed static that resolves the effective environment via:
  1. Launch arguments (`-feedEnvironment staging` or `-feedEnvironment production`) — highest priority
  2. Compilation condition `#if STAGING` — second priority
  3. Fallback: production
- [ ] 9.3 On app boot, log the resolved environment and URL so it's visible in the console
- [ ] 9.4 Ensure the resolution runs exactly once per launch and is cached in a `let` — never resolve per-request

## 10. Client validation

- [ ] 10.1 Build and run the standard `sociallist` scheme; confirm the app hits the production URL (verify via logging or a proxy)
- [ ] 10.2 Build and run the `sociallist (Staging)` scheme; confirm the app hits the staging URL
- [ ] 10.3 Run the `sociallist (Staging)` build with launch argument `-feedEnvironment production`; confirm it hits production
- [ ] 10.4 Run the standard `sociallist` build with launch argument `-feedEnvironment staging`; confirm it hits staging
- [ ] 10.5 Confirm no launch argument on either build falls back to the compiled default

## 11. Documentation

- [ ] 11.1 Add a "Staging" section to `pipeline/README.md` covering: how to iterate a source on `staging`, how to reset `staging`, how to run staging without pushing (manual dispatch), the URL prefixes, and how to point the client
- [ ] 11.2 Add a callout in the top-level `README.md` explaining that pushes to `staging` trigger a real pipeline run
- [ ] 11.3 Document the launch-argument override in `sociallist/Data/EventStore.swift` as a doc comment on `FeedSource.production`

## 12. Isolation soak

- [ ] 12.1 Deliberately break Calagator's normalizer on the `staging` branch (e.g. force a `raise ValueError` in one code path); push
- [ ] 12.2 Confirm the staging Calagator dispatch fails, staging Ticketmaster succeeds, and staging merge falls back to the last-known-good `staging/sources/calagator.json`
- [ ] 12.3 Confirm production paths are entirely unaffected during and after the staging failure
- [ ] 12.4 Revert the deliberate break; confirm the next push to `staging` heals

## 13. Cleanup

- [ ] 13.1 Confirm no secret name changed (still just `TICKETMASTER_API_KEY`, still scoped only to the Ticketmaster workflow)
- [ ] 13.2 Confirm no production workflow file gained a `staging`-specific hardcode — every environment-conditional path is derived from the `environment` input
