"""Normalize Summer Free For All rows into the shared model.

Everything here is free — that is the programme's entire premise — so unlike every
other source this one can assert `Price.free()` rather than leaving price unknown.

Dates arrive as "July 10" plus "7:30pm" with the year in a page heading, so they are
assembled and localised to Portland rather than parsed from a single field.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ...common.log import get_logger
from ...common.models import Category, Event, Price, Venue, make_event_id
from . import config
from .fetch import RawParksEvent

log = get_logger(__name__)

_VENUES_PATH = Path(__file__).with_name("venues.json")

TYPE_CATEGORIES: dict[str, Category] = {
    "movie": Category.FILM,
    "concert": Category.MUSIC,
    "festival": Category.COMMUNITY,
    "special event": Category.COMMUNITY,
    "performance": Category.ARTS,
    "theatre": Category.ARTS,
    "theater": Category.ARTS,
    "workshop": Category.COMMUNITY,
}
DEFAULT_CATEGORY = Category.COMMUNITY

_TIME = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\s*$", re.IGNORECASE)


def _load_venues() -> dict[str, tuple[float, float]]:
    try:
        raw = json.loads(_VENUES_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read %s (%s); park events will have no coordinates", _VENUES_PATH, exc)
        return {}
    return {name: (float(lat), float(lon)) for name, (lat, lon) in raw.items()}


VENUE_COORDINATES = _load_venues()


class NormalizationCounters:
    def __init__(self) -> None:
        self.unparseable_date = 0
        self.stale = 0
        self.no_venue_coordinates = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "dropped_unparseable_date": self.unparseable_date,
            "dropped_stale": self.stale,
            "without_venue_coordinates": self.no_venue_coordinates,
        }


def parse_when(date_text: str, time_text: str, year: int) -> datetime:
    """Assemble "July 10" + "7:30pm" + 2026 into a Portland-local instant."""
    day = datetime.strptime(f"{date_text.strip()} {year}", "%B %d %Y")

    match = _TIME.match(time_text)
    if not match:
        raise ValueError(f"unrecognised time {time_text!r}")
    hour = int(match.group(1)) % 12
    minute = int(match.group(2) or 0)
    if match.group(3).lower() == "p":
        hour += 12

    return day.replace(hour=hour, minute=minute, tzinfo=ZoneInfo(config.TIMEZONE))


def infer_categories(event_type: str | None) -> tuple[Category, ...]:
    return (TYPE_CATEGORIES.get((event_type or "").strip().lower(), DEFAULT_CATEGORY),)


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


def _slug(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def normalize(raw_events: list[RawParksEvent], *, now: datetime) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    events: list[Event] = []

    for raw in raw_events:
        try:
            start_at = parse_when(raw.date_text, raw.time_text, raw.year)
        except ValueError as exc:
            log.warning("could not read %r %r: %s", raw.date_text, raw.time_text, exc)
            counters.unparseable_date += 1
            continue

        venue = _build_venue(raw.venue)
        if venue is not None and venue.latitude is None:
            counters.no_venue_coordinates += 1

        # The table carries no identifier, so one is composed from the fields that
        # identify an occurrence. Title and venue can be edited upstream, but the
        # date cannot move without it genuinely being a different occurrence.
        identifier = f"{start_at:%Y-%m-%d}-{_slug(raw.venue or 'portland')}-{_slug(raw.title)[:40]}"

        event = Event(
            id=make_event_id(config.SOURCE.id, identifier),
            title=raw.title,
            start_at=start_at,
            summary=raw.detail if raw.detail != raw.title else None,
            venue=venue,
            categories=infer_categories(raw.event_type),
            # Summer Free For All is free by definition — the one source that can
            # say so rather than leaving price unknown.
            price=Price.free(),
            listing_url=config.EVENTS_URL,
            organizer="Portland Parks & Recreation",
            source=config.SOURCE,
        )

        if event.is_stale(now):
            counters.stale += 1
            continue

        events.append(event)

    events.sort(key=lambda e: e.start_at)
    log.info("Portland Parks normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters
