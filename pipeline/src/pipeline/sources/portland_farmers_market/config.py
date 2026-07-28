"""Portland Farmers Market source configuration.

PFM is the nonprofit that runs five markets around the city — PSU, King, Shemanski
Park, Lents International, and Kenton. They are the archetype of what this app is
for: free to walk into, neighborhood-scaled, and weekly.

The site runs WordPress with The Events Calendar plus Events Calendar Pro, which
exposes a read-only REST API at `/wp-json/tribe/events/v1/events`. That matters more
than it sounds. Recurring events are the one thing our `Event` model cannot express,
and the plugin already expands a recurring series into one record per occurrence
before we ever see it. So PFM needs no recurrence logic of our own: we read dated
occurrences and pass them through.

`robots.txt` here is a Yoast block with an empty `Disallow:`, which permits
everything, and the REST route is a documented public interface rather than a
private XHR endpoint.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.models import Source

SOURCE = Source(
    id="portland_farmers_market",
    name="Portland Farmers Market",
    url="https://www.portlandfarmersmarket.org",
)

EVENTS_ENDPOINT = "https://www.portlandfarmersmarket.org/wp-json/tribe/events/v1/events"

# The API silently clamps per_page to 50 — asking for 100 still returns 50 — so
# requesting more would just make the page count wrong.
PAGE_SIZE = 50

# ~110 occurrences published at the time of writing, so three pages. The cap only
# exists so a pagination bug upstream cannot turn into an unbounded crawl.
MAX_PAGES = 20

# PFM publishes roughly eight months out (a full market season plus the winter
# markets). A year of horizon takes everything they have without inventing any.
FETCH_WINDOW = timedelta(days=365)

REQUEST_TIMEOUT_SECONDS = 25
MAX_RETRIES = 3
# A small nonprofit's shared WordPress host, not a CDN-backed API. Crawl gently.
SECONDS_BETWEEN_PAGES = 0.75

USER_AGENT = "ballyhoo-pipeline/0.1 (+https://github.com/ryangurn/ballyhoo)"

# Every record carries `utc_start_date`/`utc_end_date` alongside the local pair, so
# we read the UTC fields and convert. Trusting the offset-free local fields would
# mean guessing at the DST boundary, which the season straddles in both directions.
DISPLAY_TIMEZONE = "America/Los_Angeles"
