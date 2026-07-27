"""Eventbrite source configuration.

Eventbrite is the largest single pool of Portland events by a wide margin — roughly
3,400 upcoming at any time against Ticketmaster's ~700 — and unusually for this feed
it states free-ness per event rather than leaving us to infer it.

**How we read it, and what we ruled out.** The documented public search API was
discontinued in 2019, so that route does not exist. The discovery page at
`/d/or--portland/events/` is a React city-landing template whose `window.__SERVER_DATA__`
carries shelves and metadata but an *empty* `search_data` — no events at all. Only the
filtered variants (`/d/or--portland/free--events/`) render the search template with
results embedded, which would give free events but no paid ones.

What we use instead is the endpoint the discovery UI itself calls:
`POST /api/v3/destination/search/`. Eventbrite's robots.txt disallows the sibling
`/api/v3/destination/events/` and `/api/v3/promoted/events`, but `/api/v3/destination/
search/` is *not* disallowed — only its `log_requests/` subpath is. So this is the
permitted door, and it is a far better one: clean paginated JSON, a `price` filter, and
per-event `ticket_availability` carrying an explicit `is_free` boolean and ticket price
bounds. No browser impersonation is needed; there is no Cloudflare challenge here.

**It is CSRF-guarded, not authenticated.** The endpoint rejects a bare POST with
`ACCESS_DENIED`. It needs three things together, all obtainable anonymously: a
`Referer` on eventbrite.com, the `csrftoken` cookie handed out by any page load, and
that same token echoed in an `X-CSRFToken` header. `fetch.py` bootstraps by GETting the
discovery page once. No account, no key, no secret.

**Fragility.** This is the site's own front-end contract, not a published API, so it
can change without notice. The failure is loud: a shape change means page one raises
and the run fails rather than publishing a gutted feed.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.http import USER_AGENT
from ...common.models import Source

SOURCE = Source(
    id="eventbrite",
    name="Eventbrite",
    url="https://www.eventbrite.com",
)

# The search endpoint the discovery UI calls. Permitted by robots.txt; the adjacent
# `/api/v3/destination/events/` is not, and is deliberately never touched.
SEARCH_URL = "https://www.eventbrite.com/api/v3/destination/search/"

# GET once to collect the `csrftoken` cookie, and sent as the Referer on every POST.
# Both are required — the endpoint 401s without either.
DISCOVERY_URL = "https://www.eventbrite.com/d/or--portland/events/"

# Eventbrite's internal locality id for Portland, Oregon, read from the `places`
# filter the discovery page echoes back for the `or--portland` slug. Sent explicitly
# so a slug rename cannot silently redirect the search somewhere else.
PORTLAND_PLACE_ID = "101715829"

# Which `ticket_availability` and venue detail to inflate on each result. Without this
# expansion the records come back with no price information whatsoever, which would
# leave every event price-unknown and lose the one thing Eventbrite does better than
# most sources.
EXPAND_FIELDS = (
    "primary_venue",
    "image",
    "ticket_availability",
    "event_sales_status",
    "primary_organizer",
)

# Two passes, deduplicated by event id. Neither is a superset of the other: measured
# over one week, the unfiltered pass missed 11 events the free filter returned, and the
# free filter missed 6 the unfiltered pass returned. Relevance ranking, not date order,
# decides what falls inside the result ceiling below, and the two rankings differ.
PRICE_FILTERS: tuple[str | None, ...] = (None, "free")

# Measured, not documented: `page_size` is silently clamped to 50 — asking for 100 or
# 200 returns 50 — and results stop at 1,000 per query however they are paged. Page 51
# at size 20 comes back empty, page 20 at size 50 is the last full one. Fifty per
# request is therefore the cheapest way to reach the ceiling.
PAGE_SIZE = 50
RESULT_CEILING = 1000
MAX_PAGES_PER_WINDOW = RESULT_CEILING // PAGE_SIZE

# The ceiling is per query, so the window is sliced and each slice queried separately.
# A Portland week holds 300-850 events, comfortably under 1,000, while a whole month in
# one query would be truncated to its top 1,000 by relevance and silently lose the rest.
FETCH_WINDOW = timedelta(days=30)
WINDOW_STRIDE = timedelta(days=7)

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
# A full run is ~90 requests against a platform CDN. Half a second keeps it unhurried
# without stretching the job past a couple of minutes.
SECONDS_BETWEEN_REQUESTS = 0.5

# Image renditions, best first. Eventbrite serves images through a signed imgix CDN:
# every rendition URL carries an `s=` signature, and editing the `w=` parameter to ask
# for an arbitrary width returns HTTP 403 `sig_`. So we cannot request the ~1136px the
# cards actually draw — we pick the nearest pre-signed size instead.
#
# `large` is 1024px wide, which decodes to roughly 3 MB. The `original` rendition is
# 2160-2560px and decodes to 15-20 MB apiece; that is precisely what exhausted the
# app's memory with Ticketmaster artwork, so it is never used. Neither is the bare
# `image.url`, which is unsized and sometimes returns the full-resolution original.
IMAGE_RENDITIONS = ("large", "medium", "small")

# Eventbrite's "Portland" place is generous — sampled results included Newport (91 mi),
# Centralia WA (84 mi), Corvallis and Salem. Coordinates are present on 100% of results,
# so distance settles it. Forty miles matches DoPDX: wide enough for Hillsboro,
# Troutdale and Oregon City, narrow enough to exclude Salem and the coast.
PORTLAND_LATITUDE = 45.5152
PORTLAND_LONGITUDE = -122.6784
MAX_DISTANCE_MILES = 40

# Results carry a local date and time plus an IANA zone, and no offset. The zone is
# authoritative — 1,731 sampled `event_sales_status` local/UTC pairs round-trip through
# it exactly, and an event page's schema.org `startDate` matches what it produces — so
# the offset is resolved rather than guessed.
#
# About 5% of in-metro results declare a *non-Pacific* zone against a Portland address:
# national certification resellers listing "PMP Training in Portland" on Eastern time,
# and outliers as implausible as Asia/Calcutta. Eventbrite renders those in the declared
# zone, so the data is self-consistent but the event cannot be: 9am Eastern at a
# Portland venue is 6am locally. There is no telling whether the clock or the address is
# wrong, so `normalize` drops them rather than shift someone three hours. This mirrors
# the same call made for Ticketmaster's multi-city listings.
EXPECTED_TIMEZONE = "America/Los_Angeles"

# Shared project identity; see pipeline/common/http.py for why it omits a URL scheme.
__all__ = ["SOURCE", "USER_AGENT"]
