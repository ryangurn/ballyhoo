"""Hollywood Farmers Market source configuration.

A single neighborhood market on NE Hancock, running Saturdays year-round. It publishes
three different kinds of thing, and this source reads all three:

* `/music-schedule` — the musicians booked into the market, one dated page each.
* `/event-schedule` — special days: Strawberry Day, Hollyween, the Harvest Festival.
* the market itself, which appears nowhere as a dated listing and exists only as a
  sentence of prose on the homepage.

That last one is the hard part and is handled by `common.recurrence`.

The site is Squarespace. Its robots.txt disallows `?format=json` and `?format=ical`,
which rules out the two shortcuts you would normally reach for on a Squarespace site,
so this source reads the ordinary HTML collection pages instead — those are permitted
and are fully server-rendered.
"""

from __future__ import annotations

from datetime import time, timedelta

from ...common.models import Source
from ...common.recurrence import MonthDay, Season, WeeklyRule

SOURCE = Source(
    id="hollywood_farmers_market",
    name="Hollywood Farmers Market",
    url="https://www.hollywoodfarmersmarket.org",
)

HOME_URL = "https://www.hollywoodfarmersmarket.org/"
# Squarespace collection pages. Both render their items server-side.
LISTING_URLS = {
    "music-schedule": "https://www.hollywoodfarmersmarket.org/music-schedule",
    "event-schedule": "https://www.hollywoodfarmersmarket.org/event-schedule",
}

SATURDAY = 5

# The homepage states, verbatim:
#
#     MARKET HOURS April-December 19th : Every Saturday 8am-1pm
#     January-March: 2nd and 4th Saturdays 9am-1pm
#
# Encoded here as data because prose is a bad thing to parse and a worse thing to
# parse wrong — a misread would publish a market that is not open. `fetch` reads that
# sentence back on every run and `normalize` refuses to expand the rules if it has
# changed, so the encoding cannot drift silently. Ordered most specific first, which
# is what `expand` uses to resolve a date claimed by two rules.
MARKET_RULES = [
    WeeklyRule(
        weekday=SATURDAY,
        start_time=time(9, 0),
        end_time=time(13, 0),
        season=Season(MonthDay(1, 1), MonthDay(3, 31)),
        ordinals=frozenset({2, 4}),
    ),
    WeeklyRule(
        weekday=SATURDAY,
        start_time=time(8, 0),
        end_time=time(13, 0),
        season=Season(MonthDay(4, 1), MonthDay(12, 19)),
    ),
]

# Normalized (whitespace-collapsed, case-folded) form of the sentence above. The
# tripwire for the rules going stale.
EXPECTED_HOURS_TEXT = "april-december 19th : every saturday 8am-1pm january-march: 2nd and 4th saturdays 9am-1pm"

# How far ahead to expand the market rules. Deliberately shorter than the 365 days the
# calendar-backed sources use: these dates are inferred from a rule rather than read
# from a published calendar, and confidence in them decays with distance — a market
# can change its hours, skip a holiday, or close its season early without warning.
# 120 days is about seventeen Saturdays, which fills the app without inventing a year
# of events nobody has confirmed.
MARKET_EXPANSION_WINDOW = timedelta(days=120)

# Dated listings are read as published, so they get the usual horizon.
FETCH_WINDOW = timedelta(days=365)

MARKET_TITLE = "Hollywood Farmers Market"
VENUE_NAME = "Hollywood Farmers Market"
VENUE_ADDRESS = "NE Hancock St between NE 44th and NE 45th Ave, Portland, OR 97213"

REQUEST_TIMEOUT_SECONDS = 25
MAX_RETRIES = 3
SECONDS_BETWEEN_PAGES = 0.75

USER_AGENT = "ballyhoo-pipeline/0.1 (+https://github.com/ryangurn/ballyhoo)"

TIMEZONE = "America/Los_Angeles"
