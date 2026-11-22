"""DoPDX source configuration.

DoPDX (dopdx.com) is the Portland edition of the DoStuff Media network of city
event guides. In November 2026 the site was rebuilt as a SvelteKit app and the old
`/events/YYYY/M/D.json` API was removed. Every page now has a `__data.json` twin
that returns what the page renders: the day listing carries titles, times, category,
image and venue name, and each event's own page adds the description, price, free
flag, organizer and venue coordinates.

Access is scoped by their robots.txt, which disallows `/locales`, `/features` and any
`view=map`. Only `/events` is used here.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.http import USER_AGENT
from ...common.models import Source

SOURCE = Source(
    id="dopdx",
    name="DoPDX",
    url="https://dopdx.com",
)

BASE_URL = "https://dopdx.com"
# One calendar day per listing, paginated with ?page=N.
DAY_PATH = "/events/{year}/{month}/{day}/__data.json"
# An event's own page is its permalink, e.g. /events/2026/11/22/some-show-tickets.
DETAIL_SUFFIX = "/__data.json"

# Portland runs up to ~190 listings a day, and multi-day runs repeat on every day they
# cover. Thirty days measured 1,481 distinct events across 97 listing requests.
FETCH_WINDOW = timedelta(days=30)

# The site caps page_size at 50 and defaults to 20; asking for the cap cuts the
# listing walk from ~300 requests to ~100.
PAGE_SIZE = 50
MAX_PAGES_PER_DAY = 8

# Event pages are fetched once and cached between runs (see the workflow's cache
# step), because fetching all ~1,500 every run would take ~15 minutes and put ~25x
# the listing load on a small publisher. Each run fetches new events first, then
# refreshes the oldest cached ones, up to the budget. A cold cache therefore takes
# about three runs to fill; until then the remaining events ship from listing data.
MAX_DETAIL_REQUESTS = 500
DETAIL_REFRESH_AFTER = timedelta(days=2)

REQUEST_TIMEOUT_SECONDS = 25
MAX_RETRIES = 3
# One request every 400ms. This is a small commercial publisher, not a CDN-backed
# platform, and a full run is up to ~600 requests.
SECONDS_BETWEEN_REQUESTS = 0.4

# The listing's `image_url` is the 1200x450 cover crop, which is already card-sized.
# Their Cloudinary host now refuses on-the-fly transforms (403), so the old
# pre-sizing trick no longer applies; sized crops are what keep this source from
# repeating Ticketmaster's full-resolution memory exhaustion.

# DoPDX covers the wider Pacific Northwest, not just Portland. A single sampled day
# carried venues in Seattle, Bend, George (the Gorge amphitheatre) and Forest Grove,
# and the category vocabulary even includes "Eugene". Those do not belong in a
# Portland feed, so events are filtered by where they actually are.
#
# Coordinates are authoritative when present. 40 miles is wider than Ticketmaster's
# 25 because DoPDX legitimately covers the metro's edges — Forest Grove, Troutdale,
# Oregon City — while still excluding Seattle (~145 mi) and Bend (~130 mi).
PORTLAND_LATITUDE = 45.5152
PORTLAND_LONGITUDE = -122.6784
MAX_DISTANCE_MILES = 40

# DoPDX's own neighbourhood areas. "Eugene" is listed beside Portland's areas, so an
# event in it is out of the metro even when its venue has no coordinates.
NON_METRO_AREAS = frozenset({"eugene"})

# Used only when an event has no coordinates, where distance cannot be checked.
# Deliberately a blocklist rather than an allowlist: an unrecognised city is far more
# likely to be a Portland neighbourhood or a typo than a distant metro.
NON_METRO_CITIES = frozenset(
    {
        "seattle", "tacoma", "spokane", "bellingham", "olympia", "everett",
        "eugene", "bend", "salem", "corvallis", "medford", "ashland", "astoria",
        "george", "redmond", "boise", "san francisco", "los angeles", "vancouver bc",
    }
)

# Shared project identity; see pipeline/common/http.py for why it omits a URL scheme.
__all__ = ["SOURCE", "USER_AGENT"]
