"""Normalize Ticketmaster's Discovery API payloads into the shared Event model.

Shape notes from live data:
  - `dates.start.dateTime` is UTC; `dates.timezone` carries the real local zone. We
    convert to local so the app renders the time a Portlander would actually see.
  - `dateTBD` / `dateTBA` / `timeTBA` / `noSpecificTime` flags mark placeholder times.
  - `dates.status.code` includes `cancelled`, which must not reach the feed.
  - `priceRanges` is present on only about 27% of events.
  - Venue coordinates are strings under `_embedded.venues[0].location`.
  - `images` offers many sizes; the largest 16:9 is the usable one for a card.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...common.io import parse_datetime
from ...common.log import get_logger
from ...common.models import Event, Price, Venue, make_event_id
from . import config
from .categories import infer_categories

log = get_logger(__name__)


class NormalizationCounters:
    def __init__(self) -> None:
        self.cancelled = 0
        self.test_event = 0
        self.no_start_time = 0
        self.time_tba = 0
        self.unparseable_time = 0
        self.stale = 0
        self.no_title = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "dropped_cancelled": self.cancelled,
            "dropped_test_event": self.test_event,
            "dropped_no_start_time": self.no_start_time,
            "dropped_time_tba": self.time_tba,
            "dropped_unparseable_time": self.unparseable_time,
            "dropped_stale": self.stale,
            "dropped_no_title": self.no_title,
        }


def _coerce_coordinate(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _best_image(images: list[dict[str, Any]] | None) -> str | None:
    """Largest 16:9 image, falling back to the largest of any ratio.

    16:9 matches the card layout; other ratios crop badly.
    """
    if not images:
        return None
    usable = [i for i in images if i.get("url")]
    if not usable:
        return None
    widescreen = [i for i in usable if i.get("ratio") == "16_9"]
    pool = widescreen or usable
    return max(pool, key=lambda i: i.get("width") or 0).get("url")


def _build_venue(raw_event: dict[str, Any]) -> Venue | None:
    venues = raw_event.get("_embedded", {}).get("venues") or []
    if not venues:
        return None
    venue = venues[0]

    name = _clean(venue.get("name"))
    if not name:
        return None

    location = venue.get("location") or {}
    return Venue(
        name=name,
        address=_clean((venue.get("address") or {}).get("line1")),
        city=_clean((venue.get("city") or {}).get("name")),
        latitude=_coerce_coordinate(location.get("latitude")),
        longitude=_coerce_coordinate(location.get("longitude")),
    )


def _build_price(raw_event: dict[str, Any]) -> Price:
    ranges = raw_event.get("priceRanges") or []
    if not ranges:
        # Absent on ~73% of events. Unknown, not free — a wrong "Free" badge on a
        # ticketed show is the costlier direction to be wrong in.
        return Price.unknown()

    standard = next((r for r in ranges if r.get("type") == "standard"), ranges[0])
    minimum = standard.get("min")
    maximum = standard.get("max")
    if minimum == 0 and maximum == 0:
        return Price.free()
    return Price(
        is_free=False,
        min=minimum,
        max=maximum,
        currency=standard.get("currency") or "USD",
    )


def _primary_classification(raw_event: dict[str, Any]) -> tuple[str | None, str | None]:
    classifications = raw_event.get("classifications") or []
    if not classifications:
        return None, None
    primary = next((c for c in classifications if c.get("primary")), classifications[0])
    return (
        (primary.get("segment") or {}).get("name"),
        (primary.get("genre") or {}).get("name"),
    )


def _start_datetime(raw_event: dict[str, Any]) -> datetime | None:
    """Resolve the start instant in Portland local time.

    The API gives UTC in `dateTime` plus a `timezone`. Converting to the event's own
    zone means the serialized offset matches what an attendee would read on a poster.
    """
    start = (raw_event.get("dates") or {}).get("start") or {}
    raw = start.get("dateTime")
    if not raw:
        return None

    moment = parse_datetime(raw)
    tz_name = (raw_event.get("dates") or {}).get("timezone")
    if tz_name:
        try:
            return moment.astimezone(ZoneInfo(tz_name))
        except (ZoneInfoNotFoundError, ValueError):
            log.warning("unknown timezone %r on event %s", tz_name, raw_event.get("id"))
    return moment


def normalize(raw_events: list[dict[str, Any]], *, now: datetime) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    events: list[Event] = []

    for raw in raw_events:
        if raw.get("test") is True:
            counters.test_event += 1
            continue

        dates = raw.get("dates") or {}
        status = ((dates.get("status") or {}).get("code") or "").lower()
        if status in config.EXCLUDED_STATUS_CODES:
            counters.cancelled += 1
            continue

        title = _clean(raw.get("name"))
        if not title:
            counters.no_title += 1
            continue

        start_block = dates.get("start") or {}
        if start_block.get("dateTBD") or start_block.get("dateTBA"):
            counters.no_start_time += 1
            continue
        if start_block.get("timeTBA") or start_block.get("noSpecificTime"):
            # A date without a real time would render as an arbitrary hour in the feed.
            counters.time_tba += 1
            continue

        try:
            start_at = _start_datetime(raw)
        except (ValueError, TypeError) as exc:
            log.warning("event %s has unparseable start time: %s", raw.get("id"), exc)
            counters.unparseable_time += 1
            continue

        if start_at is None:
            counters.no_start_time += 1
            continue

        segment_name, genre_name = _primary_classification(raw)
        promoter = (raw.get("promoter") or {}).get("name")

        event = Event(
            id=make_event_id(config.SOURCE.id, raw["id"]),
            title=title,
            start_at=start_at,
            summary=_clean(raw.get("info")) or _clean(raw.get("pleaseNote")),
            venue=_build_venue(raw),
            categories=infer_categories(segment_name, genre_name),
            price=_build_price(raw),
            image_url=_best_image(raw.get("images")),
            listing_url=_clean(raw.get("url")),
            ticket_url=_clean(raw.get("url")),
            organizer=_clean(promoter),
            source=config.SOURCE,
        )

        if event.is_stale(now):
            counters.stale += 1
            continue

        events.append(event)

    events.sort(key=lambda e: e.start_at)
    log.info("Ticketmaster normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters
