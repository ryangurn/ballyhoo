"""Fetch Portland Farmers Market occurrences from The Events Calendar REST API.

The interesting part of the response is what the plugin has already done for us. A
market is authored upstream as one recurring series, but the API hands back one
record per date:

    {"id": 10003167, "slug": "king-farmers-market-3",
     "url": ".../event/king-farmers-market-3/2026-07-26/",
     "utc_start_date": "2026-07-26 17:00:00", ...}
    {"id": 10003168, "slug": "king-farmers-market-3",
     "url": ".../event/king-farmers-market-3/2026-08-02/", ...}

Note that `id` differs per occurrence while `slug` is shared. Those numeric ids are
provisional ids synthesized by Events Calendar Pro, not WordPress post ids: real
posts on this site number in the thousands (venues at 6742, one-off events at 31594)
while occurrences sit in a dense sequential block above 10000000. Inserting or
removing one date in a series renumbers every occurrence after it, so they are unfit
to key a bookmark on. `normalize` uses slug plus occurrence date instead, which is
exactly the identity the per-occurrence URL encodes.

Two shape quirks worth knowing: `venue` is a dict when set but an empty *list* when
not, and `organizer` is likewise a list. Both would raise on a naive `.get()`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

from ...common.log import get_logger
from . import config

log = get_logger(__name__)


class FarmersMarketFetchError(Exception):
    """Upstream did not return usable data."""


@dataclass(frozen=True)
class RawVenue:
    name: str
    address: str | None
    city: str | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class RawMarketEvent:
    slug: str
    title: str
    utc_start_raw: str
    utc_end_raw: str | None
    all_day: bool
    url: str
    excerpt_html: str | None
    image_url: str | None
    website: str | None
    categories: tuple[str, ...]
    venue: RawVenue | None


def _as_dict(value: Any) -> dict[str, Any]:
    """The API uses `[]` rather than `null` for an unset object field."""
    return value if isinstance(value, dict) else {}


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_venue(payload: Any) -> RawVenue | None:
    venue = _as_dict(payload)
    name = _clean(venue.get("venue"))
    if not name:
        return None
    return RawVenue(
        name=name,
        address=_clean(venue.get("address")),
        city=_clean(venue.get("city")),
        latitude=_float_or_none(venue.get("geo_lat")),
        longitude=_float_or_none(venue.get("geo_lng")),
    )


def parse_events(payload: dict[str, Any]) -> list[RawMarketEvent]:
    events: list[RawMarketEvent] = []

    for item in payload.get("events") or []:
        if not isinstance(item, dict):
            continue
        slug = _clean(item.get("slug"))
        title = _clean(item.get("title"))
        start = _clean(item.get("utc_start_date"))
        url = _clean(item.get("url"))
        # Without all four there is no event we could name, place in time, or link to.
        if not (slug and title and start and url):
            continue

        events.append(
            RawMarketEvent(
                slug=slug,
                title=title,
                utc_start_raw=start,
                utc_end_raw=_clean(item.get("utc_end_date")),
                all_day=bool(item.get("all_day")),
                url=url,
                excerpt_html=_clean(item.get("excerpt")),
                image_url=_clean(_as_dict(item.get("image")).get("url")),
                website=_clean(item.get("website")),
                categories=tuple(
                    name
                    for name in (_clean(c.get("name")) for c in (item.get("categories") or []) if isinstance(c, dict))
                    if name
                ),
                venue=_parse_venue(item.get("venue")),
            )
        )

    return events


def fetch_raw(session: requests.Session | None = None) -> tuple[list[RawMarketEvent], dict[str, Any]]:
    client = session or requests.Session()
    collected: list[RawMarketEvent] = []
    seen: set[tuple[str, str]] = set()
    pages_read = 0

    for page in range(1, config.MAX_PAGES + 1):
        last_error: Exception | None = None
        payload: dict[str, Any] | None = None

        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                response = client.get(
                    config.EVENTS_ENDPOINT,
                    params={"per_page": config.PAGE_SIZE, "page": page},
                    timeout=config.REQUEST_TIMEOUT_SECONDS,
                    headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
                )
                # Asking for a page past the end is a 400 here, not an empty list.
                if response.status_code == 400 and page > 1:
                    payload = {"events": []}
                    break
                response.raise_for_status()
                payload = response.json()
                break
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < config.MAX_RETRIES:
                    time.sleep(2**attempt)

        if payload is None:
            if page == 1:
                raise FarmersMarketFetchError(f"could not read the first page: {last_error}")
            # A later page failing costs its occurrences, not the whole run.
            log.warning("stopping at page %d after repeated failures: %s", page, last_error)
            break

        batch = parse_events(payload)
        pages_read += 1
        if not batch:
            break

        # Key on slug plus occurrence URL: the same series repeats legitimately, so
        # only an identical occurrence is a duplicate.
        fresh = [e for e in batch if (e.slug, e.url) not in seen]
        if not fresh:
            break
        seen.update((e.slug, e.url) for e in fresh)
        collected.extend(fresh)

        if len(batch) < config.PAGE_SIZE:
            break

        time.sleep(config.SECONDS_BETWEEN_PAGES)

    stats = {"pages_read": pages_read, "collected": len(collected)}
    log.info("Portland Farmers Market read %d page(s), %d occurrences", pages_read, len(collected))
    return collected, stats
