"""Hillsboro Farmers' Markets source configuration.

One nonprofit runs four markets in Hillsboro, and publishes every market day of all
four, dated, on a single Squarespace events page — including the ones it cancels and
reschedules. That page is the whole source.

The site is the market organization's own, separate from the City of Hillsboro's
parks site that hard-403s at its edge. It is Squarespace, so `robots.txt` disallows
`?format=json` and `?format=ical`; the server-rendered `/events` collection page is
permitted and is what we read, through `common.squarespace`.

Two things on that page need handling rather than passing through:

* **Titles are not names.** Items are titled `"Orenco Station"`,
  `"Hillsboro Farmers Markets - Saturday Downtown"`, `"Harvest Festival - Streets at
  Tanasbourne"`, `"**CANCELLED Aug 5th, 2026 **Reed's Crossing at Tamarack Park"`.
  Each is matched to one of the markets below by a fragment of its title, and
  published under that market's name.
* **The event addresses are wrong for two markets.** Orenco Station and Tanasbourne
  items both carry the organization's office address on NE 61st Ave rather than where
  the market is held, so each market's location comes from its own page instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from ...common.models import Source

SOURCE = Source(
    id="hillsboro_farmers_markets",
    name="Hillsboro Farmers' Markets",
    url="https://hillsboromarkets.org",
)

BASE_URL = "https://hillsboromarkets.org/"
EVENTS_URL = "https://hillsboromarkets.org/events"


@dataclass(frozen=True)
class Market:
    key: str
    title: str
    # Case-folded fragments, any one of which in an item's title identifies the market.
    title_fragments: tuple[str, ...]
    # The venue publishes under `title`, as every market source names its venue, so
    # cross-source dedup can match it; the place itself goes in the address.
    address: str
    page_url: str


MARKETS = (
    Market(
        key="downtown",
        title="Downtown Hillsboro Saturday Farmers' Market",
        title_fragments=("saturday downtown", "downtown saturday"),
        address="150 E Main St, Hillsboro, OR 97123",
        page_url="https://hillsboromarkets.org/downtown",
    ),
    Market(
        key="orenco",
        title="Orenco Station Farmers' Market",
        title_fragments=("orenco",),
        address="6125 NE Cornell Rd, Hillsboro, OR 97124",
        page_url="https://hillsboromarkets.org/orenco",
    ),
    Market(
        key="reeds-crossing",
        title="South Hillsboro Farmers' Market at Reed's Crossing",
        title_fragments=("reed's crossing", "reeds crossing", "tamarack"),
        address="Tamarack Park, 7250 SE Tamarack St, Hillsboro, OR 97123",
        page_url="https://hillsboromarkets.org/reeds-crossing",
    ),
    Market(
        key="tanasbourne",
        title="Streets at Tanasbourne Farmers' Market",
        title_fragments=("tanasbourne",),
        address="The Streets of Tanasbourne, 10050 NW Emma Way, Hillsboro, OR 97124",
        page_url="https://hillsboromarkets.org/the-streets-at-tanasbourne",
    ),
)

# An item whose title contains one of these takes a market day away rather than
# adding one: "**CANCELLED Aug 5th, 2026 **Reed's Crossing...", "HFM Closed - Labor Day".
CLOSURE_MARKERS = ("cancel", "closed")

# "Harvest Festival - Orenco Station" is the market's last day of the season, held as a
# festival. Still the market, and still free.
HARVEST_FESTIVAL_PREFIX = "harvest festival"

FETCH_WINDOW = timedelta(days=365)

REQUEST_TIMEOUT_SECONDS = 25
MAX_RETRIES = 3

TIMEZONE = "America/Los_Angeles"
