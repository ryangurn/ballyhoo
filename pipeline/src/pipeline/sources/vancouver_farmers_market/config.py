"""Vancouver Farmers Market source configuration.

The nonprofit runs two markets across the river in Vancouver, WA: the downtown market
at Esther Short Park, weekends spring through fall and Saturdays through the winter,
and the East Vancouver market at Columbia Tech Center, Thursdays in summer. It also
runs a holiday market at the Hilton and books musicians into the downtown market.

The site is WordPress with The Events Calendar, read through the shared client in
`common.tribe_events`. `robots.txt` disallows only `/wp-admin/`.

Unlike Portland Farmers Market, each market day here is its own post with its own slug
(`downtown-vancouver-farmers-market-72`, `-73`, ...) rather than one occurrence of a
recurring series, so the slug-plus-date key is unique without the date — and stays
stable if the operator ever switches to a recurring series.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.models import Source

SOURCE = Source(
    id="vancouver_farmers_market",
    name="Vancouver Farmers Market",
    url="https://vancouverfarmersmarket.org",
)

EVENTS_ENDPOINT = "https://vancouverfarmersmarket.org/wp-json/tribe/events/v1/events"

# The market days themselves. Matched exactly, so a new market added upstream
# publishes as a community listing at the market rather than being dropped.
MARKET_TITLES = frozenset({"Downtown Vancouver Farmers Market", "East Vancouver Farmers Market"})

# The musicians booked into the markets carry this category; nothing else does.
MUSIC_CATEGORY = "Market Music"

# The winter season is published through March, about six months out.
FETCH_WINDOW = timedelta(days=365)

SECONDS_BETWEEN_PAGES = 0.75

DISPLAY_TIMEZONE = "America/Los_Angeles"
