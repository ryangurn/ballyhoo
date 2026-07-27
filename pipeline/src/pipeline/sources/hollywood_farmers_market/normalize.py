"""Normalize Hollywood Farmers Market into the shared model.

This source produces events from two different kinds of upstream statement, and they
are held to different standards.

**Dated listings** are read as published. Music items get the market's venue and
`Price.free()`: the collection is the market's own booked-music programme, played
inside a market that costs nothing to walk into. Special-event items get neither. That
is not caution for its own sake — their detail pages carry a schema.org Event whose
`location` is an empty string and whose `offers` is null, so the venue and the price
genuinely are not stated anywhere, and the collection mixes on-site days like
Strawberry Day with off-site benefit nights at a bar. Asserting the market's
coordinates for those would drop a wrong pin on the map, and asserting free would be
a guess about a fundraiser.

**The market itself** is never published as a dated listing anywhere on the site. It
exists as one sentence of prose on the homepage:

    MARKET HOURS April-December 19th : Every Saturday 8am-1pm
    January-March: 2nd and 4th Saturdays 9am-1pm

Those two rules are encoded in `config.MARKET_RULES` and expanded here into individual
dated events. Encoding beats parsing: a misparse of that sentence would publish a
market that is not open, which is worse than publishing nothing. The cost of encoding
is that it can go stale, so `fetch` reads the sentence back on every run and expansion
is skipped entirely if it no longer matches what the rules were derived from. A market
day's id is the market slug plus its date, so it is identical on every run and a
bookmark survives — nothing about it depends on when the pipeline happened to execute.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from ...common.log import get_logger
from ...common.models import Category, Event, Price, Venue, make_event_id
from ...common.recurrence import expand
from . import config
from .fetch import RawListingEvent, normalize_spaces

log = get_logger(__name__)

_VENUES_PATH = Path(__file__).with_name("venues.json")

# The stable identity of a market-day occurrence. Only the date varies.
MARKET_SLUG = "market"

_CLOCK = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?[Mm]\.?$")


def _load_venues() -> dict[str, tuple[float, float]]:
    """Coordinates for the market, geocoded once against Nominatim and baked in."""
    try:
        raw = json.loads(_VENUES_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read %s (%s); events will have no coordinates", _VENUES_PATH, exc)
        return {}
    return {name: (float(lat), float(lon)) for name, (lat, lon) in raw.items()}


VENUE_COORDINATES = _load_venues()


class NormalizationCounters:
    def __init__(self) -> None:
        self.unparseable_time = 0
        self.stale = 0
        self.beyond_horizon = 0
        self.market_days_expanded = 0
        self.market_rules_skipped = 0
        self.duplicate_id = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "dropped_unparseable_time": self.unparseable_time,
            "dropped_stale": self.stale,
            "dropped_beyond_horizon": self.beyond_horizon,
            "dropped_duplicate_id": self.duplicate_id,
            "market_days_expanded": self.market_days_expanded,
            "market_rules_skipped": self.market_rules_skipped,
        }


def parse_clock(value: str | None) -> time | None:
    """Read Squarespace's "10:00 AM".

    The listing separates the minutes from the meridiem with U+202F rather than a
    space; `normalize_spaces` has already folded that, so a plain match works here.
    """
    if not value:
        return None
    match = _CLOCK.match(normalize_spaces(value))
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(3).lower()
    if not 1 <= hour <= 12 or minute > 59:
        return None
    if meridiem == "a":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    return time(hour, minute)


def _market_venue() -> Venue:
    coordinates = VENUE_COORDINATES.get(config.VENUE_NAME)
    return Venue(
        name=config.VENUE_NAME,
        address=config.VENUE_ADDRESS,
        city="Portland",
        latitude=coordinates[0] if coordinates else None,
        longitude=coordinates[1] if coordinates else None,
    )


def market_hours_are_unchanged(hours_text: str | None) -> bool:
    """Whether the homepage still states the schedule the rules were encoded from."""
    if hours_text is None:
        return False
    return normalize_spaces(hours_text).casefold() == config.EXPECTED_HOURS_TEXT


def _listing_event(raw: RawListingEvent, zone: ZoneInfo) -> Event | None:
    try:
        start_day = date.fromisoformat(raw.start_date)
    except (ValueError, TypeError):
        return None

    start_clock = parse_clock(raw.start_clock)
    start_at = datetime.combine(start_day, start_clock or time(0, 0), tzinfo=zone)

    end_at = None
    end_clock = parse_clock(raw.end_clock)
    try:
        end_day = date.fromisoformat(raw.end_date) if raw.end_date else start_day
    except (ValueError, TypeError):
        end_day = start_day
    if end_clock or raw.end_date:
        candidate = datetime.combine(end_day, end_clock or time(0, 0), tzinfo=zone)
        if candidate > start_at:
            end_at = candidate

    is_music = raw.collection == "music-schedule"
    return Event(
        # Namespaced by collection: the two collections are separate slug spaces.
        id=make_event_id(config.SOURCE.id, f"{raw.collection}/{raw.slug}"),
        title=raw.title,
        start_at=start_at,
        end_at=end_at,
        is_all_day=start_clock is None,
        summary=raw.summary,
        # Music happens inside the market. Special events may not — their own
        # markup states no location, so we assert none.
        venue=_market_venue() if is_music else None,
        categories=(Category.MUSIC, Category.MARKET) if is_music else (Category.COMMUNITY, Category.MARKET),
        # Free for the music, which is played at a market with no admission.
        # Unknown for special events: the collection includes off-site benefit
        # nights, and nothing upstream states a price for any of them.
        price=Price.free() if is_music else Price.unknown(),
        image_url=raw.image_url,
        listing_url=raw.url,
        organizer=config.SOURCE.name,
        source=config.SOURCE,
    )


def _market_day_events(*, now: datetime, zone: ZoneInfo) -> list[Event]:
    today = now.astimezone(zone).date()
    occurrences = expand(
        config.MARKET_RULES,
        window_start=today,
        window_end=today + config.MARKET_EXPANSION_WINDOW,
        zone=zone,
    )
    venue = _market_venue()
    return [
        Event(
            # Slug plus date, so the id is a property of the occurrence and not of
            # the run that produced it.
            id=make_event_id(config.SOURCE.id, f"{MARKET_SLUG}@{occurrence.date_key}"),
            title=config.MARKET_TITLE,
            start_at=occurrence.start_at,
            end_at=occurrence.end_at,
            summary=(
                "Neighborhood farmers market on NE Hancock, with produce, prepared food and live music. "
                "Free to attend."
            ),
            venue=venue,
            categories=(Category.MARKET, Category.FOOD),
            # No gate and no ticket; see the module docstring.
            price=Price.free(),
            listing_url=config.HOME_URL,
            organizer=config.SOURCE.name,
            source=config.SOURCE,
        )
        for occurrence in occurrences
    ]


def normalize(
    raw_events: list[RawListingEvent],
    *,
    hours_text: str | None,
    now: datetime,
) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    zone = ZoneInfo(config.TIMEZONE)
    events: list[Event] = []
    horizon = now + config.FETCH_WINDOW

    for raw in raw_events:
        event = _listing_event(raw, zone)
        if event is None:
            log.warning("listing %s/%s has an unparseable date %r", raw.collection, raw.slug, raw.start_date)
            counters.unparseable_time += 1
            continue
        if event.start_at > horizon:
            counters.beyond_horizon += 1
            continue
        if event.is_stale(now):
            counters.stale += 1
            continue
        events.append(event)

    if market_hours_are_unchanged(hours_text):
        market_days = _market_day_events(now=now, zone=zone)
        counters.market_days_expanded = len(market_days)
        events.extend(market_days)
    else:
        # The encoded rules are only trustworthy while the sentence they came from
        # is unchanged. Publishing a market that may not be open is worse than
        # publishing only the dated listings.
        counters.market_rules_skipped = len(config.MARKET_RULES)
        log.warning(
            "homepage market hours changed (read %r, expected %r); "
            "skipping market-day expansion until the rules in config are updated",
            hours_text,
            config.EXPECTED_HOURS_TEXT,
        )

    deduped: list[Event] = []
    seen_ids: set[str] = set()
    for event in events:
        if event.id in seen_ids:
            counters.duplicate_id += 1
            continue
        seen_ids.add(event.id)
        deduped.append(event)

    deduped.sort(key=lambda e: (e.start_at, e.id))
    log.info("Hollywood Farmers Market normalized %d events (%s)", len(deduped), counters.as_dict())
    return deduped, counters
