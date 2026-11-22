"""Normalize DoPDX events into the shared model.

Each raw event is a day-listing entry, plus a `detail` dict when its own page has
been fetched (see fetch.py). Notes from the live payload:
  - `tz_adjusted_begin_time` carries the correct Portland offset. The plain
    `begin_time` field does not — it is a UTC wall time with no offset — so only the
    tz_adjusted fields are trusted.
  - `free_event` is an explicit boolean, which no other source provides.
    `ticket_info` is free text like "$40.29-$45.93".
  - Venue coordinates and city exist only on the event page, so an event without
    page details falls back to the listing's area name for the metro filter.
  - `description` contains HTML and HTML entities.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from typing import Any

from ...common.io import parse_datetime
from ...common.log import get_logger
from ...common.models import Category, Event, Price, Venue, make_event_id
from . import config

log = get_logger(__name__)

# DoPDX's own vocabulary, observed across sampled days.
CATEGORY_MAP: dict[str, Category] = {
    "music": Category.MUSIC,
    "comedy": Category.ARTS,
    "theatre & performing arts": Category.ARTS,
    "art": Category.ARTS,
    "culture": Category.COMMUNITY,
    "movies": Category.FILM,
    "film": Category.FILM,
    "beer": Category.FOOD,
    "food & drink": Category.FOOD,
    "sports & rec": Category.SPORTS,
    "trivia": Category.NIGHTLIFE,
    "nightlife": Category.NIGHTLIFE,
    "convention": Category.COMMUNITY,
    "festivals": Category.COMMUNITY,
    "children & family": Category.FAMILY,
    "family": Category.FAMILY,
    "literary": Category.LITERARY,
    "readings & talks": Category.LITERARY,
    "wellness": Category.WELLNESS,
    "outdoors": Category.OUTDOORS,
    "dance": Category.ARTS,
    "sports": Category.SPORTS,
    "game night": Category.NIGHTLIFE,
    "cannabis": Category.NIGHTLIFE,
    "drag": Category.NIGHTLIFE,
    "karaoke": Category.NIGHTLIFE,
    "parties": Category.NIGHTLIFE,
    "happy hours": Category.FOOD,
    "food & dining": Category.FOOD,
    "literature": Category.LITERARY,
    "education & instructional": Category.COMMUNITY,
    "holiday event": Category.COMMUNITY,
    "lgbtq": Category.COMMUNITY,
    # "Eugene" appears in the category vocabulary because DoStuff runs sibling city
    # guides. It says nothing about the event's nature; the distance filter is what
    # keeps out-of-metro events out.
    "eugene": Category.COMMUNITY,
}
DEFAULT_CATEGORY = Category.COMMUNITY

_unmapped_seen: set[str] = set()

_PRICE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]{1,2})?)")
_TAG = re.compile(r"<[^>]+>")


class NormalizationCounters:
    def __init__(self) -> None:
        self.past = 0
        self.no_start = 0
        self.unparseable_time = 0
        self.stale = 0
        self.no_title = 0
        self.outside_metro = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "dropped_past": self.past,
            "dropped_no_start": self.no_start,
            "dropped_unparseable_time": self.unparseable_time,
            "dropped_stale": self.stale,
            "dropped_no_title": self.no_title,
            "dropped_outside_metro": self.outside_metro,
        }


def _miles_from_portland(latitude: float, longitude: float) -> float:
    """Great-circle distance in miles. Haversine is ample at metro scale."""
    radius = 3958.8
    lat1, lat2 = radians(config.PORTLAND_LATITUDE), radians(latitude)
    dlat = lat2 - lat1
    dlon = radians(longitude - config.PORTLAND_LONGITUDE)
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * radius * asin(sqrt(a))


def is_in_metro(venue: Venue | None, area: str | None = None) -> bool:
    """Whether an event is close enough to Portland to belong in the feed.

    DoPDX serves the wider Pacific Northwest. Coordinates settle it when present;
    otherwise fall back to the city and the listing's area name, keeping anything
    unrecognised on the grounds that an unknown string is more likely a
    neighbourhood than a distant city.
    """
    if (area or "").strip().lower() in config.NON_METRO_AREAS:
        return False

    if venue is None:
        return True

    if venue.latitude is not None and venue.longitude is not None:
        return _miles_from_portland(venue.latitude, venue.longitude) <= config.MAX_DISTANCE_MILES

    city = (venue.city or "").strip().lower()
    return city not in config.NON_METRO_CITIES


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = html.unescape(_TAG.sub(" ", value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def infer_categories(label: str | None) -> tuple[Category, ...]:
    key = (label or "").strip().lower()
    if key in CATEGORY_MAP:
        return (CATEGORY_MAP[key],)
    if key and key not in _unmapped_seen:
        _unmapped_seen.add(key)
        log.info("DoPDX category %r has no mapping; using %s", label, DEFAULT_CATEGORY.value)
    return (DEFAULT_CATEGORY,)


def unmapped_categories() -> list[str]:
    return sorted(_unmapped_seen)


def _build_price(detail: dict[str, Any] | None) -> Price:
    if not detail:
        return Price.unknown()
    if detail.get("free_event") is True:
        return Price.free()

    # "$40.29-$45.93" -> 40.29, 45.93
    amounts = [float(m) for m in _PRICE.findall(detail.get("ticket_info") or "")]
    if not amounts:
        # Paid, but no figure stated. Unknown rather than a guess.
        return Price.unknown()
    return Price(is_free=False, min=min(amounts), max=max(amounts) if len(amounts) > 1 else min(amounts))


def _coordinate(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _build_venue(raw: dict[str, Any], detail: dict[str, Any] | None) -> Venue | None:
    listed = raw.get("venue") or {}
    located = (detail or {}).get("venue") or {}
    name = _clean(located.get("name")) or _clean(listed.get("title"))
    if not name:
        return None
    return Venue(
        name=name,
        address=_clean(located.get("address")),
        city=_clean(located.get("city")),
        latitude=_coordinate(located.get("latitude")),
        longitude=_coordinate(located.get("longitude")),
    )


def _build_image(raw: dict[str, Any]) -> str | None:
    url = (raw.get("image_url") or "").strip()
    return url if url.startswith("https://") else None


def normalize(
    raw_events: list[dict[str, Any]],
    *,
    now: datetime,
) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    events: list[Event] = []

    for raw in raw_events:
        detail = raw.get("detail")
        if detail and detail.get("is_past") is True:
            counters.past += 1
            continue

        title = _clean(raw.get("title"))
        if not title:
            counters.no_title += 1
            continue

        # Only the tz_adjusted fields carry a trustworthy offset.
        start_raw = raw.get("tz_adjusted_begin_time")
        if not start_raw:
            counters.no_start += 1
            continue

        try:
            start_at = parse_datetime(start_raw)
        except (ValueError, TypeError) as exc:
            log.warning("event %s has an unparseable start %r: %s", raw.get("id"), start_raw, exc)
            counters.unparseable_time += 1
            continue

        end_at = None
        if raw.get("tz_adjusted_end_time"):
            try:
                end_at = parse_datetime(raw["tz_adjusted_end_time"])
            except (ValueError, TypeError):
                log.warning("event %s has an unparseable end", raw.get("id"))

        venue = _build_venue(raw, detail)
        if not is_in_metro(venue, (raw.get("venue") or {}).get("area_name")):
            counters.outside_metro += 1
            continue

        permalink = raw.get("permalink") or ""
        event = Event(
            id=make_event_id(config.SOURCE.id, raw["id"]),
            title=title,
            start_at=start_at,
            end_at=end_at,
            summary=_clean((detail or {}).get("description")),
            venue=venue,
            categories=infer_categories(raw.get("category")),
            price=_build_price(detail),
            image_url=_build_image(raw),
            listing_url=f"{config.BASE_URL}{permalink}" if permalink.startswith("/") else (permalink or None),
            organizer=_clean((detail or {}).get("presented_by")) or _clean(raw.get("presented_by")),
            source=config.SOURCE,
        )

        if event.is_stale(now):
            counters.stale += 1
            continue

        events.append(event)

    events.sort(key=lambda e: e.start_at)
    log.info("DoPDX normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters
