"""Oregon City Farmers Market source configuration.

A year-round market: Saturdays May through October, and a winter market on alternate
Saturdays from January to April. It moved to Clackamas Community College (Green Lot
#1) for 2026, and the venue record upstream is already geocoded there.

WordPress with The Events Calendar, read through `common.tribe_events`. Each season is
one recurring series upstream, and this version of the plugin already suffixes every
occurrence's slug with its date (`oregon-city-summer-farmers-market-8-2026-10-10`).

`robots.txt` sets `Crawl-Delay: 10` and disallows the HTML month and list views, but
not `/wp-json/`. A season is well under one page, so in practice this is one request
a run; the delay applies if it ever is not.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.models import Source

SOURCE = Source(
    id="oregon_city_farmers_market",
    name="Oregon City Farmers Market",
    url="https://orcityfarmersmarket.com",
)

EVENTS_ENDPOINT = "https://orcityfarmersmarket.com/wp-json/tribe/events/v1/events"

# Every market day carries this category. Anything else the site posts is not one.
MARKET_CATEGORY = "Market"

FETCH_WINDOW = timedelta(days=365)

# From robots.txt.
SECONDS_BETWEEN_PAGES = 10.0

DISPLAY_TIMEZONE = "America/Los_Angeles"
