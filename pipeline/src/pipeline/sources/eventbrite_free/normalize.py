"""Normalize Eventbrite free-filter results into the shared model.

**Free-ness.** This source claims `Price.free()`, and the evidence is the filter
rather than the record. Eventbrite's results carry no per-event price field at all;
what they carry is a server-echoed `event_search.price == "free"`, verified in
`fetch` on every page before any of that page's events reach here. So the assertion
is not "we asked for free events, so these must be free" — it is "the server told us
which query it ran, and it ran the free one." A page that stops echoing the filter is
discarded upstream rather than downgraded to `Price.unknown()`, because a page of
unfiltered results is not a page of price-unknown events, it is a page of the wrong
events.

**Recurrence.** Eventbrite runs the discovery search with `dedup: true`, which
collapses a repeating series to a single entry, and each entry that does appear is
already a dated occurrence with its own permanent numeric id. Nothing to expand.

**Time.** Dates and times arrive as separate `start_date` / `start_time` strings with
a named IANA zone rather than an offset, so we build the local moment and attach the
zone. An event with no `start_time` is treated as all-day rather than as midnight.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...common.log import get_logger
from ...common.models import Category, Event, Price, Venue, make_event_id
from . import config
from .fetch import RawEventbriteEvent

log = get_logger(__name__)

# Eventbrite's top-level taxonomy, as it appears in the `EventbriteCategory` tag.
CATEGORY_MAP: dict[str, Category] = {
    "music": Category.MUSIC,
    "performing & visual arts": Category.ARTS,
    "fashion & beauty": Category.ARTS,
    "film, media & entertainment": Category.FILM,
    "food & drink": Category.FOOD,
    "health & wellness": Category.WELLNESS,
    "sports & fitness": Category.SPORTS,
    "travel & outdoor": Category.OUTDOORS,
    "science & technology": Category.TECH,
    "family & education": Category.FAMILY,
    "school activities": Category.FAMILY,
    "government & politics": Category.CIVIC,
    "community & culture": Category.COMMUNITY,
    "charity & causes": Category.COMMUNITY,
    "religion & spirituality": Category.COMMUNITY,
    "business & professional": Category.COMMUNITY,
    "home & lifestyle": Category.COMMUNITY,
    "hobbies & special interest": Category.COMMUNITY,
    "auto, boat & air": Category.COMMUNITY,
    "seasonal & holiday": Category.COMMUNITY,
    "other": Category.COMMUNITY,
}
DEFAULT_CATEGORY = Category.COMMUNITY


class NormalizationCounters:
    def __init__(self) -> None:
        self.unparseable_time = 0
        self.stale = 0
        self.beyond_horizon = 0
        self.online = 0
        self.cancelled = 0
        self.no_venue_coordinates = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "dropped_unparseable_time": self.unparseable_time,
            "dropped_stale": self.stale,
            "dropped_beyond_horizon": self.beyond_horizon,
            "dropped_online": self.online,
            "dropped_cancelled": self.cancelled,
            "without_venue_coordinates": self.no_venue_coordinates,
        }


def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or config.DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("unknown timezone %r, falling back to %s", name, config.DEFAULT_TIMEZONE)
        return ZoneInfo(config.DEFAULT_TIMEZONE)


def combine(day: str, clock: str | None, zone: ZoneInfo) -> datetime:
    """Build a zone-aware moment from Eventbrite's split date and time fields."""
    parsed_day = date.fromisoformat(day)
    parsed_time = time.fromisoformat(clock) if clock else time(0, 0)
    return datetime.combine(parsed_day, parsed_time, tzinfo=zone)


def infer_category(label: str | None) -> tuple[Category, ...]:
    return (CATEGORY_MAP.get((label or "").strip().lower(), DEFAULT_CATEGORY),)


def _build_venue(raw: RawEventbriteEvent) -> Venue | None:
    if raw.venue is None:
        return None
    name = raw.venue.name or raw.venue.address
    if not name:
        return None
    return Venue(
        name=name,
        address=raw.venue.address,
        city=raw.venue.city or "Portland",
        latitude=raw.venue.latitude,
        longitude=raw.venue.longitude,
    )


def normalize(raw_events: list[RawEventbriteEvent], *, now: datetime) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    events: list[Event] = []
    unmapped: set[str] = set()
    horizon = now + config.FETCH_WINDOW

    for raw in raw_events:
        if raw.is_cancelled:
            counters.cancelled += 1
            continue
        if raw.is_online:
            # This app is about places you can walk to; a stream has no venue.
            counters.online += 1
            continue

        zone = _zone(raw.timezone)
        try:
            start_at = combine(raw.start_date, raw.start_time, zone)
        except (ValueError, TypeError) as exc:
            log.warning("event %s has an unparseable start %r %r: %s", raw.event_id, raw.start_date, raw.start_time, exc)
            counters.unparseable_time += 1
            continue

        end_at = None
        if raw.end_date:
            try:
                end_at = combine(raw.end_date, raw.end_time, zone)
            except (ValueError, TypeError):
                log.warning("event %s has an unparseable end %r %r", raw.event_id, raw.end_date, raw.end_time)

        if start_at > horizon:
            counters.beyond_horizon += 1
            continue

        if raw.category and raw.category.strip().lower() not in CATEGORY_MAP:
            unmapped.add(raw.category.strip())

        venue = _build_venue(raw)
        if venue is not None and venue.latitude is None:
            counters.no_venue_coordinates += 1

        event = Event(
            id=make_event_id(config.SOURCE.id, raw.event_id),
            title=raw.name,
            start_at=start_at,
            end_at=end_at,
            # No clock means Eventbrite is not stating one, not that it starts at 00:00.
            is_all_day=raw.start_time is None,
            summary=raw.summary,
            venue=venue,
            categories=infer_category(raw.category),
            # Verified free: `fetch` discards any page whose echoed query is not the
            # free filter, so every event reaching here came from one that was.
            price=Price.free(),
            image_url=raw.image_url,
            listing_url=raw.url,
            ticket_url=raw.tickets_url,
            source=config.SOURCE,
        )

        if event.is_stale(now):
            counters.stale += 1
            continue

        events.append(event)

    if unmapped:
        log.info("Eventbrite categories with no explicit mapping: %s", ", ".join(sorted(unmapped)))

    events.sort(key=lambda e: (e.start_at, e.id))
    log.info("Eventbrite normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters
