"""DoPDX source configuration.

DoPDX (dopdx.com) is the Portland edition of the DoStuff Media network of city
event guides. It exposes a genuine JSON API — versioned, unauthenticated, no bot
protection — with venue coordinates and a free/paid flag, which makes it the richest
source available after Ticketmaster.

Access is scoped by their robots.txt, which disallows `/features`, `/search`,
`/latest`, `/locales`, `/assets/` and any `view=map`. Only `/events` is used here.
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
# Dates live in the path: /events/2026/8/15.json, paginated with ?page=N.
EVENTS_PATH = "/events/{year}/{month}/{day}.json"

# The API serves one calendar day per request, and Portland runs 15-76 events a day,
# so the window is a direct multiplier on both runtime and feed size. Thirty days is
# roughly 1,400 events for about 60 requests, which fits comfortably in an hourly run.
FETCH_WINDOW = timedelta(days=30)

PAGE_SIZE = 25
MAX_PAGES_PER_DAY = 6

REQUEST_TIMEOUT_SECONDS = 25
MAX_RETRIES = 3
# One request every 400ms. This is a small commercial publisher, not a CDN-backed
# platform, and a full run is already ~60 requests.
SECONDS_BETWEEN_REQUESTS = 0.4


# Images come from Cloudinary, which resizes on request. Asking for the size we
# actually render avoids the mistake made with Ticketmaster, where full-resolution
# artwork decoded to ~13 MB apiece and exhausted the app's memory.
CLOUDINARY_TRANSFORM = "w_1136,c_fill,q_auto,f_auto"

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
