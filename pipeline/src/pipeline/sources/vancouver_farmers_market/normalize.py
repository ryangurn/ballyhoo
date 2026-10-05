"""Normalize Vancouver Farmers Market occurrences into the shared model.

**Venues.** The plugin's venue records here carry the whole address in the *name* field
(`"Vancouver Farmers Market, 605 Esther St, Vancouver, WA 98660, USA"`, or for the
musicians just `"605 Esther St, Vancouver, WA 98660"`) and no coordinates at all.
`venues.json` maps each upstream venue string to a clean name, address and coordinates,
geocoded once and baked in. A venue missing from the table still publishes, under its
upstream name and without a pin.

**Kind.** Market days are recognised by exact title, musicians by their category, and
anything else the market posts — Kids Bucks, a dance performance, the holiday market —
publishes as a community listing. Only those last carry a summary: the description
field is the right text for them and the wrong text for the other two.

**Price.** `Price.free()` for the markets, the music played at them, and anything else
held on the market grounds: there is no gate and no ticket, and every record here
carries an empty `cost`. Off the grounds — the holiday market at the Hilton, or a
listing with no venue at all — nothing upstream says whether entry is free, so the
price is unknown. A record that does state a cost is never marked free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ...common.log import get_logger
from ...common.models import Category, Event, Price, Venue, make_event_id
from ...common.tribe_events import TribeEvent, html_to_text, occurrence_key, occurrence_times
from . import config

log = get_logger(__name__)

_VENUES_PATH = Path(__file__).with_name("venues.json")


@dataclass(frozen=True)
class KnownVenue:
    venue: Venue
    is_market_grounds: bool


def _load_venues() -> dict[str, KnownVenue]:
    try:
        raw = json.loads(_VENUES_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read %s (%s); venues will publish as upstream names them", _VENUES_PATH, exc)
        return {}
    known: dict[str, KnownVenue] = {}
    for upstream_name, entry in raw.items():
        coordinates = entry.get("coordinates") or (None, None)
        known[upstream_name] = KnownVenue(
            venue=Venue(
                name=entry["name"],
                address=entry.get("address"),
                city=entry.get("city"),
                latitude=coordinates[0],
                longitude=coordinates[1],
            ),
            is_market_grounds=bool(entry.get("market_grounds")),
        )
    return known


KNOWN_VENUES = _load_venues()


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
    return raw.title in config.MARKET_TITLES


def is_music(raw: TribeEvent) -> bool:
    return config.MUSIC_CATEGORY in raw.categories


def _resolve_venue(raw: TribeEvent) -> KnownVenue | None:
    if raw.venue is None:
        return None
    known = KNOWN_VENUES.get(raw.venue.name)
    if known is not None:
        return known
    log.warning("venue %r is not in venues.json; publishing it without coordinates", raw.venue.name)
    return KnownVenue(
        venue=Venue(name=raw.venue.name, address=raw.venue.address, city=raw.venue.city or "Vancouver"),
        is_market_grounds=False,
    )


def infer_categories(raw: TribeEvent) -> tuple[Category, ...]:
    if is_market_day(raw):
        return (Category.MARKET, Category.FOOD)
    if is_music(raw):
        return (Category.MUSIC, Category.MARKET)
    return (Category.COMMUNITY, Category.MARKET)


def infer_price(raw: TribeEvent, venue: KnownVenue | None) -> Price:
    if not raw.states_no_price:
        return Price.unknown()
    if is_market_day(raw) or is_music(raw) or (venue is not None and venue.is_market_grounds):
        return Price.free()
    return Price.unknown()


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

        known = _resolve_venue(raw)
        if known is not None and not known.venue.has_coordinates:
            counters.no_venue_coordinates += 1

        event = Event(
            id=event_id,
            title=raw.title,
            start_at=start_at,
            end_at=end_at,
            is_all_day=raw.all_day,
            # A market day's description is only its street address, and a musician's
            # is the booking form performers fill in to get a slot. Neither describes
            # the event to someone attending it.
            summary=None if is_market_day(raw) or is_music(raw) else html_to_text(raw.description_html),
            venue=known.venue if known else None,
            categories=infer_categories(raw),
            price=infer_price(raw, known),
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
    log.info("Vancouver Farmers Market normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters
