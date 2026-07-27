"""Normalize Calagator's raw JSON into the shared Event model.

Shape notes from live data, none of which are documented upstream:
  - The venue's display name is `title`, not `name`.
  - Venue `latitude` / `longitude` are strings, or null, or empty strings.
  - `duplicate_of_id` is Calagator's own dedup marker; those rows are shadows of
    another event and must be dropped.
  - There is no price field of any kind.
  - Timestamps carry fractional seconds and an explicit offset.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ...common.io import parse_datetime
from ...common.log import get_logger
from ...common.models import Event, Price, Venue, make_event_id
from . import config
from .categories import infer_categories

log = get_logger(__name__)


class NormalizationCounters:
    """Why events were dropped. Surfaced in the run report so silent loss is visible."""

    def __init__(self) -> None:
        self.duplicate = 0
        self.no_start_time = 0
        self.unparseable_time = 0
        self.stale = 0
        self.no_title = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "dropped_duplicate": self.duplicate,
            "dropped_no_start_time": self.no_start_time,
            "dropped_unparseable_time": self.unparseable_time,
            "dropped_stale": self.stale,
            "dropped_no_title": self.no_title,
        }


def _coerce_coordinate(value: Any) -> float | None:
    """Calagator sends coordinates as strings, and sometimes as empty strings."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_venue(raw: dict[str, Any] | None, venue_details: str | None) -> Venue | None:
    if not raw:
        # `venue_details` is free text used when there is no venue record. It is not
        # a name, so it becomes the address rather than pretending to be a venue.
        return Venue(name="Portland", address=venue_details) if venue_details else None

    name = (raw.get("title") or "").strip()
    if not name:
        return None

    street = (raw.get("street_address") or "").strip() or None
    return Venue(
        name=name,
        address=street,
        city=(raw.get("locality") or "").strip() or None,
        latitude=_coerce_coordinate(raw.get("latitude")),
        longitude=_coerce_coordinate(raw.get("longitude")),
    )


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def normalize(raw_events: list[dict[str, Any]], *, now: datetime) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    events: list[Event] = []

    for raw in raw_events:
        # Calagator marks known duplicates rather than deleting them.
        if raw.get("duplicate_of_id") is not None:
            counters.duplicate += 1
            continue

        title = _clean(raw.get("title"))
        if not title:
            counters.no_title += 1
            continue

        start_raw = raw.get("start_time")
        if not start_raw:
            counters.no_start_time += 1
            continue

        try:
            start_at = parse_datetime(start_raw)
        except (ValueError, TypeError) as exc:
            log.warning("Calagator event %s has unparseable start_time %r: %s", raw.get("id"), start_raw, exc)
            counters.unparseable_time += 1
            continue

        end_at = None
        if raw.get("end_time"):
            try:
                end_at = parse_datetime(raw["end_time"])
            except (ValueError, TypeError):
                # A bad end time isn't worth dropping an otherwise valid event over.
                log.warning("Calagator event %s has unparseable end_time %r", raw.get("id"), raw["end_time"])

        description = _clean(raw.get("description"))
        event = Event(
            id=make_event_id(config.SOURCE.id, raw["id"]),
            title=title,
            start_at=start_at,
            end_at=end_at,
            summary=description,
            venue=_build_venue(raw.get("venue"), _clean(raw.get("venue_details"))),
            categories=infer_categories(title, description),
            # Calagator has no price field. Free is a claim we cannot substantiate,
            # and wrongly showing "Free" on a paid event is worse than showing nothing.
            price=Price.unknown(),
            listing_url=_clean(raw.get("url")),
            source=config.SOURCE,
        )

        if event.is_stale(now):
            counters.stale += 1
            continue

        events.append(event)

    events.sort(key=lambda e: e.start_at)
    log.info("Calagator normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters
