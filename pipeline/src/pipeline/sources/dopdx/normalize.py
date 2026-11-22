"""Normalize DoPDX events into the shared model.

Notes from the live payload (listing + detail merged by fetch.py):
  - `tz_adjusted_begin_time` already carries the correct Portland offset. The plain
    `begin_time` field does not — it appeared as `-05:00` on an event that runs at
    `-07:00` — so only the tz_adjusted fields are trusted.
  - `free_event` is an explicit boolean, which no other source provides.
    `ticket_info` is free text like "$73 to $669, All Ages".
  - `description` contains HTML (`<br />`, links) and is stripped to text.
  - `image_url` is a pre-rendered asset URL, so no resize transform is needed.
"""

from __future__ import annotations

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
    # New vocabulary the doxyz platform added after the SvelteKit migration.
    "literature": Category.LITERARY,
    "food & dining": Category.FOOD,
    "happy hours": Category.FOOD,
    "karaoke": Category.NIGHTLIFE,
    "drag": Category.NIGHTLIFE,
    "parties": Category.NIGHTLIFE,
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


def is_in_metro(venue: Venue | None) -> bool:
    """Whether an event is close enough to Portland to belong in the feed.

    DoPDX serves the wider Pacific Northwest. Coordinates settle it when present;
    otherwise fall back to the city name, keeping anything unrecognised on the
    grounds that an unknown string is more likely a neighbourhood than a distant city.
    """
    if venue is None:
        return True

    if venue.latitude is not None and venue.longitude is not None:
        return _miles_from_portland(venue.latitude, venue.longitude) <= config.MAX_DISTANCE_MILES

    city = (venue.city or "").strip().lower()
    return city not in config.NON_METRO_CITIES


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = _TAG.sub(" ", value)
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


def _build_price(raw: dict[str, Any]) -> Price:
    if raw.get("free_event") is True:
        return Price.free()

    # "$73 to $669, All Ages" -> 73.0, 669.0
    amounts = [float(m) for m in _PRICE.findall(raw.get("ticket_info") or "")]
    if not amounts:
        # Paid, but no figure stated. Unknown rather than a guess.
        return Price.unknown()
    return Price(is_free=False, min=min(amounts), max=max(amounts) if len(amounts) > 1 else min(amounts))


def _build_venue(raw: dict[str, Any]) -> Venue | None:
    venue = raw.get("venue") or {}
    name = _clean(venue.get("title"))
    if not name:
        return None
    return Venue(
        name=name,
        address=_clean(venue.get("address")),
        city=_clean(venue.get("city")),
        latitude=venue.get("latitude"),
        longitude=venue.get("longitude"),
    )


def normalize(
    raw_events: list[dict[str, Any]],
    *,
    now: datetime,
) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    events: list[Event] = []

    for raw in raw_events:
        if raw.get("is_past") is True:
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

        venue = _build_venue(raw)
        if not is_in_metro(venue):
            counters.outside_metro += 1
            continue

        permalink = raw.get("permalink") or ""
        event = Event(
            id=make_event_id(config.SOURCE.id, raw["id"]),
            title=title,
            start_at=start_at,
            end_at=end_at,
            summary=_clean(raw.get("description")),
            venue=venue,
            categories=infer_categories(raw.get("category")),
            price=_build_price(raw),
            image_url=raw.get("image_url") or None,
            listing_url=f"{config.BASE_URL}{permalink}" if permalink.startswith("/") else (permalink or None),
            organizer=_clean(raw.get("presented_by")),
            source=config.SOURCE,
        )

        if event.is_stale(now):
            counters.stale += 1
            continue

        events.append(event)

    events.sort(key=lambda e: e.start_at)
    log.info("DoPDX normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters
