"""Portland Parks & Recreation — Summer Free For All.

Free movies, concerts and festivals in neighbourhood parks. This is the closest
thing yet to the programming the app exists to surface: no ticket, walkable, spread
across the city rather than concentrated downtown.

The schedule is a hand-maintained HTML table on a single page. That makes it easy to
read and easy to break — a column reorder upstream would silently change meaning —
so the parser validates the header row before trusting the columns.

It is also seasonal. Outside summer the table may be absent or hold only past dates,
which is a normal empty result rather than a failure.
"""

from __future__ import annotations

from ...common.http import USER_AGENT
from ...common.models import Source

SOURCE = Source(
    id="portland_parks",
    name="Portland Parks & Recreation",
    url="https://www.portland.gov/parks",
)

EVENTS_URL = "https://www.portland.gov/parks/arts-culture/summer-free-all/cultural-events"

# The table's own column order, checked against the live header before parsing.
EXPECTED_HEADERS = ("date/time", "type of event", "cultural event", "location")

# Cells give a month and day but no year; the page states it in a nearby heading.
YEAR_HEADING = r"(20\d{2})\s+Schedule of Events"

TIMEZONE = "America/Los_Angeles"

REQUEST_TIMEOUT_SECONDS = 25
MAX_RETRIES = 3

# Shared project identity; see pipeline/common/http.py for why it omits a URL scheme.
__all__ = ["SOURCE", "USER_AGENT"]
