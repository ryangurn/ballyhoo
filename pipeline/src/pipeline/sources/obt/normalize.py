"""Normalize OBT's Tessitura listing into the shared model.

One event per performance, not one per production. A ballet season is a handful of
productions each running many nights — eighteen Nutcrackers over three weeks in the
current listing — and a production is not a thing anyone can attend. The app answers
"what is on tonight", which only a dated occurrence can answer. The cost is that a
long run dominates its dates, but collapsing a run into one event would mean either
inventing a date or publishing something nobody can buy a ticket to.

That choice is only safe because Tessitura gives every performance its own immutable
integer key, so per-occurrence identity comes free and stays byte-identical across
runs. Deriving an id from the title would have collapsed all eighteen Nutcrackers
onto one bookmark; deriving it from title-plus-date would break the moment OBT
renamed a production mid-season.

Three fields cannot be filled honestly from what Tessitura exposes:

  price     Nothing in the API carries one, and the pages that do are behind the
            bot control documented in `tessitura.py`. Ballet tickets are plainly not
            free, so `Price.unknown()` is the only defensible value. For the record,
            the detail pages priced the current Nutcracker run at $39-$168 all-in.
  end_at    Never published. A two-hour guess would be a fabrication.
  venue     Comes from the marketing site via `fetch.py`, not from Tessitura.
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
from .fetch import RawOBTSeason, match_key
from .tessitura import Production, TimestampDisagreement

log = get_logger(__name__)

_VENUES_PATH = Path(__file__).with_name("venues.json")

# Ballet is unambiguously ARTS. Nothing in the feed justifies a second category:
# family-friendly programming is not flagged upstream, and inferring it from titles
# would be guesswork dressed up as data.
CATEGORIES = (Category.ARTS,)

# A card shows a couple of lines. The full description runs to several paragraphs of
# marketing copy plus a photo credit.
SUMMARY_MAX_CHARS = 300


def _load_venues() -> dict[str, dict]:
    """Venue geometry, geocoded once via Nominatim and baked in.

    Keyed by the casefolded venue name as the season page spells it. OBT plays a
    stable handful of houses, so a lookup table beats a geocoding call per run.
    """
    try:
        raw = json.loads(_VENUES_PATH.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read %s (%s); OBT events will have no coordinates", _VENUES_PATH, exc)
        return {}
    return raw


VENUES = _load_venues()


class NormalizationCounters:
    def __init__(self) -> None:
        self.hidden = 0
        self.timestamp_disagreement = 0
        self.unparseable_time = 0
        self.stale = 0
        self.no_venue_name = 0
        self.no_venue_coordinates = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "dropped_hidden_upstream": self.hidden,
            "dropped_timestamp_disagreement": self.timestamp_disagreement,
            "dropped_unparseable_time": self.unparseable_time,
            "dropped_stale": self.stale,
            "without_venue_name": self.no_venue_name,
            "without_venue_coordinates": self.no_venue_coordinates,
        }


def strip_html(value: str | None) -> str | None:
    """Flatten Tessitura's stored HTML description to a plain summary."""
    if not value:
        return None
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    text = " ".join(text.split())
    if not text:
        return None
    # Trailing photo credits ("photo: Hart Isaacoff ... by Jingzi Zhao") are set in
    # 8px type on the site and read as noise in a summary.
    text = re.sub(r"\s*photo:\s.*$", "", text, flags=re.IGNORECASE)
    if len(text) > SUMMARY_MAX_CHARS:
        cut = text[:SUMMARY_MAX_CHARS].rsplit(" ", 1)[0]
        text = f"{cut}\u2026"
    return text or None


def build_summary(description: str | None, product_type: str | None) -> str | None:
    """Lead with what distinguishes this showing from the rest of its run.

    `productTypeName` is the only per-performance descriptor Tessitura publishes, and
    it carries real information: "Sensory Friendly/Recorded Music" is a materially
    different event from "w/OBT Orchestra" on the same stage in the same week.
    """
    body = strip_html(description)
    if product_type and body:
        return f"{product_type} \u2014 {body}"
    return product_type or body


def build_venue(production_title: str, venues_by_title: dict[str, str]) -> Venue | None:
    name = venues_by_title.get(match_key(production_title))
    if not name:
        return None
    known = VENUES.get(name.casefold())
    if known is None:
        return Venue(name=name)
    return Venue(
        name=known.get("name", name),
        address=known.get("address"),
        city=known.get("city"),
        latitude=known.get("latitude"),
        longitude=known.get("longitude"),
    )


def best_image(image_url: str | None, renditions: list[tuple[int, str]]) -> str | None:
    """Smallest rendition still wide enough for a card; the original if none is.

    Same rule as the Ticketmaster source and for the same reason — see
    `fetch.fetch_image_renditions`.
    """
    if not image_url:
        return None
    big_enough = [(w, u) for w, u in renditions if w >= config.MIN_IMAGE_WIDTH]
    if big_enough:
        return min(big_enough)[1]
    return image_url


def normalize(
    raw: RawOBTSeason,
    *,
    now: datetime,
    renditions_by_image: dict[str, list[tuple[int, str]]] | None = None,
) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    renditions_by_image = renditions_by_image or {}
    events: list[Event] = []
    unmapped_venues: set[str] = set()

    for production in raw.productions:
        venue = build_venue(production.title, raw.venues_by_title)
        image_url = best_image(production.image_url, renditions_by_image.get(production.image_url or "", []))
        events.extend(
            _normalize_production(
                production,
                venue=venue,
                image_url=image_url,
                now=now,
                counters=counters,
                unmapped_venues=unmapped_venues,
            )
        )

    if unmapped_venues:
        log.info(
            "OBT venues with no entry in venues.json (events published without coordinates): %s",
            ", ".join(sorted(unmapped_venues)),
        )

    events.sort(key=lambda e: e.start_at)
    log.info("OBT normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters


def _normalize_production(
    production: Production,
    *,
    venue: Venue | None,
    image_url: str | None,
    now: datetime,
    counters: NormalizationCounters,
    unmapped_venues: set[str],
) -> list[Event]:
    summary_source = production.description_html
    out: list[Event] = []

    for performance in production.performances:
        if not performance.is_visible:
            counters.hidden += 1
            continue

        try:
            start_at = performance.instant.astimezone(ZoneInfo(config.DISPLAY_TIMEZONE))
        except TimestampDisagreement as exc:
            log.warning("%s", exc)
            counters.timestamp_disagreement += 1
            continue
        except (ValueError, TypeError) as exc:
            log.warning("performance %s has an unparseable start: %s", performance.id, exc)
            counters.unparseable_time += 1
            continue

        if venue is None:
            counters.no_venue_name += 1
        else:
            if not venue.has_coordinates:
                counters.no_venue_coordinates += 1
                unmapped_venues.add(venue.name)

        event = Event(
            # Tessitura's performance key. Immutable upstream, unique per showing, and
            # the only identifier that keeps eighteen Nutcrackers eighteen bookmarks.
            id=make_event_id(config.SOURCE.id, performance.id),
            title=performance.title,
            summary=build_summary(summary_source, performance.product_type),
            start_at=start_at,
            venue=venue,
            categories=CATEGORIES,
            price=Price.unknown(),
            image_url=image_url,
            listing_url=production.listing_url,
            ticket_url=performance.ticket_url,
            organizer=config.SOURCE.name,
            source=config.SOURCE,
        )

        if event.is_stale(now):
            counters.stale += 1
            continue

        out.append(event)

    return out
