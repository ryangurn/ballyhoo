"""Neighborhood farmers markets source configuration.

The markets in `markets.py` publish no calendar at all — no Events Calendar route, no
dated Squarespace collection, no public Google Calendar. Each states its schedule as a
sentence on its own website, and that is all there is to read.

This source applies the Hollywood Farmers Market approach to all of them at once. The
schedule is **encoded** in `markets.py` rather than parsed, because a misread sentence
publishes a market that is not open. Each market carries the exact sentences its rules
were derived from, and every run re-reads them from the market's own page: if any is
gone, that market's days are withheld until someone re-reads the page and updates the
entry. The comparison ignores case, whitespace, and the quote and dash styles a site
builder may swap, so it fires on a changed schedule rather than on re-rendered markup.

The sentences replace what the PDX Parent roundup used to provide, read from each
operator directly. Every page fetched here is permitted by its site's `robots.txt` and
answered the pipeline's user agent without a bot challenge when the entry was written.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.models import Source

SOURCE = Source(id="neighborhood_markets", name="Neighborhood Farmers Markets")

# The same bounded horizon the other rule-derived sources use: these dates are inferred
# from a sentence, and confidence in them decays with distance.
EXPANSION_WINDOW = timedelta(days=120)

# A single market cannot legitimately produce more than this inside the window.
MAX_OCCURRENCES_PER_MARKET = 40

REQUEST_TIMEOUT_SECONDS = 25
MAX_RETRIES = 3
# Most pages are on different hosts, so this is courtesy rather than a rate limit.
SECONDS_BETWEEN_PAGES = 0.5

TIMEZONE = "America/Los_Angeles"
