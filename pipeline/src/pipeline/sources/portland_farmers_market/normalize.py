"""Normalize Portland Farmers Market occurrences into the shared model.

Three decisions carry the weight here.

**Identity.** Every occurrence needs an id that is byte-identical run to run, because
client bookmarks key off it. The obvious candidate — the API's numeric `id` — is the
wrong one: for recurring series those are provisional ids that renumber whenever a
date is added to or removed from the series (see `fetch`). We use the series slug
plus the occurrence's Portland-local date, which is the same identity the upstream
per-occurrence URL encodes (`/event/king-farmers-market-3/2026-07-26/`) and is
unaffected by edits elsewhere in the season. Across the 110 records published at the
time of writing, that pair is unique.

**Price.** These are marked `Price.free()`, which is a deliberate exception to the
usual `Price.unknown()` default. Everywhere else we refuse to assert free without
evidence, and the reasoning holds here rather than being waived: a farmers market has
no admission — there is no gate, no ticket, and PFM's own records carry an empty
`cost` field. What costs money is the produce, not attending. "Free" in this app means
free to show up, which is unambiguously true of a farmers market.

**Kind.** The feed mixes the markets themselves with the musicians booked to play at
them, and both carry the market's name as their taxonomy term. We separate them by
comparing the title against the venue and category names rather than by keyword,
so a new market added upstream classifies correctly without a code change.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from ...common.log import get_logger
from ...common.models import Category, Event, Price, Venue, make_event_id
from . import config
from .fetch import RawMarketEvent

log = get_logger(__name__)

_VENUES_PATH = Path(__file__).with_name("venues.json")

# The plugin serializes UTC timestamps without an offset: "2026-07-26 17:00:00".
_UTC = ZoneInfo("UTC")

MAX_SUMMARY_CHARS = 400


def _load_venue_fallbacks() -> dict[str, tuple[float, float]]:
    """Coordinates for the venues the API itself leaves ungeocoded.

    The Events Calendar returns `geo_lat`/`geo_lng` for most PFM venues, so this
    table patches gaps rather than being the primary source. Geocoded once against
    Nominatim and baked in; never looked up at pipeline runtime.
    """
    try:
        raw = json.loads(_VENUES_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read %s (%s); ungeocoded venues will have no coordinates", _VENUES_PATH, exc)
        return {}
    return {name: (float(lat), float(lon)) for name, (lat, lon) in raw.items()}


VENUE_FALLBACK_COORDINATES = _load_venue_fallbacks()


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


def _parse_utc(value: str) -> datetime:
    """Read an offset-free UTC timestamp and return Portland local time."""
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_UTC)
    return moment.astimezone(ZoneInfo(config.DISPLAY_TIMEZONE))


def _strip_html(value: str | None) -> str | None:
    if not value:
        return None
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if len(text) > MAX_SUMMARY_CHARS:
        text = text[:MAX_SUMMARY_CHARS].rsplit(" ", 1)[0] + "\u2026"
    return text


def occurrence_id(slug: str, start_at: datetime) -> str:
    """Stable per-occurrence identity: series slug plus its local date.

    Deliberately not the API's numeric id, which is provisional for recurring
    series and renumbers when the season is edited.
    """
    return make_event_id(config.SOURCE.id, f"{slug}@{start_at.date().isoformat()}")


def is_the_market_itself(raw: RawMarketEvent) -> bool:
    """Distinguish a market day from a performer booked at that market.

    Both carry the market's name as their category, so the taxonomy cannot tell them
    apart. The market's own occurrences are titled exactly after their venue.
    """
    title = raw.title.strip().casefold()
    if raw.venue and raw.venue.name.strip().casefold() == title:
        return True
    return any(name.strip().casefold() == title for name in raw.categories)


def infer_categories(raw: RawMarketEvent) -> tuple[Category, ...]:
    if is_the_market_itself(raw):
        return (Category.MARKET, Category.FOOD)
    # PFM's only non-market listings are the live music program it books into the
    # markets. They are still market events, so both labels apply.
    return (Category.MUSIC, Category.MARKET)


def _build_venue(raw: RawMarketEvent) -> Venue | None:
    if raw.venue is None:
        return None
    latitude, longitude = raw.venue.latitude, raw.venue.longitude
    if latitude is None or longitude is None:
        fallback = VENUE_FALLBACK_COORDINATES.get(raw.venue.name)
        if fallback:
            latitude, longitude = fallback
    return Venue(
        name=raw.venue.name,
        address=raw.venue.address,
        city=raw.venue.city or "Portland",
        latitude=latitude,
        longitude=longitude,
    )


def normalize(raw_events: list[RawMarketEvent], *, now: datetime) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    events: list[Event] = []
    seen_ids: set[str] = set()
    horizon = now + config.FETCH_WINDOW

    for raw in raw_events:
        try:
            start_at = _parse_utc(raw.utc_start_raw)
        except (ValueError, TypeError) as exc:
            log.warning("occurrence %s has an unparseable start %r: %s", raw.slug, raw.utc_start_raw, exc)
            counters.unparseable_time += 1
            continue

        end_at = None
        if raw.utc_end_raw:
            try:
                end_at = _parse_utc(raw.utc_end_raw)
            except (ValueError, TypeError):
                log.warning("occurrence %s has an unparseable end %r", raw.slug, raw.utc_end_raw)

        if start_at > horizon:
            counters.beyond_horizon += 1
            continue

        event_id = occurrence_id(raw.slug, start_at)
        if event_id in seen_ids:
            # Two records claiming the same slug and date would silently overwrite
            # each other client-side; drop the second and say so.
            log.warning("duplicate occurrence id %s, dropping the repeat", event_id)
            counters.duplicate_id += 1
            continue

        venue = _build_venue(raw)
        if venue is not None and venue.latitude is None:
            counters.no_venue_coordinates += 1

        event = Event(
            id=event_id,
            title=raw.title,
            start_at=start_at,
            end_at=end_at,
            is_all_day=raw.all_day,
            summary=_strip_html(raw.excerpt_html),
            venue=venue,
            categories=infer_categories(raw),
            # Free to enter, with no gate and no ticket — see the module docstring.
            price=Price.free(),
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
    log.info("Portland Farmers Market normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters
