"""PDX Parent farmers-market roundup source configuration.

PDX Parent publishes one page listing every farmers market in the Portland metro,
organized by day of the week. It is the only inventory of the neighborhood markets —
Montavilla, Woodstock, Woodlawn, Cully, St Johns, Sellwood, Rocky Butte, People's —
that have no machine-readable calendar of their own anywhere. That is precisely the
walkable, free, neighborhood-scale supply this app exists for, and none of it reaches
the feed any other way.

The cost is that every schedule is a sentence of English rather than a date. This
source therefore does two unusual things: it parses prose (see `schedule.py`, which is
deliberately strict and drops what it cannot read with confidence), and it expands the
result into dated occurrences through `common.recurrence`.

Its robots.txt only disallows `/wp-admin/`, so this path is permitted.

**This is a secondary source.** Markets whose own operator publishes a real calendar
are skipped rather than inferred — see `COVERED_ELSEWHERE_DOMAINS`. A guessed date
that contradicts an authoritative one is worse than no date.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.models import Source

SOURCE = Source(
    id="pdxparent_markets",
    name="PDX Parent",
    url="https://pdxparent.com",
)

ROUNDUP_URL = "https://pdxparent.com/farmers-markets-portland-oregon/"

# A market linked to one of these already reaches the feed from its operator's own
# calendar, with real published dates rather than dates inferred from prose. Matching
# on the link the roundup itself provides means a market moving in or out of coverage
# needs no edit here. Covers the five Portland Farmers Market sites and Hollywood.
COVERED_ELSEWHERE_DOMAINS = (
    "portlandfarmersmarket.org",
    "hollywoodfarmersmarket.org",
)

# How far ahead to expand. Short for the same reason Hollywood's is: these dates are
# inferred from a rule in a listicle, at two removes from the market itself, so
# confidence decays fast. 120 days is roughly seventeen occurrences per market.
EXPANSION_WINDOW = timedelta(days=120)

# A single market cannot legitimately produce more than this inside the window. A
# runaway rule hits the ceiling instead of the feed.
MAX_OCCURRENCES_PER_MARKET = 40

REQUEST_TIMEOUT_SECONDS = 25
MAX_RETRIES = 3

USER_AGENT = "ballyhoo-pipeline/0.1 (+https://github.com/ryangurn/ballyhoo)"

TIMEZONE = "America/Los_Angeles"
