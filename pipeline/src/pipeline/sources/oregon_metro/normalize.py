"""Normalize Oregon Metro events into the shared model.

Two things need care here.

The `datetime` attribute has no UTC offset but is UTC — the page renders
`2026-07-25T18:00:00` as "11 a.m.", and Portland was UTC-7 that day. Parsing it as
naive local time would shift every Metro event seven hours.

The listing gives a venue name but no coordinates. Metro uses a small, stable set of
venues, so they are geocoded once into `venues.json` rather than adding a geocoding
service call to every pipeline run. Venues missing from the table still produce an
event; it simply will not appear on the map.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ...common.log import get_logger
from ...common.models import Category, Event, Price, Venue, make_event_id
from . import config
from .fetch import RawMetroEvent

log = get_logger(__name__)

_VENUES_PATH = Path(__file__).with_name("venues.json")

# Metro's own taxonomy, straight off the page.
CATEGORY_MAP: dict[str, Category] = {
    "meetings": Category.CIVIC,
    "nature activity": Category.OUTDOORS,
    "community events": Category.COMMUNITY,
    "opportunity": Category.COMMUNITY,
    "volunteer": Category.COMMUNITY,
    "recycling": Category.CIVIC,
    "garbage and recycling": Category.CIVIC,
}
DEFAULT_CATEGORY = Category.CIVIC


def _load_venues() -> dict[str, tuple[float, float]]:
    try:
        raw = json.loads(_VENUES_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read %s (%s); Metro events will have no coordinates", _VENUES_PATH, exc)
        return {}
    return {name: (float(lat), float(lon)) for name, (lat, lon) in raw.items()}


VENUE_COORDINATES = _load_venues()


class NormalizationCounters:
    def __init__(self) -> None:
        self.unparseable_time = 0
        self.stale = 0
        self.no_venue_coordinates = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "dropped_unparseable_time": self.unparseable_time,
            "dropped_stale": self.stale,
            "without_venue_coordinates": self.no_venue_coordinates,
        }


def _parse_utc(value: str) -> datetime:
    """Interpret Metro's offset-free timestamp as UTC and return Portland local time."""
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo(config.SOURCE_TIMEZONE))
    return moment.astimezone(ZoneInfo(config.DISPLAY_TIMEZONE))


def _build_venue(name: str | None) -> Venue | None:
    if not name:
        return None
    coordinates = VENUE_COORDINATES.get(name)
    return Venue(
        name=name,
        city="Portland",
        latitude=coordinates[0] if coordinates else None,
        longitude=coordinates[1] if coordinates else None,
    )


def infer_category(label: str | None) -> tuple[Category, ...]:
    return (CATEGORY_MAP.get((label or "").strip().lower(), DEFAULT_CATEGORY),)


def normalize(raw_events: list[RawMetroEvent], *, now: datetime) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    events: list[Event] = []
    unmapped: set[str] = set()

    for raw in raw_events:
        try:
            start_at = _parse_utc(raw.start_raw)
        except (ValueError, TypeError) as exc:
            log.warning("event %s has an unparseable start %r: %s", raw.slug, raw.start_raw, exc)
            counters.unparseable_time += 1
            continue

        end_at = None
        if raw.end_raw:
            try:
                end_at = _parse_utc(raw.end_raw)
            except (ValueError, TypeError):
                log.warning("event %s has an unparseable end %r", raw.slug, raw.end_raw)

        if raw.category and raw.category.strip().lower() not in CATEGORY_MAP:
            unmapped.add(raw.category.strip())

        venue = _build_venue(raw.location)
        if venue is not None and venue.latitude is None:
            counters.no_venue_coordinates += 1

        event = Event(
            id=make_event_id(config.SOURCE.id, raw.slug),
            title=raw.title,
            start_at=start_at,
            end_at=end_at,
            venue=venue,
            categories=infer_category(raw.category),
            # Metro's listing states no price. Most of this is free public
            # programming, but asserting that without data would be a guess.
            price=Price.unknown(),
            listing_url=raw.url,
            source=config.SOURCE,
        )

        if event.is_stale(now):
            counters.stale += 1
            continue

        events.append(event)

    if unmapped:
        log.info("Metro categories with no explicit mapping: %s", ", ".join(sorted(unmapped)))

    events.sort(key=lambda e: e.start_at)
    log.info("Oregon Metro normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters
