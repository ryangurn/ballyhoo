"""Normalize Eventbrite search results into the shared model.

What the live payload forces, in rough order of how much trouble each caused:

  - Timestamps arrive as a local date, a local clock, and an IANA zone, with no offset
    anywhere. The zone is authoritative and the offset is resolved from it, never
    assumed. Evidence: 1,731 `event_sales_status` local/UTC pairs round-trip through
    `ZoneInfo` exactly, and an event page's schema.org `startDate` reproduces what this
    module computes, offset included.
  - Roughly 5% of Portland-area results declare a non-Pacific zone. Those are dropped;
    `config.EXPECTED_TIMEZONE` explains why at length.
  - `ticket_availability.is_free` is an explicit per-event boolean, which is better
    evidence than the `price=free` search filter because it is also present on events
    the filtered pass never returned. Across 881 events returned by the free filter the
    two agreed 100%, and a run reports any disagreement.
  - Eventbrite's "Portland" reaches Newport, Salem and Centralia, so events are filtered
    to within 40 miles. Coordinates are present on every result, so this is exact.
  - Prices arrive as `{"major_value": "12.00", "value": 1200}`. `value` is minor units.
"""

from __future__ import annotations

from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...common.log import get_logger
from ...common.models import Category, Event, Price, Venue, make_event_id
from . import config
from .fetch import RawEvent, RawPrice, RawVenue

log = get_logger(__name__)

# Eventbrite's published category vocabulary, all 21 values observed across a
# 1,434-event sample. Exactly one is attached per event.
CATEGORY_MAP: dict[str, Category] = {
    "music": Category.MUSIC,
    "performing & visual arts": Category.ARTS,
    "fashion & beauty": Category.ARTS,
    "film, media & entertainment": Category.FILM,
    "food & drink": Category.FOOD,
    "health & wellness": Category.WELLNESS,
    "science & technology": Category.TECH,
    "travel & outdoor": Category.OUTDOORS,
    "sports & fitness": Category.SPORTS,
    "government & politics": Category.CIVIC,
    "family & education": Category.FAMILY,
    "school activities": Category.FAMILY,
    "community & culture": Category.COMMUNITY,
    "charity & causes": Category.COMMUNITY,
    "religion & spirituality": Category.COMMUNITY,
    "home & lifestyle": Category.COMMUNITY,
    "auto, boat & air": Category.COMMUNITY,
    "seasonal & holiday": Category.COMMUNITY,
    "hobbies & special interest": Category.COMMUNITY,
    # 26% of Portland's Eventbrite listings, and a genuine mixed bag: career fairs,
    # networking breakfasts, certification bootcamps. Nothing narrower fits.
    "business & professional": Category.COMMUNITY,
    "other": Category.COMMUNITY,
}
DEFAULT_CATEGORY = Category.COMMUNITY

# `EventbriteFormat` is a second, orthogonal tag. It is consulted only when the category
# says nothing useful — absent, or the literal "Other" — because format and category
# disagree often enough that letting format win would be worse than the fallback. A
# board game night is tagged "Game or Competition" but is not a sporting event.
FORMAT_MAP: dict[str, Category] = {
    "concert or performance": Category.MUSIC,
    "party or social gathering": Category.NIGHTLIFE,
    "screening": Category.FILM,
    "race or endurance event": Category.SPORTS,
    "festival or fair": Category.COMMUNITY,
}

_unmapped_seen: set[str] = set()


class NormalizationCounters:
    def __init__(self) -> None:
        self.no_title = 0
        self.no_start = 0
        self.unparseable_time = 0
        self.no_timezone = 0
        self.timezone_conflict = 0
        self.outside_metro = 0
        self.online = 0
        self.cancelled = 0
        self.stale = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "dropped_no_title": self.no_title,
            "dropped_no_start": self.no_start,
            "dropped_unparseable_time": self.unparseable_time,
            "dropped_no_timezone": self.no_timezone,
            "dropped_timezone_conflict": self.timezone_conflict,
            "dropped_outside_metro": self.outside_metro,
            "dropped_online": self.online,
            "dropped_cancelled": self.cancelled,
            "dropped_stale": self.stale,
        }


def _miles_from_portland(latitude: float, longitude: float) -> float:
    """Great-circle distance in miles. Haversine is ample at metro scale."""
    radius = 3958.8
    lat1, lat2 = radians(config.PORTLAND_LATITUDE), radians(latitude)
    dlat = lat2 - lat1
    dlon = radians(longitude - config.PORTLAND_LONGITUDE)
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * radius * asin(sqrt(a))


def is_in_metro(venue: RawVenue | None) -> bool:
    """Whether the venue is close enough to Portland to belong in the feed.

    Every observed result carried coordinates, so the coordinate-less branch is a
    guard rather than a real path; it keeps the event, on the same reasoning DoPDX
    uses — an unplaceable venue is likelier a data gap than a distant city.
    """
    if venue is None or venue.latitude is None or venue.longitude is None:
        return True
    return _miles_from_portland(venue.latitude, venue.longitude) <= config.MAX_DISTANCE_MILES


def infer_categories(category: str | None, event_format: str | None = None) -> tuple[Category, ...]:
    key = (category or "").strip().lower()
    if key and key != "other":
        if mapped := CATEGORY_MAP.get(key):
            return (mapped,)
        if key not in _unmapped_seen:
            _unmapped_seen.add(key)
            log.info("Eventbrite category %r has no mapping; using %s", category, DEFAULT_CATEGORY.value)
        return (DEFAULT_CATEGORY,)

    if mapped := FORMAT_MAP.get((event_format or "").strip().lower()):
        return (mapped,)
    return (DEFAULT_CATEGORY,)


def unmapped_categories() -> list[str]:
    return sorted(_unmapped_seen)


def _local_datetime(day: str, clock: str | None, zone: ZoneInfo) -> datetime:
    """Combine Eventbrite's separate date and clock fields into an aware datetime.

    A missing clock becomes local midnight, and the caller marks the event all-day so
    the client does not render a 12:00 AM start that Eventbrite never stated.
    """
    return datetime.fromisoformat(f"{day}T{clock or '00:00'}:00").replace(tzinfo=zone)


def _build_venue(raw: RawVenue | None) -> Venue | None:
    if raw is None:
        return None
    name = raw.name or raw.address
    if not name:
        return None
    return Venue(
        name=name,
        address=raw.address,
        city=raw.city,
        latitude=raw.latitude,
        longitude=raw.longitude,
    )


def _build_price(raw: RawPrice) -> Price:
    """Free only where Eventbrite says free; a figure only where Eventbrite states one."""
    if raw.is_free is True:
        return Price.free()
    if raw.is_free is not False or raw.minimum is None:
        # Either the expansion did not come back or the event is paid with no published
        # figure — 12 of 1,434 sampled. Unknown, never free.
        return Price.unknown()
    if raw.currency not in (None, "USD"):
        # No non-USD event has been observed in Portland. If one appears, its amount is
        # withheld rather than rendered behind a dollar sign in the client.
        log.info("withholding a %s price on an event; only USD amounts are published", raw.currency)
        return Price.unknown()

    maximum = raw.maximum if raw.maximum is not None else raw.minimum
    if raw.minimum == 0 and maximum == 0:
        # Upstream contradicts itself: not flagged free, yet every ticket class is
        # $0.00. Around 2% of a run, and they read like donation or register-to-attend
        # events — trail parties, community meals. Honouring `is_free` alone would badge
        # them "$0" while the app treats them as paid, which is worse than saying
        # nothing. We decline to claim free on upstream's own denial, and decline to
        # publish a figure that means nothing.
        return Price.unknown()
    # A zero *minimum* against a real maximum is different: a free tier alongside paid
    # ones is a genuine range worth showing.
    return Price(is_free=False, min=raw.minimum, max=maximum)


def normalize(
    raw_events: list[RawEvent],
    *,
    now: datetime,
) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    events: list[Event] = []
    free_filter_disagreements = 0

    for raw in raw_events:
        if not raw.name:
            counters.no_title += 1
            continue
        if raw.is_cancelled:
            counters.cancelled += 1
            continue
        if raw.is_online:
            # A webinar has no walkable venue, which is the whole premise of the app.
            counters.online += 1
            continue

        venue = _build_venue(raw.venue)
        if not is_in_metro(raw.venue):
            counters.outside_metro += 1
            continue

        if not raw.timezone:
            counters.no_timezone += 1
            continue
        if raw.timezone != config.EXPECTED_TIMEZONE:
            # In-metro but on another region's clock. See config.EXPECTED_TIMEZONE.
            counters.timezone_conflict += 1
            continue

        try:
            zone = ZoneInfo(raw.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            counters.no_timezone += 1
            continue

        if not raw.start_date:
            counters.no_start += 1
            continue

        try:
            start_at = _local_datetime(raw.start_date, raw.start_time, zone)
        except ValueError as exc:
            log.warning("event %s has an unparseable start %r %r: %s",
                        raw.event_id, raw.start_date, raw.start_time, exc)
            counters.unparseable_time += 1
            continue

        end_at = None
        if raw.end_date:
            try:
                candidate = _local_datetime(raw.end_date, raw.end_time, zone)
                # Multi-day listings occasionally carry an end before their start.
                end_at = candidate if candidate >= start_at else None
            except ValueError:
                log.warning("event %s has an unparseable end", raw.event_id)

        price = _build_price(raw.price)
        if raw.matched_free_filter and not price.is_free:
            # The two independent claims about free-ness parted company. Worth a line
            # in the log: it would mean the per-event field can no longer be trusted.
            free_filter_disagreements += 1

        event = Event(
            id=make_event_id(config.SOURCE.id, raw.event_id),
            title=raw.name,
            start_at=start_at,
            end_at=end_at,
            is_all_day=raw.start_time is None,
            summary=raw.summary,
            venue=venue,
            categories=infer_categories(raw.category, raw.event_format),
            price=price,
            image_url=raw.image_url,
            # Both point at the public event page. Eventbrite's own `tickets_url` is a
            # `/checkout-external` link, which robots.txt disallows and which renders as
            # a bare checkout frame; the event page carries the same widget in context.
            listing_url=raw.url,
            ticket_url=raw.url,
            organizer=raw.organizer,
            source=config.SOURCE,
        )

        if event.is_stale(now):
            counters.stale += 1
            continue

        events.append(event)

    events.sort(key=lambda e: e.start_at)
    free_count = sum(1 for e in events if e.price.is_free)
    log.info(
        "Eventbrite normalized %d events, %d free (%s)",
        len(events), free_count, counters.as_dict(),
    )
    if free_filter_disagreements:
        log.warning(
            "%d event(s) came back under the free filter but are not flagged free per event; "
            "the two signals normally agree exactly",
            free_filter_disagreements,
        )
    return events, counters
