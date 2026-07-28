"""Oregon Ballet Theatre source configuration.

OBT sells tickets through Tessitura's TNEW web sales module at `my.obt.org`. TNEW
backs its event listing with an unauthenticated JSON endpoint, so this source reads
structured data rather than scraping markup. See `tessitura.py` for the endpoint and
why the surrounding HTML is not read.

Two hosts are involved, and they behave very differently:

  my.obt.org   Tessitura TNEW behind an Imperva/Incapsula WAF. The JSON API is
               unmetered, but the HTML pages hard-block after five views. No
               crawl-delay in robots.txt; the API path is not disallowed.
  www.obt.org  WordPress. robots.txt allows everything with `Crawl-delay: 10`,
               which we honor. Consulted once per run for venue names, which
               Tessitura does not expose anywhere in its API.
"""

from __future__ import annotations

from datetime import timedelta

from ...common.http import USER_AGENT
from ...common.models import Source

SOURCE = Source(
    id="obt",
    name="Oregon Ballet Theatre",
    url="https://www.obt.org",
)

# Tessitura TNEW instance. Every org running TNEW exposes the same API under its own
# hostname, so this one constant is most of what a sibling source would change.
TNEW_BASE_URL = "https://my.obt.org"

# The listing page's own JS asks for 18 months. Matching it means we see exactly what
# a visitor to my.obt.org/events sees, rather than a window of our own invention that
# might quietly include or exclude a production.
FETCH_WINDOW = timedelta(days=548)

WWW_BASE_URL = "https://www.obt.org"

# Season-agnostic landing page. The season page itself lives at a URL that rotates
# every year (`/2026-27-season/`, and `/2025-26-season/` still exists alongside it),
# so we follow the link from here rather than hardcoding a URL that expires each
# summer.
SEASON_INDEX_URL = f"{WWW_BASE_URL}/ballet-performances-in-portland/"

# WordPress serves OBT's production artwork. The media API is the only way to learn
# what downscaled renditions exist for a given upload; see fetch.fetch_image_renditions.
WP_MEDIA_ENDPOINT = f"{WWW_BASE_URL}/wp-json/wp/v2/media"

# Matches the Ticketmaster source. Larger artwork is indistinguishable at the size a
# card renders and costs real memory on device once decoded.
MIN_IMAGE_WIDTH = 1100

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3

# www.obt.org's robots.txt asks for `Crawl-delay: 10`. We make at most three requests
# to that host per run, so honoring it costs about twenty seconds.
WWW_CRAWL_DELAY_SECONDS = 10.0

DISPLAY_TIMEZONE = "America/Los_Angeles"

__all__ = ["SOURCE", "USER_AGENT"]
