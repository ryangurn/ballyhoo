"""Expand each market's encoded schedule into dated events.

A market is expanded only if every one of its statements still appears on the page it
was copied from. Otherwise its days are withheld for this run and the reason is logged,
naming the page to re-read. The other markets are unaffected.

**Identity.** A market's slug plus the occurrence date. Nothing in it depends on when
the pipeline ran or where the market sits in `MARKETS`, so a bookmark survives both.

**Precedence.** An explicitly listed day (`Market.days`) replaces a rule-derived one on
the same date, since it is the more specific statement; `Market.skipped` removes a date
outright.

**Price.** `Price.free()`, on the same grounds as every market source: no gate and no
ticket, and what costs money is the produce rather than attending.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from ...common.log import get_logger
from ...common.models import Category, Event, Price, Venue, make_event_id
from ...common.recurrence import expand
from . import config
from .fetch import squash
from .markets import MARKETS, Market

log = get_logger(__name__)

_VENUES_PATH = Path(__file__).with_name("venues.json")


def _load_coordinates() -> dict[str, tuple[float, float]]:
    """Coordinates per market slug, geocoded once against OpenStreetMap and baked in.

    Each was checked against the market's own stated address, in the expected city.
    """
    try:
        raw = json.loads(_VENUES_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read %s (%s); markets will have no coordinates", _VENUES_PATH, exc)
        return {}
    return {slug: (float(lat), float(lon)) for slug, (lat, lon) in raw.items()}


COORDINATES = _load_coordinates()


class NormalizationCounters:
    def __init__(self) -> None:
        self.markets_expanded = 0
        self.markets_out_of_season = 0
        self.markets_statement_changed = 0
        self.markets_page_unreadable = 0
        self.skipped_dates = 0
        self.stale = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "markets_expanded": self.markets_expanded,
            "markets_out_of_season": self.markets_out_of_season,
            "markets_statement_changed": self.markets_statement_changed,
            "markets_page_unreadable": self.markets_page_unreadable,
            "dropped_explicitly_skipped_dates": self.skipped_dates,
            "dropped_stale": self.stale,
        }


@dataclass(frozen=True)
class MarketOccurrence:
    day: date
    start_at: datetime
    end_at: datetime | None
    title: str


def check_statements(market: Market, pages: dict[str, str | None]) -> str | None:
    """None if every statement still holds, otherwise why not."""
    for statement in market.statements:
        text = pages.get(statement.url)
        if text is None:
            return f"page unreadable: {statement.url}"
        if squash(statement.text) not in text:
            return f"statement no longer on {statement.url}: {statement.text!r}"
    return None


def _at(day: date, clock: time | None, zone: ZoneInfo) -> datetime | None:
    return datetime.combine(day, clock, tzinfo=zone) if clock else None


def occurrences(market: Market, *, today: date, zone: ZoneInfo) -> list[MarketOccurrence]:
    window_end = today + config.EXPANSION_WINDOW
    if market.through is not None:
        window_end = min(window_end, market.through)
    if window_end < today:
        return []

    by_day: dict[date, MarketOccurrence] = {}
    for occurrence in expand(
        list(market.rules),
        window_start=today,
        window_end=window_end,
        zone=zone,
        max_occurrences=config.MAX_OCCURRENCES_PER_MARKET,
    ):
        by_day[occurrence.day] = MarketOccurrence(occurrence.day, occurrence.start_at, occurrence.end_at, market.name)

    for listed in market.days:
        if today <= listed.day <= window_end:
            start_at = datetime.combine(listed.day, listed.opens, tzinfo=zone)
            end_at = _at(listed.day, listed.closes, zone)
            by_day[listed.day] = MarketOccurrence(listed.day, start_at, end_at, listed.title or market.name)

    return [by_day[day] for day in sorted(by_day)]


def _venue(market: Market) -> Venue:
    coordinates = COORDINATES.get(market.slug)
    return Venue(
        name=market.name,
        address=market.address,
        city=market.city,
        latitude=coordinates[0] if coordinates else None,
        longitude=coordinates[1] if coordinates else None,
    )


def normalize(
    pages: dict[str, str | None],
    *,
    now: datetime,
    markets: tuple[Market, ...] = MARKETS,
) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    zone = ZoneInfo(config.TIMEZONE)
    today = now.astimezone(zone).date()
    events: list[Event] = []

    for market in markets:
        problem = check_statements(market, pages)
        if problem is not None:
            if problem.startswith("page unreadable"):
                counters.markets_page_unreadable += 1
            else:
                counters.markets_statement_changed += 1
            log.warning("withholding %s until markets.py is updated (%s)", market.name, problem)
            continue

        venue = _venue(market)
        published = 0
        for occurrence in occurrences(market, today=today, zone=zone):
            if occurrence.day in market.skipped:
                counters.skipped_dates += 1
                continue
            event = Event(
                id=make_event_id(config.SOURCE.id, f"{market.slug}@{occurrence.day.isoformat()}"),
                title=occurrence.title,
                start_at=occurrence.start_at,
                end_at=occurrence.end_at,
                venue=venue,
                categories=(Category.MARKET, Category.FOOD),
                # No gate and no ticket; see the module docstring.
                price=Price.free(),
                listing_url=market.listing_url,
                organizer=market.name,
                source=config.SOURCE,
            )
            if event.is_stale(now):
                counters.stale += 1
                continue
            events.append(event)
            published += 1

        if published:
            counters.markets_expanded += 1
        else:
            counters.markets_out_of_season += 1

    events.sort(key=lambda e: (e.start_at, e.id))
    log.info("neighborhood markets normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters
