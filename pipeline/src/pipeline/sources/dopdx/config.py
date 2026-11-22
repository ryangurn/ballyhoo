"""DoPDX source configuration.

DoPDX (dopdx.com) is the Portland edition of the DoStuff Media network of city
event guides. Since the site's move to DoStuff's SvelteKit platform ("doxyz") the
old `*.json` day API is gone; the site now hydrates its own frontend from
`<path>/__data.json` endpoints — day listings and per-event detail pages, the
latter still carrying venue coordinates and a free/paid flag, which keeps this the
richest source available after Ticketmaster.

Access is scoped by their robots.txt, which disallows `/locales`, `/features`,
and any `view=map`. Only `/events` is used here.
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
# Dates live in the path: /events/2026/8/15/__data.json, paginated with ?page=N.
LISTING_PATH = "/events/{year}/{month}/{day}/__data.json"
# Detail pages are the listing permalink + the same suffix.
DETAIL_SUFFIX = "/__data.json"

# The listing serves one calendar day per request, and Portland runs 15-76 events
# a day, so the window is a direct multiplier on both runtime and feed size. Thirty
# days is roughly 1,400 unique events — about 100 listing requests plus one detail
# request per event, which fits comfortably in an hourly run.
FETCH_WINDOW = timedelta(days=30)

PAGE_SIZE = 50
MAX_PAGES_PER_DAY = 6

REQUEST_TIMEOUT_SECONDS = 25
MAX_RETRIES = 3
# One request every 300ms. This is a small commercial publisher, not a CDN-backed
# platform; the pacing keeps a ~1,500-request run near fifteen minutes.
SECONDS_BETWEEN_REQUESTS = 0.3

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
