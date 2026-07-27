## ADDED Requirements

### Requirement: Independent staging URL namespace

Staging artifacts SHALL be published under a URL prefix distinct from production, so a client can select an environment by URL alone and neither environment can accidentally overwrite the other.

#### Scenario: Staging URLs use a stable prefix

- **WHEN** the pipeline publishes a staging artifact
- **THEN** it is served at `/staging/events.json`, `/staging/sources/<source_id>.json`, or `/staging/sources/index.json` — never at the corresponding production path

#### Scenario: Production URLs never move

- **WHEN** any staging workflow runs, whether successfully or with failure
- **THEN** the production paths at `/events.json` and `/sources/*` remain untouched

#### Scenario: Same schema for both environments

- **WHEN** a client fetches a staging artifact
- **THEN** it decodes with the same schema and code paths as the production equivalent — staging is a different URL, not a different shape

### Requirement: Environment-aware workflow dispatch

Every pipeline workflow that publishes SHALL accept an `environment` input on `workflow_dispatch` with values `production` (default) and `staging`, and route its publish step to the corresponding path prefix.

#### Scenario: Default environment is production

- **WHEN** a scheduled trigger or manual dispatch fires without specifying `environment`
- **THEN** the workflow publishes to production paths

#### Scenario: Explicit staging dispatch

- **WHEN** a maintainer dispatches a source workflow with `environment: staging`
- **THEN** that run's per-source file is published at `/staging/sources/<source_id>.json` and its entry appears only in `/staging/sources/index.json`

#### Scenario: Staging merge dispatch

- **WHEN** the merge workflow is dispatched with `environment: staging`
- **THEN** it reads only from `/staging/sources/*.json`, dedupes across them, and publishes the merged result to `/staging/events.json`

### Requirement: Staging code runs from a configurable ref

Staging workflow dispatches SHALL check out a caller-specified git ref for the pipeline code, defaulting to the `staging` branch. Production dispatches SHALL always run pipeline code from the default branch.

#### Scenario: Default staging ref

- **WHEN** a staging dispatch fires without specifying `ref`
- **THEN** the workflow checks out the `staging` branch's pipeline code and runs it against real upstreams

#### Scenario: Ad hoc ref for staging

- **WHEN** a maintainer dispatches a staging run with `ref: my-experimental-branch`
- **THEN** the workflow checks out that branch's pipeline code and runs it, publishing to staging paths

#### Scenario: Production ref is fixed

- **WHEN** any workflow runs with `environment: production`
- **THEN** it checks out the default branch's pipeline code and ignores any `ref` input for the pipeline

### Requirement: Push-to-staging auto-refresh

Push events on the `staging` branch SHALL trigger a full staging refresh across every source and the merge, so a maintainer sees the effect of their change in the staging feed without further manual action.

#### Scenario: Staging push triggers all sources

- **WHEN** a commit is pushed to the `staging` branch
- **THEN** the staging-refresh workflow dispatches every source workflow with `environment: staging, ref: staging`

#### Scenario: Staging push triggers a merge

- **WHEN** the source dispatches from a staging refresh complete
- **THEN** the merge workflow runs with `environment: staging` and produces an updated `/staging/events.json` within minutes of the original push

#### Scenario: Non-staging pushes do not affect staging

- **WHEN** a commit is pushed to any branch other than `staging`
- **THEN** no staging workflow is triggered

### Requirement: Staging isolation from production

No staging workflow run SHALL alter production paths or state, and no production workflow run SHALL alter staging paths or state.

#### Scenario: Staging failure isolation

- **WHEN** a staging workflow fails at any step
- **THEN** production paths (`/events.json`, `/sources/*`) remain unchanged and no production workflow is delayed or affected

#### Scenario: Production failure isolation

- **WHEN** a production workflow fails
- **THEN** staging paths (`/staging/**`) remain unchanged

#### Scenario: Independent history

- **WHEN** the merge workflow performs its floor check
- **THEN** production merges compare against production's history file (`/history.json`), and staging merges compare against staging's history file (`/staging/history.json`) — never against each other

#### Scenario: Staging runs are not archived

- **WHEN** any workflow runs with `environment: staging` and publishes successfully
- **THEN** no historical snapshot is written to the `archive` branch; the archive records only what was published to production, so it remains a faithful record of what real users actually received

### Requirement: Client can select environment at build time

Dev builds of the client SHALL be able to select the staging feed at compile time via a build configuration and a Swift compilation condition, so developers can build a staging-pointing binary without runtime configuration.

#### Scenario: Staging build configuration

- **WHEN** the client is built with the `Debug-Staging` configuration active
- **THEN** `FeedSource.production` resolves to the staging URL

#### Scenario: Production release builds ignore staging

- **WHEN** the client is built with any release or production configuration
- **THEN** `FeedSource.production` resolves to the production URL regardless of any staging-related settings

### Requirement: Launch-argument environment override

Clients SHALL support a launch-argument override that selects the feed environment at process startup, so QA and maintainers can flip environments without a rebuild.

#### Scenario: Explicit staging launch argument

- **WHEN** the client is launched with launch argument `-feedEnvironment staging`
- **THEN** `FeedSource.production` resolves to the staging URL for that launch, regardless of build configuration

#### Scenario: Explicit production launch argument on a staging build

- **WHEN** a `Debug-Staging` build is launched with `-feedEnvironment production`
- **THEN** `FeedSource.production` resolves to the production URL for that launch

#### Scenario: No launch argument falls back to build config

- **WHEN** the client is launched without a `-feedEnvironment` argument
- **THEN** `FeedSource.production` resolves per the compiled build configuration

### Requirement: Staging never receives production credentials it does not need

Staging workflow dispatches SHALL access secrets under the same scoping rules as production; no new secret SHALL be required to run staging, and no production-only secret SHALL leak into staging output.

#### Scenario: Ticketmaster staging reuses the production key

- **WHEN** a staging Ticketmaster dispatch runs
- **THEN** it reads `TICKETMASTER_API_KEY` from the same repo secret as production, hits the same upstream, and stays under the same daily quota

#### Scenario: Staging output contains no secrets

- **WHEN** any staging artifact is published
- **THEN** it contains no API keys, tokens, or bearer values — same guarantee as production
