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

# One source at a time, into a directory the merge step will read
uv run python -m pipeline.sources.calagator    --output /tmp/sources/calagator.json
uv run python -m pipeline.sources.ticketmaster --output /tmp/sources/ticketmaster.json

# Combine into the canonical feed
uv run python -m pipeline.merge --sources-dir /tmp/sources --output-dir /tmp/feed

uv run pytest
```

That produces the same artifacts the workflows publish: `events.json`,
`sources/index.json`, `history.json`, and a `merge-report.json` recording every
dedup decision and per-source problem.

Sources needing credentials read them from the environment. Copy
`.env.local.example` to `.env.local` and fill it in; that file is gitignored and
never committed. In CI the same values come from GitHub Actions secrets.

## Sources

| Source | Auth | Volume | Window | Notes |
|---|---|---|---|---|
| Ticketmaster | API key | ~705 | 365 d | Touring acts plus independent venues |
| DoPDX | none | ~185 | 30 d | Curated city guide; the richest metadata of any source |
| Oregon Metro | none | ~125 | all | Council meetings, nature activities, regional parks |
| Portland Parks | none | ~30 | season | Summer Free For All — every event free |
| Calagator | none | ~27 | 365 d | Portland's community **tech** calendar |

Roughly 1,070 events merged, about 200 KB gzipped. Volumes are measured, not
estimated.

Cross-source dedup earns its keep here: DoPDX and Ticketmaster list many of the same
ticketed shows, and a merge run collapses around a dozen. Calagator and Oregon Metro
overlap nothing.

### Sources evaluated and rejected

Worth recording so the ground is not re-covered:

| Source | Why not |
|---|---|
| portland.gov events | JS-rendered Drupal; no feed, no iCal, no JSON:API |
| Multnomah County Library | JS-rendered; zero event data in the HTML |
| Eventbrite | React-hydrated; public search API discontinued in 2019 |
| Travel Portland | Real WordPress API, but Cloudflare blocks non-browser TLS fingerprints |
| Hillsboro Parks | Hard 403 at their edge |
| Bandsintown / Songkick / SeatGeek | All require API keys |

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

- `dates.start.dateTime` is UTC while `dates.timezone` carries the real zone — but the
  latter is **missing on ~37% of results**. Those default to Pacific, which is safe
  because a 25-mile radius around downtown Portland contains no other zone. Left in
  UTC the instant is still correct, but a 7pm show serializes as the next day at
  02:00Z and gets filed under the wrong date by anything bucketing on the date string.
- Events that *do* declare a non-Pacific zone are dropped as internally inconsistent.
  Live data returns "Life Surge" events for Charlotte, Hartford, Fort Myers, Tampa, and
  Phoenix all tagged to the Oregon Convention Center. Their titles name the real cities;
  either the venue or the time is wrong upstream and there is no telling which.
- `dates.status.code` includes `cancelled`, which is excluded. `offsale` is kept —
  sold out is still a real event worth showing.
- `priceRanges` is absent on ~70% of events, so those are price-unknown, not free.
- Genres are an open vocabulary. Unmapped ones fall back to their segment silently,
  because that is the correct outcome; only an unmapped *segment* is reported, since
  that means Ticketmaster added one and the table needs a row.

Their terms require "Powered by Ticketmaster" attribution, satisfied by the mandatory
`source` field the app renders.

### DoPDX

Portland edition of the DoStuff Media city guides. A real versioned JSON API with no
authentication: `/events/YYYY/M/D.json?page=N`, one calendar day per request.

Best metadata of any source — venue coordinates and full addresses, an explicit
`is_free` flag, and Cloudinary images we can request pre-sized.

Two things to know. It covers the wider Pacific Northwest, so events are filtered to
within 40 miles of Portland; a single sampled day carried Seattle, Bend, and the
Gorge. And their WAF rejects any User-Agent containing a URL scheme, which is why
`pipeline/common/http.py` identifies us with a bare domain.

Only `/events` is used. Their robots.txt disallows `/features`, `/search`, `/latest`,
`/locales`, `/assets/` and `view=map`.

### Portland Parks — Summer Free For All

Free movies, concerts and festivals in neighbourhood parks, and the closest thing in
the feed to what the app is actually for. Every event is free, and all 35 parks are
geocoded, so all of it maps.

The schedule is one hand-maintained HTML table, which is easy to read and easy to
break, so the parser checks the header row and raises rather than guessing if the
columns move. Reading the wrong column would put a venue name in the title and still
look plausible.

Seasonal: outside summer the table may be missing entirely, which is an empty result
rather than a failure.

## Merge

The only step that writes `events.json`. Reads whatever per-source files exist,
deduplicates across them, validates, applies the floor check, and writes the health
index the app's Sources tab reads.

A source whose latest run failed just has a stale file on disk, and the merge uses it.
One broken upstream degrades freshness rather than deleting that source's events from
the feed.

**Deduplication** matches on normalized venue name plus a start time within 30 minutes,
across different sources only — recurring events legitimately repeat within one source.
Ticketmaster wins for ticketed events since it carries canonical ticket URLs and price
data; Calagator wins otherwise. The survivor backfills fields it lacks from the loser
and records every origin in `merged_sources`, so no attribution is lost. Matching is
deliberately conservative: a false merge hides an event someone could have attended,
while a missed merge is merely untidy.

On the current two sources it fires **zero times** — Ticketmaster is touring acts,
Calagator is tech meetups. It exists for the sources still queued, where a civic or
venue feed will overlap Calagator heavily.

**The floor check** blocks publishing when the event count collapses below 40% of the
recent median. A source can fail by returning HTTP 200 with nothing in it, and without
this the healthy feed gets replaced by a gutted one for every user at once. It stays
disabled until three runs of history exist, so it can't fire on noise during the first
days. `--override-floor` publishes anyway when a drop is genuine.

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
