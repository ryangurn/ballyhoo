"""Calagator source configuration.

Calagator is Portland's community tech calendar (calagator.org). Open JSON, no auth,
no rate limit documented. Volume is small — tens of events, not hundreds.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.models import Source

SOURCE = Source(
    id="calagator",
    name="Calagator",
    url="https://calagator.org",
)

EVENTS_URL = "https://calagator.org/events.json"

# Matches the Ticketmaster window so the merged feed has a consistent horizon.
# Calagator returns 28 events unfiltered vs 44 across a year, so the date range
# meaningfully increases coverage rather than just extending an already-full list.
FETCH_WINDOW = timedelta(days=365)

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
