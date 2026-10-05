"""Read The Events Calendar's public REST route, `/wp-json/tribe/events/v1/events`.

Several market operators run WordPress with The Events Calendar, and the plugin's REST
route is a documented read-only interface rather than a private XHR endpoint. It also
does the one thing our `Event` model cannot: it hands back one record per occurrence
of a recurring series, so a source built on it needs no recurrence logic of its own.

Every site running it shares the same shape quirks, and each of these has bitten:

* An unset object field — `venue`, `organizer`, `image` — is an empty *list*, not null,
  and raises on a naive `.get()`.
* `title` and the venue name are HTML-escaped: `"Matt Choi&#8217;s Legacy"`,
  `"(June &#8211; September)"`. Published unescaped, the client shows the entity.
* `per_page` is silently clamped to 50.
* Asking for a page past the end is an error status, and which one varies by site (400
  on one, 404 on another). Pagination therefore stops on the response's own
  `total_pages` rather than waiting for an empty page.
* Each record carries offset-free local timestamps and offset-free UTC ones, and which
  pair to trust depends on the site's timezone setting. Configured as a named zone
  (`America/Los_Angeles`), the UTC pair is right and is the unambiguous one across a
  DST boundary. Configured as a fixed offset (`UTC-8`), WordPress derives the UTC pair
  from that offset all year, so every summer occurrence is an hour late; the local pair
  is what the organizer typed and is the one to read. `occurrence_times` decides.
* With Events Calendar Pro, the numeric `id` of a recurring occurrence is provisional
  and renumbers when the series is edited. `occurrence_key` uses the slug plus the
  occurrence's local date instead, which is the identity the per-occurrence URL encodes
  and which works equally for sites that publish each market day as its own post.
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from .http import JSON_HEADERS
from .log import get_logger

log = get_logger(__name__)

PAGE_SIZE = 50

# Visual Composer and similar page builders leave `[vc_row ...]` shortcodes in the
# rendered excerpt.
_SHORTCODE = re.compile(r"\[/?[a-z][\w-]*(?:\s[^\]]*)?\]", re.IGNORECASE)

_UTC = ZoneInfo("UTC")

# WordPress's "Manual offset" timezone choice serializes as `UTC`, `UTC-8`, `UTC+5:30`.
_FIXED_OFFSET = re.compile(r"^UTC(?:[+-]\d{1,2}(?::?\d{2})?)?$")


class TribeFetchError(Exception):
    """Upstream did not return usable data."""


@dataclass(frozen=True)
class TribeVenue:
    name: str
    address: str | None
    city: str | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class TribeEvent:
    slug: str
    title: str
    utc_start_raw: str
    utc_end_raw: str | None
    local_start_raw: str | None
    local_end_raw: str | None
    timezone: str | None
    all_day: bool
    url: str
    description_html: str | None
    excerpt_html: str | None
    image_url: str | None
    categories: tuple[str, ...]
    venue: TribeVenue | None
    cost: str | None

    @property
    def states_no_price(self) -> bool:
        """Whether upstream leaves the price unstated or says it is free."""
        return self.cost is None or self.cost.casefold() == "free"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _unescaped(value: Any) -> str | None:
    cleaned = _clean(value)
    return _clean(html.unescape(cleaned)) if cleaned else None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_venue(payload: Any) -> TribeVenue | None:
    venue = _as_dict(payload)
    name = _unescaped(venue.get("venue"))
    if not name:
        return None
    return TribeVenue(
        name=name,
        address=_unescaped(venue.get("address")),
        city=_unescaped(venue.get("city")),
        latitude=_float_or_none(venue.get("geo_lat")),
        longitude=_float_or_none(venue.get("geo_lng")),
    )


def _category_names(payload: Any) -> tuple[str, ...]:
    names = (_unescaped(c.get("name")) for c in (payload or []) if isinstance(c, dict))
    return tuple(name for name in names if name)


def parse_events(payload: dict[str, Any]) -> list[TribeEvent]:
    events: list[TribeEvent] = []

    for item in payload.get("events") or []:
        if not isinstance(item, dict):
            continue
        slug = _clean(item.get("slug"))
        title = _unescaped(item.get("title"))
        start = _clean(item.get("utc_start_date"))
        url = _clean(item.get("url"))
        # Without all four there is no event we could name, place in time, or link to.
        if not (slug and title and start and url):
            continue

        events.append(
            TribeEvent(
                slug=slug,
                title=title,
                utc_start_raw=start,
                utc_end_raw=_clean(item.get("utc_end_date")),
                local_start_raw=_clean(item.get("start_date")),
                local_end_raw=_clean(item.get("end_date")),
                timezone=_clean(item.get("timezone")),
                all_day=bool(item.get("all_day")),
                url=url,
                description_html=_clean(item.get("description")),
                excerpt_html=_clean(item.get("excerpt")),
                image_url=_clean(_as_dict(item.get("image")).get("url")),
                categories=_category_names(item.get("categories")),
                venue=_parse_venue(item.get("venue")),
                cost=_unescaped(item.get("cost")),
            )
        )

    return events


def _total_pages(payload: dict[str, Any]) -> int | None:
    try:
        return int(payload["total_pages"])
    except (KeyError, TypeError, ValueError):
        return None


def fetch_events(
    endpoint: str,
    *,
    seconds_between_pages: float,
    session: requests.Session | None = None,
    max_pages: int = 20,
    timeout: float = 25,
    max_retries: int = 3,
) -> tuple[list[TribeEvent], dict[str, Any]]:
    """Read every upcoming occurrence the endpoint publishes.

    The route defaults to events from now onward, which is all a feed needs. A later
    page failing costs its occurrences rather than the whole run; the first page
    failing raises, so the caller keeps its previously published file.
    """
    client = session or requests.Session()
    collected: list[TribeEvent] = []
    seen: set[tuple[str, str]] = set()
    pages_read = 0

    for page in range(1, max_pages + 1):
        last_error: Exception | None = None
        payload: dict[str, Any] | None = None

        for attempt in range(1, max_retries + 1):
            try:
                response = client.get(
                    endpoint,
                    params={"per_page": PAGE_SIZE, "page": page},
                    timeout=timeout,
                    headers=JSON_HEADERS,
                )
                if response.status_code in (400, 404) and page > 1:
                    payload = {"events": []}
                    break
                response.raise_for_status()
                payload = response.json()
                break
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < max_retries:
                    time.sleep(2**attempt)

        if payload is None:
            if page == 1:
                raise TribeFetchError(f"could not read the first page of {endpoint}: {last_error}")
            log.warning("stopping at page %d after repeated failures: %s", page, last_error)
            break

        batch = parse_events(payload)
        pages_read += 1

        # The same series repeats legitimately, so only an identical occurrence is a
        # duplicate.
        fresh = [e for e in batch if (e.slug, e.url) not in seen]
        seen.update((e.slug, e.url) for e in fresh)
        collected.extend(fresh)

        # Counted before parsing drops malformed records, so one bad record on a full
        # page does not end pagination early.
        records_on_page = len(payload.get("events") or [])
        total_pages = _total_pages(payload)
        if not fresh or records_on_page < PAGE_SIZE or (total_pages is not None and page >= total_pages):
            break

        time.sleep(seconds_between_pages)

    log.info("read %d page(s), %d occurrence(s) from %s", pages_read, len(collected), endpoint)
    return collected, {"pages_read": pages_read, "collected": len(collected)}


def _parse_utc(value: str, zone: ZoneInfo) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_UTC)
    return moment.astimezone(zone)


def _parse_wall_clock(value: str, zone: ZoneInfo) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=zone)


def has_fixed_offset_zone(raw: TribeEvent) -> bool:
    """Whether the site is configured with a fixed UTC offset rather than a named zone."""
    return raw.timezone is not None and _FIXED_OFFSET.match(raw.timezone) is not None


def occurrence_times(raw: TribeEvent, zone: ZoneInfo) -> tuple[datetime, datetime | None]:
    """The occurrence's start and end in `zone`. See the module docstring for the choice.

    Raises `ValueError` if the start is unreadable. An unreadable end is reported as
    no end rather than failing the occurrence.
    """
    wall_clock = has_fixed_offset_zone(raw) and raw.local_start_raw is not None
    if wall_clock:
        start_at = _parse_wall_clock(raw.local_start_raw, zone)
    else:
        start_at = _parse_utc(raw.utc_start_raw, zone)

    end_raw = raw.local_end_raw if wall_clock else raw.utc_end_raw
    end_at = None
    if end_raw:
        try:
            end_at = _parse_wall_clock(end_raw, zone) if wall_clock else _parse_utc(end_raw, zone)
        except ValueError:
            log.warning("occurrence %s has an unparseable end %r", raw.slug, end_raw)
    return start_at, end_at


def occurrence_key(slug: str, start_at: datetime) -> str:
    """Stable per-occurrence identity: the slug plus the occurrence's local date."""
    return f"{slug}@{start_at.date().isoformat()}"


def html_to_text(value: str | None, *, max_chars: int = 400) -> str | None:
    if not value:
        return None
    text = BeautifulSoup(_SHORTCODE.sub(" ", value), "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "\u2026"
    return text
