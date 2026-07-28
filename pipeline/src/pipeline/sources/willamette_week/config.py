"""Willamette Week "Get Busy" calendar, served by the CitySpark platform.

Willamette Week is Portland's alt-weekly. Its events calendar, branded *Get Busy*,
lives at https://www.wweek.com/getbusy/calendar/events/ and is a CitySpark widget:
that page embeds `portal.cityspark.com/PortalScripts/WillametteWeek`, and the widget
reads the endpoint below to populate itself. This source reads the same one.

Naming
------
The source id is `willamette_week` rather than `cityspark`, deliberately. CitySpark is
the vendor, the way Drupal is Oregon Metro's vendor and Arc is wweek.com's — we do not
name sources after their CMS. Willamette Week is the party doing editorial work on this
corpus: their submission page states that "our calendar editor reviews submissions at
the start of every week, approving events that we think appeal to our readership", and
that not every submission is approved. The `ppid` below scopes the query to WW's own
partner id, so what comes back is WW's approved set, not CitySpark's global one.

That said, the attribution is not airtight, and the feed shows it. A handful of events
carry labels belonging to sibling CitySpark partners — `inlanderprint` (the Spokane
Inlander), `SummerGuideEW` (Eugene Weekly), `FGnewsletter` — which means some listings
reach WW's scope through the shared platform rather than through WW's editor. WW is
still the most honest single name for what a reader would recognise, but "curated by
Willamette Week" should be read as "mostly".

Access
------
`portal.cityspark.com/robots.txt` disallows only `/test/` and `/v2/`; `/api/` is
permitted. No browser impersonation is used or needed: the project User-Agent with no
`Origin` and no `Referer` returns a byte-identical response to the browser request.
See `pipeline/common/http.py`.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.http import USER_AGENT
from ...common.models import Source

SOURCE = Source(
    id="willamette_week",
    name="Willamette Week",
    url="https://www.wweek.com/getbusy/calendar/events/",
)

EVENTS_URL = "https://portal.cityspark.com/api/events/GetEvents/WillametteWeek"

# Willamette Week's CitySpark partner id. Every request is scoped to it; dropping it
# would widen the query to whatever CitySpark serves by default.
PARTNER_ID = 9934

# Downtown Portland, the same origin Ticketmaster and DoPDX use.
LATITUDE = 45.515232
LONGITUDE = -122.6783853

# Twenty-five miles, matching Ticketmaster.
#
# Measured over 2,025 live events requested at 35 miles: 98.5% are already inside 25
# (1,152 within 5 mi, 419 at 5-10, 144 at 10-15, 144 at 15-20, 136 at 20-25, and only
# 30 beyond). Twenty-five miles reaches the real edge of the metro — Forest Grove at
# 23.5, Newberg 23.8, Banks 24.6, Dundee 24.8 — while excluding Dayton (28.4),
# Mount Angel (31.5), McMinnville, Estacada and Salem, which are not Portland.
#
# The filter is applied in the request rather than after the fact. Asking for 35 and
# discarding the tail measured 1,250 events per ten days against 1,232 at 25 — a 1.4%
# difference that costs an extra page per window for events we would throw away. The
# normalizer re-checks each event's own `Distance` anyway, so a server-side change to
# how the parameter is honoured cannot silently widen the feed.
#
# Matching Ticketmaster's radius exactly also matters for dedupe: two sources with
# different radii cover the boundary asymmetrically, and a duplicate that only one of
# them carries has nothing to merge against.
RADIUS_MILES = 25

# How far ahead to collect.
#
# Volume rather than the API is the binding constraint here. Measured weekly totals
# from a run on 2026-07-27: 958, 989, 862, 708, 627, 472, 451, 360, 321, 290, 302 —
# about 3,800 events in the first 30 days and 8,424 over 154. Thirty days already makes
# this the largest source in the feed by a wide margin, and the far tail is dominated
# by recurring library and class listings that get rescheduled before they arrive.
# Thirty days also matches DoPDX, so the two largest sources share a horizon.
FETCH_WINDOW = timedelta(days=30)

# The endpoint refuses to paginate past its 2,025th result.
#
# Measured directly: an unbounded query returns 25 events per page and keeps returning
# them through `skip=2000`, then answers `skip=2025` with HTTP 200, `Success: false`
# and `ErrorMessage: "Please refine your search"`. That is a server-side ceiling, not
# the end of the data — the 2,025 events collected spanned just 16 days, while the
# calendar demonstrably holds events five months out.
#
# So the run is sliced into date windows. `start`/`end` genuinely bound the result set,
# and a bounded window terminates cleanly with an empty page instead of the error. A
# seven-day window measured at most 989 events, leaving better than 2x headroom under
# the ceiling. If a window ever does trip it, the fetcher raises rather than publishing
# the truncated prefix — the same posture as Ticketmaster's deep-paging guard, and for
# the same reason: a feed that looks healthy while quietly missing events is the worst
# failure available.
WINDOW_DAYS = 7
RESULT_CEILING = 2025
CEILING_ERROR_MESSAGE = "Please refine your search"

# 25 per page, fixed; `skip` advances by whatever the page actually returned.
PAGE_SIZE = 25
# ~11 pages for the busiest week measured. The cap is a runaway guard, not a limit we
# expect to reach: without it, a response that kept returning rows would loop forever
# against someone else's server.
MAX_PAGES_PER_WINDOW = 40

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
# One request every 500ms. A 30-day run is roughly 50 requests against a platform we
# have no relationship with, so pace it like DoPDX rather than like a CDN.
SECONDS_BETWEEN_REQUESTS = 0.5

# Windows overlap: a request for a single day returns that day and the next, because
# the endpoint bounds on its own local interpretation of the range. Collected events
# are therefore deduplicated on `Id` across windows.
#
# Note `Id` is used only for that in-run deduplication, never as the published event
# id — see `normalize.make_id` for why.

# Events CitySpark marks as virtual. This app is about being somewhere in Portland, and
# a livestream has no venue to show on a map. Measured at 19 of 2,025 (0.9%).
#
# `isVirtual` is the field to trust. The `csRemote` and `csHybrid` labels are broader
# and mean something else: 45 events carry `csRemote` without `isVirtual`, and a
# further 40 carry `csHybrid`, which by definition still has a physical location.
DROP_VIRTUAL = True

# Images come from CitySpark's own blob storage in three fixed renditions, and unlike
# Ticketmaster the platform bounds them itself. Measured over 90 sampled events:
# `SmallImg` tops out at 210 px wide, `MediumImg` at 420, `LargeImg` at 700 (one 840 px
# outlier in a separate sample) — worst case 1.83 MB decoded, median 1.04 MB.
#
# For context, the crash this project already had came from Ticketmaster artwork at up
# to 3200 px and roughly 13 MB decoded apiece. `LargeImg` is a seventh of that and is
# capped upstream, so it is inside the bound `ticketmaster.MIN_IMAGE_WIDTH` exists to
# enforce rather than an exception to it. Medium at 420 px is the safer-looking choice
# and the wrong one: cards render at 230-390 pt, which needs 690-1170 px on a 3x screen,
# so Medium would be visibly soft.
#
# What is worth watching is the cap itself. If CitySpark ever starts serving
# unbounded `.large.` renditions this reasoning expires, and the fallback below would
# not catch it because it only handles a missing image, not an oversized one.
IMAGE_PREFERENCE = ("LargeImg", "MediumImg", "SmallImg")

# Shared project identity; see pipeline/common/http.py for why it omits a URL scheme.
__all__ = ["SOURCE", "USER_AGENT"]
