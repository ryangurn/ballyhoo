"""Eventbrite free-events source configuration.

Eventbrite's discovery page for Portland filtered to free events. The filter is the
whole point: free-ness is asserted by the upstream rather than inferred by us, which
is the same standard the rest of the feed is held to.

**What we read, and why it is not the obvious thing.** Eventbrite's public search API
was discontinued in 2019, and the modern discovery page is a React app whose results
arrive from `/api/v3/destination/events/`. That path is explicitly disallowed in
Eventbrite's robots.txt, so we do not call it. What we read instead is the HTML page
at `/d/or--portland/free--events/`, which robots.txt permits, and which is not the
empty React shell it is often assumed to be — the server embeds the entire result set
in a `window.__SERVER_DATA__` blob before hydration. We take the data the server
already chose to send us on a path it allows, and never touch the API behind it.

Plain `requests` with an honest User-Agent is enough here. There is no Cloudflare
challenge on this path and no browser impersonation is involved.

**Fragility.** `__SERVER_DATA__` is an internal of their page rather than a published
interface, and a move to streaming SSR or a renamed global would end this source
overnight. That failure is loud by construction: the blob is missing, page one raises,
and the run fails rather than publishing an empty feed.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.models import Source

SOURCE = Source(
    id="eventbrite_free",
    name="Eventbrite",
    url="https://www.eventbrite.com",
)

# `/d/<place>/<filter>/`. The `free--events` segment is what makes Price.free()
# defensible; `normalize` refuses to claim free if a page stops echoing it back.
SEARCH_URL = "https://www.eventbrite.com/d/or--portland/free--events/"

# The marker the results are embedded behind.
SERVER_DATA_MARKER = "window.__SERVER_DATA__ = "

# The value `search_data.event_search.price` must hold for a page's events to be
# treated as free. Anything else means the filter did not apply.
REQUIRED_PRICE_FILTER = "free"

# The Portland locality id the `or--portland` slug resolves to. Checked per page so a
# redirect to Eventbrite's default location (New York) cannot quietly fill the feed
# with events 2,900 miles away.
EXPECTED_PLACE_ID = "101715829"

# 20 results per page, fixed by the page rather than by us.
PAGE_SIZE = 20

# `pagination.page_count` claims 46 and `object_count` claims ~910, but both are
# Elasticsearch estimates: pages past the mid-thirties come back HTTP 200 with an
# empty result list. The crawl stops on the first empty page and this is only a guard
# against that behaviour changing into an unbounded loop.
MAX_PAGES = 50

# Eventbrite lists a handful of events years out. A year of horizon is what the other
# sources use and keeps a 2029 placeholder from sitting at the bottom of the feed.
FETCH_WINDOW = timedelta(days=365)

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
# Each page is roughly 750KB of HTML. Pace the crawl.
SECONDS_BETWEEN_PAGES = 0.75

USER_AGENT = "sociallist-pipeline/0.1 (+https://github.com/ryangurn/sociallist)"

# Every record carries its own IANA zone, which for this search is always Portland's.
# We use the per-event value and fall back to this only if it is missing.
DEFAULT_TIMEZONE = "America/Los_Angeles"
