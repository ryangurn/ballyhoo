# sociallist pipeline

Aggregates Portland event data into a static JSON feed for the sociallist iOS app.
There is no server: GitHub Actions fetches from each upstream source on a schedule,
normalizes everything into one shape, and publishes a file the app downloads directly.

## Why it works this way

Upstream API keys can't ship in an app binary, and rate limits are per-key — one
Ticketmaster key serving every install would cap the whole user base. Moving
aggregation to build time solves both, and means a broken scraper is fixed by a
commit here rather than an App Store release.

## Layout

```
schema/           JSON Schemas — the contract with the iOS client
src/pipeline/
  common/         models, serialization, validation, secret-redacting logging
  sources/        one self-contained package per upstream source
  merge/          combines per-source output into the canonical feed
```

## Running locally

```bash
cd pipeline
uv sync

uv run python -m pipeline.sources.calagator --output /tmp/calagator.json
uv run pytest
```

Sources needing credentials read them from the environment. Copy
`.env.local.example` to `.env.local` and fill it in; that file is gitignored and
never committed. In CI the same values come from GitHub Actions secrets.

## Sources

| Source | Auth | Volume | Notes |
|---|---|---|---|
| Calagator | none | ~27 events / yr | Portland's community **tech** calendar |
| Ticketmaster | API key | ~723 events / yr | Large touring acts |

Volumes are measured, not estimated. Both are far smaller than they sound, and the
two barely overlap — Ticketmaster is Bocelli and Weezer, Calagator is Code & Coffee
and the Drupal user group.

### Calagator

`https://calagator.org/events.json` returns a bare JSON array with no envelope and no
pagination. A `date[start]` / `date[end]` range roughly doubles coverage over the
unfiltered default.

Quirks worth knowing, none of them documented upstream:

- The venue's display name is `title`, not `name`.
- Coordinates are **strings**, sometimes empty strings, sometimes null. About a third
  of events have no usable coordinates.
- `duplicate_of_id` marks rows that shadow another event. They must be skipped.
- There is **no price field**, so every event is normalized as price-unknown rather
  than free. Most meetups are in fact free, but asserting it without data would put a
  wrong "Free" badge on paid events.
- There are **no tags or categories**, so `Category` is inferred from the title. See
  `sources/calagator/categories.py` — description text was tried and abandoned, because
  a venue named "Hawthorne Asylum food cart pod" made the Drupal user group look like a
  food event.

Licensed CC BY. Attribution is satisfied by the mandatory `source` field on every
event, which the app surfaces in the Sources tab and on event detail.

### Ticketmaster

Not yet implemented. Design notes ahead of building it, from live measurement:

- **Send no `segmentName` filter.** An exhaustive six-segment allow-list returns 503
  events where an unfiltered query returns 548 — any explicit list is lossy.
- **The API refuses to page past the 1,000th item** (`size * page < 1000`) and
  truncates silently. Guard on `page.totalElements` and fail loudly above 900.
- Portland is ~723 events over a 365-day / 25-mile scope, distributed Music 64%,
  Arts & Theatre 16%, Sports 10%, Miscellaneous 3%. Family and Film are empty.
- Requires "Powered by Ticketmaster" attribution per their terms.

## Adding a source

1. Create `src/pipeline/sources/<name>/` with `config.py`, `fetch.py`, `normalize.py`,
   `__main__.py`, and `tests/`.
2. Emit `Event` objects with `id = "<source_id>:<upstream_id>"`. IDs must be stable
   across runs — client bookmarks key off them, so never derive one from a title, date,
   or venue, all of which get edited upstream.
3. Validate against `schema/per-source.schema.json` before publishing.
4. Add `.github/workflows/source-<name>.yml`, copying Calagator's as a template.

No other source's code changes. That isolation is the reason for one workflow per
source rather than one monolithic job.

## Conventions

- Timestamps are ISO-8601 with an explicit offset. A naive datetime is an error, not
  something to guess a timezone for — a wrong offset silently shifts an event by hours.
- Never drop an event for lacking a clean category mapping; fall back and log.
- Never invent a price.
- Secrets are redacted at the logging sink rather than at each call site, because
  relying on every future caller to remember is how keys escape.
