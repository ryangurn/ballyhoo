"""Normalize the Hillsboro Farmers' Markets events page into the shared model.

**Identity.** A market day's id is the market's key plus its date. Not the Squarespace
item slug: this operator builds each season by duplicating the previous item, so slugs
are chains of copy suffixes (`orenco-station-sffap-3p8ad-2mjxj-...-y722y-54f7p`) and a
re-duplicated season would orphan every bookmark. Market plus date is what a reader is
bookmarking anyway.

**Closures.** A cancellation is published as its own item rather than by removing the
market day — sometimes alongside the original, sometimes in place of it. A closure
naming a market suppresses that market's day; one naming none ("HFM Closed - Labor
Day") suppresses every market that date. Publishing a market that is not open is worse
than missing one.

**Price.** `Price.free()`, on the same grounds as every market source: no gate and no
ticket.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from ...common.log import get_logger
from ...common.models import Category, Event, Price, Venue, make_event_id
from ...common.squarespace import EventListItem, normalize_spaces, parse_clock
from . import config

log = get_logger(__name__)

_VENUES_PATH = Path(__file__).with_name("venues.json")


def _load_coordinates() -> dict[str, tuple[float, float]]:
    """Coordinates per market, geocoded once against OpenStreetMap and baked in."""
    try:
        raw = json.loads(_VENUES_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read %s (%s); markets will have no coordinates", _VENUES_PATH, exc)
        return {}
    return {key: (float(lat), float(lon)) for key, (lat, lon) in raw.items()}


COORDINATES = _load_coordinates()


class NormalizationCounters:
    def __init__(self) -> None:
        self.unparseable_date = 0
        self.unrecognised = 0
        self.closed = 0
        self.stale = 0
        self.beyond_horizon = 0
        self.duplicate_id = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "dropped_unparseable_date": self.unparseable_date,
            "dropped_unrecognised_title": self.unrecognised,
            "dropped_closed": self.closed,
            "dropped_stale": self.stale,
            "dropped_beyond_horizon": self.beyond_horizon,
            "dropped_duplicate_id": self.duplicate_id,
        }


def _fold(title: str) -> str:
    return normalize_spaces(title).casefold().replace("\u2019", "'").replace("\u2018", "'")


def market_for(title: str) -> config.Market | None:
    folded = _fold(title)
    for market in config.MARKETS:
        if any(fragment in folded for fragment in market.title_fragments):
            return market
    return None


def is_closure(title: str) -> bool:
    folded = _fold(title)
    return any(marker in folded for marker in config.CLOSURE_MARKERS)


def is_harvest_festival(title: str) -> bool:
    return _fold(title).lstrip("* ").startswith(config.HARVEST_FESTIVAL_PREFIX)


def _venue(market: config.Market) -> Venue:
    coordinates = COORDINATES.get(market.key)
    return Venue(
        name=market.title,
        address=market.address,
        city="Hillsboro",
        latitude=coordinates[0] if coordinates else None,
        longitude=coordinates[1] if coordinates else None,
    )


def _market_day(item: EventListItem, market: config.Market, day: date, zone: ZoneInfo) -> Event:
    start_clock = parse_clock(item.start_clock)
    end_clock = parse_clock(item.end_clock)
    start_at = datetime.combine(day, start_clock or time(0, 0), tzinfo=zone)
    end_at = datetime.combine(day, end_clock, tzinfo=zone) if end_clock else None
    if end_at is not None and end_at <= start_at:
        end_at = None

    title = f"Harvest Festival at {market.title}" if is_harvest_festival(item.title) else market.title
    return Event(
        id=make_event_id(config.SOURCE.id, f"{market.key}@{day.isoformat()}"),
        title=title,
        start_at=start_at,
        end_at=end_at,
        is_all_day=start_clock is None,
        summary=item.summary,
        venue=_venue(market),
        categories=(Category.MARKET, Category.FOOD),
        # No gate and no ticket; see the module docstring.
        price=Price.free(),
        image_url=item.image_url,
        listing_url=item.url,
        organizer=config.SOURCE.name,
        source=config.SOURCE,
    )


def normalize(items: list[EventListItem], *, now: datetime) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    zone = ZoneInfo(config.TIMEZONE)
    horizon = now + config.FETCH_WINDOW

    dated: list[tuple[EventListItem, date]] = []
    for item in items:
        try:
            dated.append((item, date.fromisoformat(item.start_date)))
        except ValueError:
            log.warning("item %r has an unparseable date %r", item.title, item.start_date)
            counters.unparseable_date += 1

    # A closure for no particular market is recorded against None and closes them all.
    closures: set[tuple[str | None, date]] = set()
    for item, day in dated:
        if is_closure(item.title):
            market = market_for(item.title)
            closures.add((market.key if market else None, day))

    by_id: dict[str, Event] = {}
    for item, day in dated:
        if is_closure(item.title):
            counters.closed += 1
            continue
        market = market_for(item.title)
        if market is None:
            log.warning("no market matches the title %r; dropping it", item.title)
            counters.unrecognised += 1
            continue
        if (market.key, day) in closures or (None, day) in closures:
            counters.closed += 1
            continue

        event = _market_day(item, market, day, zone)
        if event.start_at > horizon:
            counters.beyond_horizon += 1
            continue
        if event.is_stale(now):
            counters.stale += 1
            continue

        existing = by_id.get(event.id)
        if existing is not None:
            counters.duplicate_id += 1
            # Two items for one market day: keep the one that says it is the festival.
            if not is_harvest_festival(item.title):
                continue
        by_id[event.id] = event

    events = sorted(by_id.values(), key=lambda e: (e.start_at, e.id))
    log.info("Hillsboro Farmers' Markets normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters
