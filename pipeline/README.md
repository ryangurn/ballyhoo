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
uv run python -m pipeline.sources.obt          --output /tmp/sources/obt.json

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
| Eventbrite | none | ~1,770 | 30 d | Largest source by far; states free-ness per event |
| Ticketmaster | API key | ~705 | 365 d | Touring acts plus independent venues |
| PDX Parent markets | none | ~450 | 120 d | 36 neighbourhood farmers markets; schedules parsed from prose |
| DoPDX | none | ~185 | 30 d | Curated city guide; the richest metadata of any source |
| Oregon Metro | none | ~125 | all | Council meetings, nature activities, regional parks |
| Portland Farmers Market | none | ~110 | season | Five markets plus their live music; recurrence pre-expanded upstream |
| Hollywood Farmers Market | none | ~32 | 120 d | One market; its own days expanded from a rule |
| Portland Parks | none | ~30 | season | Summer Free For All — every event free |
| Calagator | none | ~27 | 365 d | Portland's community **tech** calendar |
| Oregon Ballet Theatre | none | ~19 | 18 mo | Tessitura TNEW; one event per performance, not per production |

Volumes are measured, not estimated. Adding Eventbrite roughly doubles the feed — it
alone is about 2.5 MB of JSON, 395 KB gzipped, which is nonetheless slightly *more*
compact per event than the pre-Eventbrite average.

Cross-source dedup earns its keep here: DoPDX and Ticketmaster list many of the same
ticketed shows, and Eventbrite overlaps DoPDX heavily on small-venue events, since
plenty of Portland venues ticket through it. A measured run collapses 159. Calagator and
Oregon Metro overlap nothing.

Eventbrite's 30-day window is the obvious knob if the feed ever needs to be smaller: it
contributes about half the events and half the bytes, and shortening it is a one-line
change in its `config.py`.

### Sources evaluated and rejected

Worth recording so the ground is not re-covered:

| Source | Why not |
|---|---|
| portland.gov events | JS-rendered Drupal; no feed, no iCal, no JSON:API |
| Multnomah County Library | JS-rendered; zero event data in the HTML |
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

### Eventbrite

The largest source in the feed and the only one besides DoPDX that states free-ness per
event rather than leaving us to infer it.

**Finding a way in took three dead ends.** The documented public search API was
discontinued in 2019. The discovery page at `/d/or--portland/events/` is a React
city-landing template whose `window.__SERVER_DATA__` carries shelves and metadata but an
*empty* `search_data` — no events at all, and its single `ld+json` block has none
either. The filtered variants like `/d/or--portland/free--events/` do render the search
template with results embedded, but by construction that route can only ever return free
events.

What works is the endpoint the discovery UI itself calls,
`POST /api/v3/destination/search/`. Their robots.txt disallows the sibling
`/api/v3/destination/events/` and `/api/v3/promoted/events`, but not this path — only its
`log_requests/` subpath. It is CSRF-guarded rather than authenticated, and needs three
things together, all obtainable anonymously: a `Referer` on eventbrite.com, the
`csrftoken` cookie a page load hands out, and that token echoed in `X-CSRFToken`. Miss
any one and it returns `ACCESS_DENIED`. No account, no key. There is no challenge on
this path, so no browser impersonation is involved.

**Which page the cookie comes from matters, and cost this source a day in production.**
The bootstrap originally loaded the discovery page, and that page is behind an AWS WAF
CAPTCHA action for datacenter callers. From a laptop it returns 200; from a GitHub
Actions runner it returns HTTP 405 with `x-amzn-waf-action: captcha` and a "Human
Verification" body — 405 being AWS WAF's status code for its interstitial rather than
anything to do with the method, which is what makes it so easy to misread as a bug in
the request. Nine clients measured from a runner, including `curl` over both HTTP
versions and six `curl_cffi` impersonation profiles, all got the identical 2,543-byte
challenge, so it is neither TLS fingerprinting nor headers. It is not the runner's
address range either: in the same job the site root returned 200 with a `csrftoken`, and
this search endpoint returned 200 with 828 events. The rule is scoped to `/d/`.

So the bootstrap loads `https://www.eventbrite.com/` instead, and the `Referer` is that
same URL, since Django checks the Referer's origin rather than its path. The challenged
page is simply never requested — nothing is solved, presented or impersonated to get
past it. `fetch.py` raises `EventbriteChallengedError` the moment any response carries
`x-amzn-waf-action`, without retrying. If that ever fires on the search endpoint it
means Eventbrite has extended the rule to cover this traffic deliberately, and the
source should be retired rather than pushed harder.

The payoff is `expand.destination_event=[ticket_availability,...]`, which attaches an
explicit `is_free` boolean and ticket price bounds to every result. Without that
expansion the records carry no price information whatsoever.

Measured shape of a run (30 days, both price passes):

| | |
|---|---|
| Fetched / published | 2,213 unique → 1,769 after filtering |
| Free | 569 (32%), each on Eventbrite's own per-event flag |
| Paid with a stated figure | 1,105 (62%), median $60 |
| Price unknown | 95 (5%) |
| Coverage | venue, coordinates, listing URL and end time on 100%; image 99%; description and organizer 96% |
| Cost | 79 requests, about two minutes |

Things live data forced:

- **Results are capped at 1,000 per query and ordered by relevance, not date.** A
  month-wide query would silently return its top 1,000 and drop the rest. The window is
  therefore sliced into weeks and each week queried separately; the busiest sampled week
  held 829, comfortably clear of the cap. `page_size` is also silently clamped to 50 —
  asking for 100 returns 50 — so 50 is what we ask for. A run logs a warning if any week
  ever fills the ceiling, which is the signal to shorten the stride.
- **Free and paid are two passes, deduplicated by event id, because neither is a
  superset of the other.** Over one week the unfiltered pass missed 11 events the free
  filter returned and the free filter missed 6 the unfiltered pass returned; over a full
  run the free pass still contributes ~50 events nothing else found. The two rankings
  simply differ about what falls inside the cap.
- **Timestamps arrive as a local date, a local clock and an IANA zone, with no offset
  anywhere.** The zone is authoritative, not a guess: 1,731 sampled `event_sales_status`
  local/UTC pairs round-trip through `ZoneInfo` exactly, and event pages' schema.org
  `startDate` reproduces what we compute, offset included.
- **About 5% of in-metro results declare a non-Pacific zone** — national certification
  resellers listing "PMP Training in Portland" on Eastern time, and outliers as
  implausible as Asia/Calcutta against a Portland address. Eventbrite renders them in the
  declared zone, so 9am Eastern really is 6am at that venue. Either the clock or the
  address is wrong and there is no telling which, so they are dropped, the same call made
  for Ticketmaster's multi-city listings. That is ~108 events a run.
- **Their "Portland" reaches Newport (91 mi), Centralia (84 mi), Salem and Corvallis.**
  Coordinates are present on 100% of results, so the same 40-mile filter DoPDX uses is
  exact here. It removes ~336 events a run.
- **Images are signature-locked.** Renditions come pre-signed at 320, 640 and 1024 px;
  rewriting `w=` to the ~1136 px the cards actually draw returns HTTP 403 `sig_`. So we
  take `large` at 1024 px, which decodes to about 3 MB, and never `original` at
  2,160-2,560 px or the bare `image.url`, which is unsized and sometimes *is* the
  original. That is the mistake Ticketmaster artwork caused.
- **Prices are split into `major_value` (dollars) and `value` (minor units).** Reading
  `value` would put $1,200 on a $12 event.
- **Around 2% of events are flagged not-free while every ticket class is $0.00** —
  donation and register-to-attend listings, trail parties, community meals. Those are
  published as price-unknown: claiming free contradicts upstream's own flag, and a "$0"
  badge on an event the app treats as paid is worse than saying nothing. A zero
  *minimum* against a real maximum is a different thing — a free tier alongside paid ones
  — and that range is kept.
- `tickets_url` is a `/checkout-external` link, which robots.txt disallows and which
  renders as a bare checkout frame, so both URLs point at the public event page instead.

**What would signal this breaking.** The endpoint is the site's own front-end contract,
not a published API, so it can change without notice. Every failure mode is loud rather
than silent: a CSRF scheme change means no `csrftoken` cookie and the run raises before
fetching anything; a renamed field means page one yields nothing and the run fails rather
than publishing an empty feed; a shape change in `ticket_availability` shows up as free
count collapsing toward zero while the event count holds. The merge floor catches the
rest.

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

### Farmers markets, and recurrence

Three sources cover farmers markets, and together they are the largest block of
genuinely free, walkable, neighbourhood-scale events in the feed. They also forced the
one piece of shared machinery added since the model was written.

**The problem.** `Event` has no recurrence and should not grow any — every event is one
dated occurrence with a stable id, which dedup, staleness and client bookmarks all lean
on. But a market publishes a *rule*: "Saturdays 9am-2pm, May through November". Someone
has to turn one into the other.

`common/recurrence.py` does, once, for everyone. A `WeeklyRule` carries a weekday, an
optional ordinal constraint ("2nd and 4th Saturdays"), and a season written as
month/day pairs with no year — so a rule stays valid across years instead of needing an
annual edit, and a season that wraps New Year still reads as one window. Two properties
are load-bearing:

- **Ids never depend on the run.** An occurrence's id is its series plus its date, never
  its index in the expansion and nothing derived from `now`. Two runs a week apart emit
  byte-identical ids for the same market day, so a bookmark survives.
- **Expansion is always bounded.** A weekly rule is infinite; every caller passes an
  explicit window. Rule-derived sources use 120 days rather than the year the
  calendar-backed ones use, because inferred dates lose confidence with distance — a
  market can change hours, skip a holiday, or close early without telling anyone.

**Free-ness.** These are the only sources that assert `Price.free()` without an upstream
flag, and the reasoning is not a waiver of the usual rule. A farmers market has no gate
and no ticket; what costs money is the produce, not attending. Free-to-show-up is a fact
here rather than an inference.

### Portland Farmers Market

Five markets — PSU, King, Shemanski Park, Lents International, Kenton — on WordPress
with The Events Calendar plus Events Calendar Pro, which exposes a read-only REST route
at `/wp-json/tribe/events/v1/events`. Yoast's robots.txt is an empty `Disallow:`, so
nothing is off limits.

The plugin **already expands recurrence**, handing back one record per date, so this
source needs none of the machinery above — it reads dated occurrences and passes them
through.

The trap is which identifier to key on. Each occurrence carries its own numeric `id`,
and they look like post ids until you notice King's run 10003167–10003184 with no gaps
while real posts on the site sit in the thousands (venues at 6742, one-off events at
31594). They are **provisional ids** synthesized for the series: cancel one market day
and every occurrence after it renumbers, orphaning bookmarks downstream of the edit. The
id is the series slug plus the occurrence's local date instead, which is exactly what
the per-occurrence URL encodes (`/event/king-farmers-market-3/2026-07-26/`).

Other things live data forced:

- `venue` arrives as an empty **list** rather than null when unset, as does `organizer`.
- The feed mixes the markets with the musicians booked into them, and both carry the
  market's name as their taxonomy term, so the category cannot separate them. A market
  occurrence is titled exactly after its venue, which is what we test — a sixth market
  appearing upstream then classifies itself.
- `per_page` is silently clamped to 50, and `utc_start_date` is read in preference to
  the offset-free local pair, since the season straddles both DST boundaries.
- Four of five venues are geocoded upstream; Shemanski Park is not, and is the only
  entry in `venues.json`.

### Hollywood Farmers Market

One market on NE Hancock, publishing three different kinds of thing: `/music-schedule`
(the musicians it books), `/event-schedule` (Strawberry Day, Hollyween), and the market
itself — which appears nowhere as a dated listing and exists only as a sentence of prose
on the homepage.

Those hours are **encoded as data in `config.py`, not parsed**, because misreading that
sentence would publish a market that is not open, which is worse than publishing
nothing. Encoding can go stale, so the fetch reads the sentence back on every run and
expansion is skipped entirely if it no longer matches. The dated listings still publish
in that case. `market_rules_skipped` in the run log is the tripwire.

Squarespace, whose robots.txt disallows `?format=json` and `?format=ical` — both of the
usual shortcuts. The ordinary HTML collection pages are permitted and fully
server-rendered, so that is what we read. Two details in that markup are quiet killers:
the clock text separates minutes from meridiem with **U+202F**, so `"10:00 AM"` is not
the string it looks like and any `%I:%M %p` parse of it fails; and a multiday item
carries **two** `time.event-date` elements, so taking the last match dates National
Farmers Market Week to the end of its run rather than the start.

Music gets `Price.free()` and the market's coordinates. Special events get neither, and
that is evidence-based: their detail pages carry a schema.org `Event` with an empty
`location` and a null `offers`, and the collection mixes on-site days with off-site
benefit nights at a bar. A guess either way is a wrong pin or a wrong price.

### PDX Parent — the neighbourhood markets

One page listing every farmers market in the metro by day of week. It is the only
inventory of Montavilla, Woodstock, Woodlawn, Cully, St Johns, Sellwood, Rocky Butte and
People's that exists in machine-readable reach; without it none of them are in the feed.

The price of that reach is that every schedule is a sentence, so `schedule.py` parses
prose and is built for precision — anything it cannot read with confidence yields
nothing for that clause plus a recorded reason. Three rules, each of which was silently
wrong first:

- **A bare number after a month is a day only if it is not part of a year.**
  "June-September 2026" was parsing as June through September *20th*, quietly
  shortening six markets' seasons by ten days.
- **Semicolons separate alternate schedules**, and a clause with no weekday inherits the
  previous one — which is what lets Beaverton's winter and summer hours both survive.
- **A vague phrase only voids a rule when it comes before the hours.** "Every other
  Sunday" as the subject is unusable, but Hillsdale's "9 am-1 pm. Open select dates
  twice monthly in winter" has a good primary rule an earlier version threw away.

Two things are refused rather than guessed. A follow-on clause naming a venue is the
market *relocating* for the season — Woodlawn's winter market is "December-May at
Classic Foods, 817 NE Madrona St" — and since the roundup gives one address per market
those dates would carry the wrong pin, so they are dropped. And markets whose operator
publishes a real calendar are skipped entirely, matched on the link the roundup itself
provides, so the Portland Farmers Market and Hollywood entries defer to the
authoritative sources with no hand-maintained list here.

Coordinates were geocoded once against Nominatim **and verified to be in the expected
city**. That check is not ceremony: an unverified pass looked entirely successful and
had put the Hillsboro Tuesday Marketplace on a Main Street in Portland, twenty-five
miles from the market. 328 of 450 events carry a pin; the rest publish without one
rather than with a plausible wrong one.

Ids are a slug of the market name plus the date. ASCII folding deletes a curly
apostrophe but keeps a straight one, so "Camas Farmer's Market" slugged two different
ways depending on which quote character was typed; apostrophes are stripped before
slugging so both forms agree.

`dropped_unparseable_schedule` is 0 today. A jump means the roundup has been reworded
into a form the parser does not read, and those markets are being withheld.

### Oregon Ballet Theatre — and Tessitura generally

OBT sells through **Tessitura's TNEW** web sales module at `my.obt.org`, and TNEW
backs its listing with an unauthenticated JSON endpoint:

```
POST https://my.obt.org/api/products/productionseasons
{"startDate": "...", "endDate": "...", "productionSeasonIdFilter": [], "keywordIds": null}
```

That returns every production and every individual performance with an explicit UTC
offset. It is a far better surface than the marketing site, whose season page gives
only date ranges for a whole run ("December 5 - 24, 2026") and carries no `Event`
JSON-LD.

**This generalizes.** A `my.<org>.org` subdomain is a strong tell for TNEW, and much
of Portland's performing-arts sector runs it — Portland Opera, Oregon Symphony,
Portland Center Stage, White Bird. `sources/obt/tessitura.py` deliberately knows
nothing about ballet: it takes a base URL and a date window. Adding a sibling should
be a new `config.py` and a venue table, not a new parser. Confirm TNEW first by
checking robots.txt for `/_syos/` and `/Flash_Bridge_Service/`, and the page source
for a `tnew.app.init({...})` call carrying the TNEW version.

Three findings that shaped the implementation:

- **The HTML pages are off limits.** `my.obt.org` sits behind Imperva Incapsula.
  The JSON API is unmetered, but the server-rendered pages at
  `/{productionSeasonId}/{performanceId}` serve exactly **five** real responses and
  then return a "Pardon Our Interruption" interstitial *with HTTP 200* — measured
  repeatedly, and unchanged by a cookie jar or by pacing requests two seconds apart.
  It is a ticket-bot control on a ticketing site and is not something to work around.
  Those pages are the only place TNEW publishes a **venue or a price**, so venues come
  from the marketing site instead and price is honestly `unknown`. (For the record,
  the detail pages priced the current Nutcracker run at $39–$168 all-in.)
- **One event per performance, not per production.** Eighteen Nutcrackers over three
  weeks become eighteen events. A production is not a thing anyone can attend, and the
  app answers "what is on tonight". This is only safe because Tessitura gives every
  performance its own immutable integer key, so `obt:830` is stable without involving
  the title or the date.
- **Every timestamp arrives twice**, once local-with-offset and once UTC. They are
  cross-checked and a performance whose two forms disagree is dropped rather than
  guessed at, which turns the whole class of "shipped seven hours off" bug into a
  visible counter.

Venue names come from one request to `www.obt.org`, whose robots.txt allows everything
with `Crawl-delay: 10` that we honor. The season page URL rotates yearly
(`/2026-27-season/`), so it is discovered from the season-agnostic index rather than
hardcoded. If that lookup fails, events publish without a venue rather than not at all.

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

It fired zero times when the feed was just Ticketmaster and Calagator — touring acts
against tech meetups. Adding Eventbrite and DoPDX, which both list independent venue
programming, took a measured run to 159 collapses.

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
