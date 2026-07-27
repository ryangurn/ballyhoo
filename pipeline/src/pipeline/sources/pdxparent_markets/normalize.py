"""Normalize PDX Parent's market roundup into dated events.

Each market arrives as a name, an address and a sentence. `schedule.parse` turns the
sentence into recurrence rules, `common.recurrence.expand` turns those into dates, and
this module turns the dates into events.

**Identity.** A market's id is a slug derived from its name plus the occurrence date.
The name is the only stable handle the roundup offers — there are no upstream ids, and
the link, the address and the wording all get edited — and it is what a reader would
consider the thing being bookmarked. Nothing in the id depends on when the pipeline ran
or on where the market fell in the page, so a bookmark survives both a re-run and a
reordering of the listicle. Two entries for one market on different weekdays (Troutdale
runs Fridays and Sundays) share a slug and are separated by their dates.

**Free-ness.** `Price.free()`, on the same grounds as the other market sources: a
farmers market has no gate and no ticket, and the thing that costs money is the
produce rather than attending.

**What is deliberately not asserted.** Coordinates come from a table geocoded once
against Nominatim and verified to be in the right city. Where that verification failed
the market still publishes, with no coordinates, rather than carrying a pin that might
be in the wrong town — the roundup gives addresses like "NE Dekum and NE Durham" and a
same-named street elsewhere in the metro is an easy and invisible way to be wrong.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ...common.log import get_logger
from ...common.models import Category, Event, Price, Venue, make_event_id
from ...common.recurrence import expand
from . import config
from .fetch import RawMarket
from .schedule import parse as parse_schedule

log = get_logger(__name__)

_VENUES_PATH = Path(__file__).with_name("venues.json")


def _load_venues() -> dict[str, tuple[float, float]]:
    """Coordinates geocoded once against Nominatim and baked in.

    Only entries whose result was verified to be in the expected city are present;
    the rest were dropped rather than guessed at.
    """
    try:
        raw = json.loads(_VENUES_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read %s (%s); markets will have no coordinates", _VENUES_PATH, exc)
        return {}
    return {name: (float(lat), float(lon)) for name, (lat, lon) in raw.items()}


VENUE_COORDINATES = _load_venues()


class NormalizationCounters:
    def __init__(self) -> None:
        self.covered_elsewhere = 0
        self.unparseable_schedule = 0
        self.no_occurrences = 0
        self.skipped_dates = 0
        self.stale = 0
        self.duplicate_id = 0
        self.no_venue_coordinates = 0
        self.markets_expanded = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "skipped_covered_elsewhere": self.covered_elsewhere,
            "dropped_unparseable_schedule": self.unparseable_schedule,
            "dropped_no_occurrences_in_window": self.no_occurrences,
            "dropped_explicitly_skipped_dates": self.skipped_dates,
            "dropped_stale": self.stale,
            "dropped_duplicate_id": self.duplicate_id,
            "without_venue_coordinates": self.no_venue_coordinates,
            "markets_expanded": self.markets_expanded,
        }


def market_slug(name: str) -> str:
    """A stable, readable key derived from the market's name.

    Apostrophes are deleted rather than treated as separators, and that is not
    cosmetic. ASCII folding drops a curly apostrophe entirely but keeps a straight
    one, so "Camas Farmer's Market" would slug as `camas-farmer-s-market` while
    "Camas Farmer's Market" with a typographic quote slugged as
    `camas-farmers-market`. Someone changing one character upstream would orphan
    every bookmark for that market. Removing both forms first makes the two agree.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    folded = re.sub(r"['\u2018\u2019\u02bc]", "", folded)
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return slug or "market"


def is_covered_elsewhere(market: RawMarket) -> bool:
    """Whether the market's operator publishes a real calendar we already read."""
    domain = market.link_domain
    return any(domain == d or domain.endswith(f".{d}") for d in config.COVERED_ELSEWHERE_DOMAINS)


def _build_venue(market: RawMarket) -> Venue:
    coordinates = VENUE_COORDINATES.get(market.name)
    return Venue(
        name=market.name,
        address=market.address,
        city="Portland",
        latitude=coordinates[0] if coordinates else None,
        longitude=coordinates[1] if coordinates else None,
    )


def normalize(markets: list[RawMarket], *, now: datetime) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    zone = ZoneInfo(config.TIMEZONE)
    today = now.astimezone(zone).date()
    window_end = today + config.EXPANSION_WINDOW

    events: list[Event] = []
    seen_ids: set[str] = set()
    problems: list[str] = []

    for market in markets:
        if is_covered_elsewhere(market):
            # Its operator publishes real dates; inferring our own would duplicate
            # them and could contradict them.
            counters.covered_elsewhere += 1
            continue

        parsed = parse_schedule(market.schedule_line)
        problems.extend(f"{market.name}: {p}" for p in parsed.problems)
        if not parsed.is_usable:
            counters.unparseable_schedule += 1
            log.warning("could not read a schedule for %s from %r", market.name, market.schedule_line[:90])
            continue

        occurrences = expand(
            parsed.rules,
            window_start=today,
            window_end=window_end,
            zone=zone,
            max_occurrences=config.MAX_OCCURRENCES_PER_MARKET,
        )
        if not occurrences:
            counters.no_occurrences += 1
            continue

        slug = market_slug(market.name)
        venue = _build_venue(market)
        if venue.latitude is None:
            counters.no_venue_coordinates += 1

        expanded_any = False
        for occurrence in occurrences:
            if (occurrence.day.month, occurrence.day.day) in parsed.skipped_dates:
                # The roundup says so explicitly: "No market July 10".
                counters.skipped_dates += 1
                continue

            event_id = make_event_id(config.SOURCE.id, f"{slug}@{occurrence.date_key}")
            if event_id in seen_ids:
                # Troutdale is listed twice; overlapping rules would collide here.
                counters.duplicate_id += 1
                continue

            event = Event(
                id=event_id,
                title=market.name,
                start_at=occurrence.start_at,
                end_at=occurrence.end_at,
                summary=market.schedule_line if len(market.schedule_line) <= 300 else None,
                venue=venue,
                categories=(Category.MARKET, Category.FOOD),
                # No gate and no ticket; see the module docstring.
                price=Price.free(),
                listing_url=market.url or config.ROUNDUP_URL,
                organizer=market.name,
                source=config.SOURCE,
            )
            if event.is_stale(now):
                counters.stale += 1
                continue

            seen_ids.add(event_id)
            events.append(event)
            expanded_any = True

        if expanded_any:
            counters.markets_expanded += 1

    if problems:
        log.info("schedule fragments not used (%d): %s", len(problems), "; ".join(problems[:8]))

    events.sort(key=lambda e: (e.start_at, e.id))
    log.info("PDX Parent normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters
