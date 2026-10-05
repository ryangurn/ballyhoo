"""Normalize Oregon City Farmers Market occurrences into the shared model.

**Summary.** None. The plugin's excerpt on this site is the page builder's footer —
phone number, mailing address, payment methods — rather than anything about the day,
and the description is the whole market homepage.

**Price.** `Price.free()` for market days, on the same grounds as every market source:
no gate, no ticket, and an empty `cost` upstream. Anything else the site might post is
`Price.unknown()`, and so is any record that states a cost.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ...common.log import get_logger
from ...common.models import Category, Event, Price, Venue, make_event_id
from ...common.tribe_events import TribeEvent, occurrence_key, occurrence_times
from . import config

log = get_logger(__name__)


class NormalizationCounters:
    def __init__(self) -> None:
        self.unparseable_time = 0
        self.stale = 0
        self.beyond_horizon = 0
        self.no_venue_coordinates = 0
        self.duplicate_id = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "dropped_unparseable_time": self.unparseable_time,
            "dropped_stale": self.stale,
            "dropped_beyond_horizon": self.beyond_horizon,
            "dropped_duplicate_id": self.duplicate_id,
            "without_venue_coordinates": self.no_venue_coordinates,
        }


def is_market_day(raw: TribeEvent) -> bool:
    return config.MARKET_CATEGORY in raw.categories


def _build_venue(raw: TribeEvent) -> Venue | None:
    if raw.venue is None:
        return None
    return Venue(
        name=raw.venue.name,
        address=raw.venue.address,
        city=raw.venue.city or "Oregon City",
        latitude=raw.venue.latitude,
        longitude=raw.venue.longitude,
    )


def normalize(raw_events: list[TribeEvent], *, now: datetime) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    zone = ZoneInfo(config.DISPLAY_TIMEZONE)
    events: list[Event] = []
    seen_ids: set[str] = set()
    horizon = now + config.FETCH_WINDOW

    for raw in raw_events:
        try:
            start_at, end_at = occurrence_times(raw, zone)
        except (ValueError, TypeError) as exc:
            log.warning("occurrence %s has an unparseable start %r: %s", raw.slug, raw.utc_start_raw, exc)
            counters.unparseable_time += 1
            continue

        if start_at > horizon:
            counters.beyond_horizon += 1
            continue

        event_id = make_event_id(config.SOURCE.id, occurrence_key(raw.slug, start_at))
        if event_id in seen_ids:
            log.warning("duplicate occurrence id %s, dropping the repeat", event_id)
            counters.duplicate_id += 1
            continue

        venue = _build_venue(raw)
        if venue is not None and not venue.has_coordinates:
            counters.no_venue_coordinates += 1

        market_day = is_market_day(raw)
        event = Event(
            id=event_id,
            title=raw.title,
            start_at=start_at,
            end_at=end_at,
            is_all_day=raw.all_day,
            venue=venue,
            categories=(Category.MARKET, Category.FOOD) if market_day else (Category.COMMUNITY, Category.MARKET),
            price=Price.free() if market_day and raw.states_no_price else Price.unknown(),
            image_url=raw.image_url,
            listing_url=raw.url,
            organizer=config.SOURCE.name,
            source=config.SOURCE,
        )

        if event.is_stale(now):
            counters.stale += 1
            continue

        seen_ids.add(event_id)
        events.append(event)

    events.sort(key=lambda e: (e.start_at, e.id))
    log.info("Oregon City Farmers Market normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters
