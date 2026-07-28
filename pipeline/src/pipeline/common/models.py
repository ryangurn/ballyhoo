"""Normalized event model shared by every source.

Mirrors the Swift `Event` type in `ballyhoo/Models/Event.swift`. The JSON these
dataclasses emit is what the iOS client decodes, so field names and shapes here are
a contract, not an implementation detail. Changes must stay in sync with
`pipeline/schema/event.schema.json` and the Swift model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

PORTLAND_TZ = ZoneInfo("America/Los_Angeles")

# Events already well past are noise even if an upstream still lists them.
STALE_EVENT_GRACE = timedelta(days=7)


class Category(StrEnum):
    """Must stay in lockstep with the Swift `Category` enum.

    A value the client doesn't recognize fails to decode, so adding a case here
    requires shipping the app change first.
    """

    MUSIC = "music"
    ARTS = "arts"
    FOOD = "food"
    COMMUNITY = "community"
    TECH = "tech"
    OUTDOORS = "outdoors"
    FAMILY = "family"
    MARKET = "market"
    NIGHTLIFE = "nightlife"
    CIVIC = "civic"
    SPORTS = "sports"
    FILM = "film"
    LITERARY = "literary"
    WELLNESS = "wellness"


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    name: str
    url: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9_]+", self.id):
            raise ValueError(f"source id must be lowercase alphanumeric/underscore, got {self.id!r}")


@dataclass(frozen=True, slots=True)
class Venue:
    name: str
    address: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None


@dataclass(frozen=True, slots=True)
class Price:
    is_free: bool
    min: float | None = None
    max: float | None = None
    currency: str | None = "USD"

    @classmethod
    def free(cls) -> Price:
        return cls(is_free=True, min=0.0, max=0.0)

    @classmethod
    def unknown(cls) -> Price:
        """Price not stated upstream. Distinct from free — we must not imply free."""
        return cls(is_free=False)


@dataclass(frozen=True, slots=True)
class Event:
    id: str
    title: str
    start_at: datetime
    price: Price
    source: Source
    summary: str | None = None
    end_at: datetime | None = None
    is_all_day: bool = False
    venue: Venue | None = None
    categories: tuple[Category, ...] = ()
    image_url: str | None = None
    listing_url: str | None = None
    ticket_url: str | None = None
    organizer: str | None = None
    merged_sources: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if not self.id.startswith(f"{self.source.id}:"):
            raise ValueError(
                f"event id {self.id!r} must be prefixed with its source id "
                f"{self.source.id!r} so bookmarks stay stable across runs"
            )
        if self.start_at.tzinfo is None:
            raise ValueError(f"event {self.id!r} has a naive start_at; an explicit offset is required")

    def is_stale(self, now: datetime) -> bool:
        return self.start_at < now - STALE_EVENT_GRACE


def make_event_id(source_id: str, upstream_id: str | int) -> str:
    """Compose the stable identifier.

    Deliberately derived only from immutable upstream identity — never from title,
    date, or venue, all of which get edited upstream and would orphan bookmarks.
    """
    upstream = str(upstream_id).strip()
    if not upstream:
        raise ValueError(f"cannot build an event id for {source_id!r} from an empty upstream id")
    return f"{source_id}:{upstream}"
