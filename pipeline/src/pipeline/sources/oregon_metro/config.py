"""Oregon Metro source configuration.

Metro is the regional government for the Portland urban area. Its calendar carries
council meetings alongside genuinely public programming — nature walks at the regional
parks, cemetery tending, life jacket giveaways.

The events page is server-rendered Drupal, so plain HTML parsing works. That makes
Metro the only civic source of the several surveyed that needs neither a headless
browser nor a bot-protection workaround.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.http import USER_AGENT
from ...common.models import Source

SOURCE = Source(
    id="oregon_metro",
    name="Oregon Metro",
    url="https://www.oregonmetro.gov",
)

EVENTS_URL = "https://www.oregonmetro.gov/events"

# 12 events per page, ~11 pages at the time of writing. The cap is a guard against a
# pagination change turning into an unbounded crawl, not a expected limit.
MAX_PAGES = 25
PAGE_SIZE_HINT = 12

# Events far enough out to be worth ignoring; matches the other sources' horizon.
FETCH_WINDOW = timedelta(days=365)

REQUEST_TIMEOUT_SECONDS = 25
MAX_RETRIES = 3
# Metro is a small public agency, not a CDN-backed API. Crawl gently.
SECONDS_BETWEEN_PAGES = 0.75


# The `datetime` attribute carries no offset but is UTC: 2026-07-25T18:00:00 renders
# on the page as "11 a.m.", and Portland was UTC-7 that day. Verified across samples.
SOURCE_TIMEZONE = "UTC"
DISPLAY_TIMEZONE = "America/Los_Angeles"

# Shared project identity; see pipeline/common/http.py for why it omits a URL scheme.
__all__ = ["SOURCE", "USER_AGENT"]
