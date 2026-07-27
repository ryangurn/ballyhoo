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
| Ticketmaster | API key | ~710 events / yr | Touring acts plus independent venues |

Volumes are measured, not estimated, and the two barely overlap — Ticketmaster is
Bocelli, Weezer, and the Wonder Ballroom; Calagator is Code & Coffee and the Drupal
user group. Cross-source dedup is therefore insurance for sources yet to be added
rather than something these two need.

Both together are still mostly ticketed shows. The neighborhood-level programming the
app is really for — library story times, parks events, civic meetings, Portland
Mercado — arrives with the sources still queued.

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

Discovery API, free tier: 5,000 calls/day. A full run costs 4 requests. Needs
`TICKETMASTER_API_KEY` — the "Consumer Key" from an app on
[developer.ticketmaster.com](https://developer.ticketmaster.com).

```bash
uv run python -m pipeline.sources.ticketmaster --histogram   # inspect, don't publish
uv run python -m pipeline.sources.ticketmaster --output /tmp/tm.json
```

**No `segmentName` filter is sent, deliberately.** Ticketmaster documents six segments
but actually returns a seventh, `Undefined`, holding 7% of Portland's events — and
they are the best ones: Dante's, Jack London Revue, Wonder Ballroom, Holocene, White
Eagle Saloon. Independent venues, live music, cabaret, burlesque. An allow-list of the
documented six drops every one of them. Measured, an unfiltered query returns 548
events against a six-name list's 503.

**The API truncates silently past the 1,000th result** (`size * page < 1000`). The
fetcher reads `page.totalElements` up front and aborts above 900 rather than
publishing a feed that looks complete but isn't. Current headroom is roughly 280
events. If it ever trips, slice by date range — never by segment, which loses the
`Undefined` events all over again.

Measured shape of the Portland feed (365 days, 25 miles):

| | |
|---|---|
| Matching events | ~719, of which 710 survive normalization |
| Segments | Music 61%, Arts & Theatre 20%, Sports 8%, Undefined 7%, Miscellaneous 2% |
| Family / Film | Zero Portland inventory |
| Dropped | 3 cancelled, 6 with placeholder times |
| Coverage | venue, image, and listing URL on 100%; price on 31%; description on 42% |

Other things live data forced:

- `dates.start.dateTime` is UTC while `dates.timezone` carries the real zone. Events
  are converted to local, or an 8pm show renders as 3am.
- `dates.status.code` includes `cancelled`, which is excluded. `offsale` is kept —
  sold out is still a real event worth showing.
- `priceRanges` is absent on ~70% of events, so those are price-unknown, not free.
- Genres are an open vocabulary. Unmapped ones fall back to their segment silently,
  because that is the correct outcome; only an unmapped *segment* is reported, since
  that means Ticketmaster added one and the table needs a row.

Their terms require "Powered by Ticketmaster" attribution, satisfied by the mandatory
`source` field the app renders.

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
