## Context

The `add-events-aggregation-pipeline` change ships a production feed derived from per-source workflows plus a merge workflow. The most fragile piece of that system is the source normalizer — it translates messy, evolving upstream data into the strict `Event` schema. Unit tests against captured fixtures can only catch shapes we've already seen. Real upstream drift is discovered by running the pipeline against live data, which today means either poisoning production or squinting at workflow-artifact JSON.

This change gives us a staging environment: a parallel feed built by the same workflows but from a `staging` branch of pipeline code, published to a `staging/` URL prefix, consumed by dev builds of the client. Push a normalizer change to `staging`, watch the staging feed rebuild, launch a `Debug-Staging` app build, and see the real result on a real device without any risk to real users.

This is a follow-up change to `add-events-aggregation-pipeline`. It assumes that change has shipped and archived. It does not modify the production capability specs; staging is entirely additive.

## Goals / Non-Goals

**Goals:**

- A staging feed at a stable, separate URL that mirrors production's shape exactly.
- Full staging feed on real upstream data (not fixtures), so we catch real drift.
- Push-to-`staging` triggers a full rebuild across all sources plus the merge — a maintainer edits one normalizer, pushes, and sees the effect on a device within minutes.
- Client can point at staging via a build configuration for a dedicated dev build, and via a launch argument for on-the-fly QA toggling.
- Absolute isolation: staging can never touch production paths and vice versa.
- Same schemas, same secret scoping, same last-known-good behavior as production.

**Non-Goals:**

