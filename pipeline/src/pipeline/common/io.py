"""Serialization between the dataclass models and the published JSON shape.

The client decodes with a snake_case key strategy and an ISO-8601 date strategy that
accepts fractional and non-fractional seconds. We always emit non-fractional with an
explicit offset, which is the stricter of the two forms it accepts.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from dateutil import parser as date_parser

from .models import Category, Event, Price, Source, Venue


def to_iso(dt: datetime) -> str:
    """ISO-8601 with an explicit offset, no fractional seconds."""
    if dt.tzinfo is None:
        raise ValueError(f"refusing to serialize naive datetime {dt!r}; offset is required")
    return dt.replace(microsecond=0).isoformat()


def parse_datetime(value: str) -> datetime:
    """Parse an upstream timestamp, preserving its offset.

    Upstream sources are inconsistent about fractional seconds and offset format, so
    we lean on dateutil rather than a fixed format string. A value that parses to a
    naive datetime is an error rather than something to guess a timezone for — a
    silently wrong offset shifts an event by hours in the UI.
    """
    parsed = date_parser.isoparse(value)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {value!r} has no UTC offset")
    return parsed


def _prune(value: Any) -> Any:
    """Drop None-valued keys so the feed stays compact.

    Every optional field on the Swift side is already Optional, so an absent key and
    an explicit null decode identically.
    """
    if isinstance(value, dict):
        return {k: _prune(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [_prune(v) for v in value]
    return value


def event_to_dict(event: Event) -> dict[str, Any]:
    payload = asdict(event)
    payload["start_at"] = to_iso(event.start_at)
    payload["end_at"] = to_iso(event.end_at) if event.end_at else None
    payload["categories"] = [c.value for c in event.categories]
    payload["merged_sources"] = list(event.merged_sources)
    if not payload["merged_sources"]:
        del payload["merged_sources"]
    return _prune(payload)


def event_from_dict(payload: dict[str, Any]) -> Event:
    src = payload["source"]
    venue_payload = payload.get("venue")
    price_payload = payload.get("price") or {}
    return Event(
        id=payload["id"],
        title=payload["title"],
        start_at=parse_datetime(payload["start_at"]),
        price=Price(
            is_free=price_payload.get("is_free", False),
            min=price_payload.get("min"),
            max=price_payload.get("max"),
            currency=price_payload.get("currency", "USD"),
        ),
        source=Source(id=src["id"], name=src["name"], url=src.get("url")),
        summary=payload.get("summary"),
        end_at=parse_datetime(payload["end_at"]) if payload.get("end_at") else None,
        is_all_day=payload.get("is_all_day", False),
        venue=Venue(**venue_payload) if venue_payload else None,
        categories=tuple(Category(c) for c in payload.get("categories", [])),
        image_url=payload.get("image_url"),
        listing_url=payload.get("listing_url"),
        ticket_url=payload.get("ticket_url"),
        organizer=payload.get("organizer"),
        merged_sources=tuple(payload.get("merged_sources", [])),
    )


def build_per_source_feed(
    source_id: str, events: Iterable[Event], *, status: str = "ok", generated_at: datetime | None = None
) -> dict[str, Any]:
    return {
        "generated_at": to_iso(generated_at or datetime.now(UTC)),
        "source_id": source_id,
        "status": status,
        "events": [event_to_dict(e) for e in events],
    }


def build_merged_feed(events: Iterable[Event], *, generated_at: datetime | None = None) -> dict[str, Any]:
    return {
        "generated_at": to_iso(generated_at or datetime.now(UTC)),
        "events": [event_to_dict(e) for e in events],
    }


def dump_json(payload: dict[str, Any]) -> str:
    """Stable, diff-friendly JSON.

    Sorted keys and a fixed separator matter more than they look: the archive skips
    writing a snapshot when content hashes identically to the previous one, and
    unstable key ordering would defeat that and bloat history with false changes.
    """
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
