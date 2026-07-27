"""A minimal read-only client for Tessitura's TNEW event listing API.

Nothing in this module knows about Oregon Ballet Theatre. It takes a TNEW base URL
and a date window and returns the productions and performances that instance is
advertising. That is deliberate: `my.obt.org` is a stock TNEW deployment, and the
same three-line request works against any other organization running it. Portland
alone has several — Portland Opera, Oregon Symphony, Portland Center Stage and White
Bird are all Tessitura shops — so a sibling source should be a new `config.py`
pointing this at a different hostname, not a new parser. Confirm the hostname really
is TNEW first: the giveaway is robots.txt disallowing `/_syos/` and
`/Flash_Bridge_Service/`, and a `tnew.app.init({...})` call in the page source that
carries the exact TNEW and Tessitura versions.

Two findings worth carrying forward to any such sibling.

The JSON endpoint is the only durable way in. `my.obt.org` sits behind Imperva
Incapsula, and while the API is unmetered, the server-rendered HTML pages under
`/{productionSeasonId}/{performanceId}` serve exactly five real responses and then
return a "Pardon Our Interruption" interstitial with HTTP 200 — measured repeatedly,
and unchanged by a cookie jar or by pacing requests two seconds apart. It is a
ticket-bot control on a ticketing site, which is entirely reasonable of them, and it
is not something to work around. So those pages are off limits, and with them the
only place TNEW publishes a venue or a price.

The listing carries two timestamps per performance and they must agree. See
`Performance.instant`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from ...common.io import parse_datetime
from ...common.log import get_logger

log = get_logger(__name__)

# TNEW formats the window bounds this way in its own request; anything more precise is
# ignored and anything less is rejected.
_WINDOW_FORMAT = "%Y-%m-%dT%H:%M"


class TessituraError(Exception):
    """The TNEW instance did not return a usable listing."""


class TimestampDisagreement(ValueError):
    """A performance's UTC and local timestamps describe different instants."""


@dataclass(frozen=True)
class Performance:
    """One dated showing. `id` is Tessitura's own immutable performance key."""

    id: int
    production_season_id: str
    title: str
    local_raw: str
    utc_raw: str
    product_type: str | None
    ticket_url: str | None
    is_visible: bool
    status_message: str | None

    @property
    def instant(self) -> datetime:
        """The moment this performance starts, cross-checked across both fields.

        TNEW returns `iso8601DateString` in the organization's local time with an
        explicit offset (`2026-12-05T14:00:00.0000000-08:00`, seven fractional digits,
        which `datetime.fromisoformat` accepts but only because it happens to be all
        zeros) and `performanceDate` as the same moment in UTC. Either alone would do.
        Reading both and refusing to guess when they disagree is what makes an offset
        bug loud instead of shipping every event some whole number of hours off.
        """
        local = parse_datetime(self.local_raw)
        utc = parse_datetime(self.utc_raw)
        if abs((local - utc).total_seconds()) > 60:
            raise TimestampDisagreement(
                f"performance {self.id}: local {self.local_raw!r} and UTC {self.utc_raw!r} "
                f"are {abs((local - utc).total_seconds()) / 3600:.1f}h apart"
            )
        return local


@dataclass(frozen=True)
class Production:
    """A production season: a titled run holding one or more performances."""

    id: str
    title: str
    description_html: str | None
    image_url: str | None
    listing_url: str | None
    performances: tuple[Performance, ...]


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def parse_listing(payload: dict[str, Any]) -> list[Production]:
    """Turn a `/api/products/productionseasons` response into productions.

    A production missing its title or its performances is skipped rather than
    half-represented; everything else tolerates absent fields.
    """
    productions: list[Production] = []

    for raw in payload.get("productions") or []:
        if not isinstance(raw, dict):
            continue
        production_id = _text(raw.get("productionSeasonId"))
        title = _text(raw.get("productionTitle"))
        if not production_id or not title:
            continue

        performances: list[Performance] = []
        for item in raw.get("performances") or []:
            if not isinstance(item, dict):
                continue
            performance_id = item.get("id")
            local_raw = _text(item.get("iso8601DateString"))
            utc_raw = _text(item.get("performanceDate"))
            if not isinstance(performance_id, int) or not local_raw or not utc_raw:
                continue
            performances.append(
                Performance(
                    id=performance_id,
                    production_season_id=production_id,
                    title=_text(item.get("performanceTitle")) or title,
                    local_raw=local_raw,
                    utc_raw=utc_raw,
                    product_type=_text(item.get("productTypeName")),
                    ticket_url=_text(item.get("actionUrl")),
                    # Upstream's own "do not display this" flag. Absent means visible.
                    is_visible=item.get("isPerformanceVisible") is not False,
                    status_message=_text(item.get("performanceStatusMessage")),
                )
            )

        if not performances:
            continue

        productions.append(
            Production(
                id=production_id,
                title=title,
                description_html=_text(raw.get("description")),
                image_url=_text(raw.get("listingImageUrl")),
                listing_url=_text(raw.get("productionSeasonActionUrl")),
                performances=tuple(performances),
            )
        )

    return productions


def fetch_listing(
    session: requests.Session,
    *,
    base_url: str,
    start: datetime,
    end: datetime,
    user_agent: str,
    timeout: float,
    max_retries: int,
) -> list[Production]:
    """POST the listing window and parse the response."""
    endpoint = f"{base_url.rstrip('/')}/api/products/productionseasons"
    body = {
        "startDate": start.strftime(_WINDOW_FORMAT),
        "endDate": end.strftime(_WINDOW_FORMAT),
        # Both are required. Empty and null respectively mean "no filtering", which is
        # what the public listing page itself sends.
        "productionSeasonIdFilter": [],
        "keywordIds": None,
    }

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = session.post(
                endpoint,
                json=body,
                headers={"User-Agent": user_agent, "Accept": "application/json"},
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(2**attempt)
            continue

        if not isinstance(payload, dict):
            raise TessituraError(f"{endpoint} returned {type(payload).__name__}, expected an object")
        return parse_listing(payload)

    raise TessituraError(f"could not read {endpoint}: {last_error}")
