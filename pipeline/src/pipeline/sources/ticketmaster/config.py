"""Ticketmaster Discovery API source configuration.

Every default here was derived from measuring live Portland data rather than guessed.
See the tables in `openspec/changes/add-events-aggregation-pipeline/design.md`.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.models import Source

SOURCE = Source(
    id="ticketmaster",
    name="Ticketmaster",
    url="https://www.ticketmaster.com",
)

EVENTS_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
API_KEY_ENV = "TICKETMASTER_API_KEY"

# Downtown Portland. Radius chosen from measurement: 15 mi returns 498 events,
# 25 mi returns 548, 50 mi returns 577, 75 mi returns 585. Past 25 miles the curve
# flattens and the additions are Salem and Vancouver, which are not Portland.
LATITUDE = 45.5152
LONGITUDE = -122.6784
RADIUS_MILES = 25

# Volume by horizon: 30 d -> 227, 90 d -> 548, 180 d -> 673, 365 d -> 723. A full
# year costs only 32% more events than a quarter and captures tours announced early.
FETCH_WINDOW = timedelta(days=365)

# The API refuses to serve past the 1000th result (`size * page < 1000`) and truncates
# silently rather than erroring. Measured volume is ~723, so there is real headroom,
# but silent truncation is the worst failure available here: the feed would look
# healthy while quietly missing events. Abort instead, and reach for date-slicing.
PAGE_SIZE = 200
DEEP_PAGING_LIMIT = 1000
TOTAL_ELEMENTS_GUARD = 900

# No `segmentName` filter is sent. Measured: an unfiltered query returns 548 events
# while an exhaustive six-segment allow-list returns only 503, so any explicit list is
# lossy by construction. If narrowing ever becomes necessary, use readable names here
# rather than opaque segment IDs, which fail silently when mistyped.
SEGMENT_NAMES: tuple[str, ...] = ()

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 4
# Their FAQ says 2 req/s while Getting Started says 5. Pace to the conservative one.
MIN_SECONDS_BETWEEN_REQUESTS = 0.5

# Events in these states are not attendable.
EXCLUDED_STATUS_CODES = frozenset({"cancelled", "canceled"})

# Ticketmaster offers each event at 16:9 in roughly 100, 205, 640, 1024, 1136, 2048,
# 2426, and 2846 px wide. Taking the largest is a trap: a 2426x1365 JPEG decodes to
# about 13 MB in memory, and a feed of 700 of them will kill the app on a real device
# for exceeding its memory limit.
#
# Cards render at roughly 230-390pt, so 1136 px covers even a full-width detail image
# on a 3x screen with room to spare, at about 2.9 MB decoded. Prefer the smallest
# offered image that clears this bar rather than the biggest available.
MIN_IMAGE_WIDTH = 1100

# Ask for that size by rendition name rather than by measuring widths. Ticketmaster
# names every rendition it derives, and RETINA_LANDSCAPE_16_9 is the 1136 px one —
# measured at exactly 1136 on all 718 live Portland events, with no event missing it.
#
# Naming it matters because the `images` array arrives in arbitrary order, not in the
# documented ladder order, so a width comparison tie-breaks on whatever happened to
# come first in that response. It also fails safe: picking by width means a response
# that omitted the 1136 entry would silently promote the choice to the 2048 px
# rendition, or to _SOURCE at up to 3200 px, which is the full-resolution artwork this
# whole bound exists to keep out of the feed.
CANONICAL_IMAGE_RENDITION = "RETINA_LANDSCAPE_16_9"

# `dates.timezone` is absent on roughly 37% of Portland results even though
# `dates.start.localTime` shows the real local hour. Left as UTC, a 7pm show
# serializes as the next day at 02:00Z, so anything bucketing by date string files it
# under the wrong day. Every venue inside a 25-mile radius of downtown Portland is in
# Pacific time — including Vancouver, WA — so this default is safe rather than a guess.
DEFAULT_TIMEZONE = "America/Los_Angeles"