- No automatic promotion of pipeline code from `staging` to `main`. Promotion is a normal PR flow.
- No multi-tier staging (single tier is enough for one dev iterating on one source at a time).
- No preview builds distributed via TestFlight (that's a separate concern about the app binary, not the feed).
- No staging monitoring dashboards beyond the same `sources/index.json` shape.
- No cost accounting per environment.
- No cross-branch staging (e.g., two devs working on different staging branches at once) in v1. If we need it later, we'll extend by publishing to `/staging/<ref>/...` — but v1 is single-slot.

## Decisions

**One set of workflows with an `environment` input, not parallel `-staging` workflow files.**
Each pipeline workflow gains an `environment` input (default `production`) on `workflow_dispatch`. When set to `staging`, the same workflow checks out a specified ref and publishes to `staging/` paths. Alternative considered: duplicate every workflow as `source-calagator-staging.yml`, `merge-feed-staging.yml`, etc. Rejected — doubles the YAML surface, means any workflow bug has to be fixed twice, and every new source has to remember to add both files. One set of workflows with a branch of conditional publish behavior is simpler and stays honest.

**Staging is a git branch, not a workflow parameter alone.**
Staging code lives on the `staging` branch. Staging workflow dispatches check out that branch (or a caller-specified ref) for pipeline code. Alternative considered: staging just changes the output path, always running the same code as production. Rejected because the whole point is to test code changes safely — if staging can't run different code, it doesn't achieve the goal. Alternative considered: use PRs against `main` as the staging surface. Rejected because that couples staging iteration to code review cycles, and iterating a normalizer against real data often requires many small pushes before it's PR-worthy.

**Workflow files themselves stay on the default branch.**
GitHub Actions cron only runs workflow files that live on the default branch. If we put workflow YAML on `staging`, we'd lose scheduled runs. Keeping YAML on `main` and having it check out a ref for the pipeline code is the standard pattern. Alternative considered: put workflow YAML on `staging` too and rely on manual dispatch only. Rejected — no push-triggered staging refresh, worse dev UX.

**Push-to-`staging` triggers a `staging-refresh.yml` fan-out workflow.**
That workflow (living on the default branch) runs on `push: branches: [staging]`. Its only job is to dispatch every source workflow with `environment: staging, ref: staging`. The dispatched source workflows fire their `workflow_run` triggers on the merge workflow, which also runs staging thanks to input propagation. Alternative considered: have every source workflow list `push` on `staging` in its own triggers. Rejected — every new source would need to remember to add the trigger, and we'd multiply the trigger surface. One fan-out workflow keeps it in one place.

**`ref` input alongside `environment` input.**
For flexibility. Default is `staging` when `environment: staging`, but a maintainer can dispatch with `ref: my-experimental-branch` for a one-off. Handy for testing a source change in a topic branch without merging to `staging` first.

**Staging URL prefix is `staging/`, not a subdomain.**
Same GitHub Pages site, path-based split. Alternative considered: separate GitHub Pages site on a different domain. Rejected — much more infra for zero user-facing benefit. The client only cares about the URL string.

**Client environment selection uses both build configuration and launch argument.**
- `Debug-Staging` Xcode build configuration adds `STAGING` to `SWIFT_ACTIVE_COMPILATION_CONDITIONS`. `FeedSource.production` reads that at compile time and picks the staging URL.
- Launch argument `-feedEnvironment staging` or `-feedEnvironment production` overrides at process startup.

Alternative considered: launch argument only, no build config. Rejected — a first-class Xcode scheme for staging is what makes the developer experience good ("run staging" is a scheme picker click), and QA can still override via launch argument without a rebuild. Alternative considered: build config only, no launch argument. Rejected — makes on-device QA cumbersome (rebuild to switch, can't verify parity between environments in one launch).

**No new secret; reuse the production `TICKETMASTER_API_KEY`.**
Staging fetches from the same upstream as production. Same key, same quota. Since staging is push-triggered (a maintainer iterating), its API burn is bounded by how fast they type. In practice a dozen dispatches a day. Adding a separate `TICKETMASTER_API_KEY_STAGING` would double the operational cost of key rotation with no benefit.

**Staging's floor check is independent.**
`/staging/history.json` tracks staging's own event count history. Otherwise a staging run with fewer events (e.g. a broken normalizer) would corrupt the production floor. Small file, cheap to keep separate.

**Staging never triggers on production's cron.**
Production's hourly cron runs `environment: production` only. Staging is only ever dispatched, never scheduled. If we later want a "keep staging fresh even without pushes" cron, we'll add it as a `schedule:` block on `staging-refresh.yml`.

**Staging can share the `gh-pages` branch with production.**
Same branch, different subtree. Alternative considered: dedicated `gh-pages-staging` branch. Rejected — GitHub Pages can only serve from one branch, and putting staging on a different branch would require a second Pages site (extra config, worse). Path-based split on the same branch is the well-trodden path.

## Risks / Trade-offs

- **A staging bug could accidentally write to production paths.** → Mitigation: `pipeline/common/publish.py` computes the target directory from a single `environment` parameter and refuses to publish if the target path escapes the expected prefix. Unit-tested. The two path universes are literally computed from one variable, so drift is minimal.
- **`git rebase --autostash` conflicts between production and staging pushes.** → Both environments push to `gh-pages` but write disjoint files. `git rebase` has to succeed with no conflicts as long as files don't overlap, which they don't. Retry loop covers the small window.
- **A staging run consumes production API quota.** → True but small. Ticketmaster's 5k/day is nowhere near what a maintainer will burn iterating; production is ~24 requests/day, staging peak is maybe ~50/day even on a heavy iteration day. Combined ≈ 75/day vs 5,000 quota.
- **A maintainer iterating on `staging` might accidentally leave a broken change there.** → Acceptable. Staging is not a promise to anyone. If it's broken, they fix it or reset it. Production is unaffected.
- **QA on device with a mixed build (staging build + `-feedEnvironment production` launch arg) is confusing.** → Documented in the pipeline README; the launch argument is a power-user tool.
- **Sources tab in the app doesn't distinguish staging from production.** → For v1 the client just displays whatever feed it's pointed at. If we want an in-app "you are on staging" badge, that's a small follow-up (read the environment resolution at boot, show a debug badge under `#if DEBUG`).

## Migration Plan

1. Land this change on `main` after `add-events-aggregation-pipeline` is live and healthy.
2. Add the `environment` and `ref` inputs to `source-calagator.yml`, `source-ticketmaster.yml`, and `merge-feed.yml`.
3. Teach `pipeline/common/publish.py` to compute the path prefix from the environment.
4. Create the `staging` branch as a fork of `main`.
5. Add `.github/workflows/staging-refresh.yml`.
6. Push a trivial commit to `staging` (e.g. a whitespace change in a source module).
7. Watch `staging-refresh.yml` fire, then the three dispatched source workflows, then the merge.
8. Verify staging URLs exist and have valid content: `/staging/events.json`, `/staging/sources/calagator.json`, `/staging/sources/ticketmaster.json`, `/staging/sources/index.json`.
9. Add the `Debug-Staging` Xcode configuration and `sociallist (Staging)` scheme.
10. Update `sociallist/Data/EventStore.swift` to resolve `FeedSource.production` from launch args → compilation condition → default.
11. Build the `sociallist (Staging)` scheme; confirm it hits the staging URL and renders the staging feed.
12. Rebuild the standard `sociallist` scheme; confirm production is unaffected.
13. Document the staging workflow in `pipeline/README.md`.

**Rollback:** Delete the `staging` branch. Revert the workflow YAML changes so they no longer accept an `environment` input. The client's launch argument code and `Debug-Staging` scheme are inert without a staging URL to point at, so they can be left in place.

## Open Questions

- Do we want an in-app "on staging" debug badge when the effective environment is staging? Small win, small work. Leaning yes as a tiny follow-up.
- Should the `staging-refresh.yml` workflow accept a `skip-source` input for the case where a maintainer knows they only changed one source? Probably not — the fan-out is fast enough that "always run everything" is fine, and simpler.
- Do we want to expose a "promote staging to production" workflow (open a PR from `staging` to `main`)? Nice bit of automation, but a normal git PR flow works fine. Deferring.
- Do we want to auto-reset `staging` from `main` on a schedule so it doesn't drift? Deferring; if drift becomes a pain we'll add a `weekly-reset-staging.yml`.
