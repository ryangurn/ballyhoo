"""Read and update the per-source health index.

`sources/index.json` is what lets the app's Sources tab tell the truth. Without it the
tab infers the source list from whichever events happen to be loaded, so a source that
breaks silently disappears from the UI — the moment a user would most benefit from
knowing about it.

Each source workflow updates only its own entry, which is also what keeps concurrent
pushes to `gh-pages` from conflicting.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .io import parse_datetime, to_iso
from .log import get_logger

log = get_logger(__name__)

# Sources run hourly; six hours of silence means something is wrong, not quiet.
STALE_AFTER = timedelta(hours=6)


def load_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"generated_at": None, "sources": []}
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        log.warning("index at %s is unreadable; rebuilding", path)
        return {"generated_at": None, "sources": []}
    payload.setdefault("sources", [])
    return payload


def mark_stale_entries(index: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Downgrade `ok` entries that have gone quiet.

    Without this a source that stops running keeps reporting `ok` forever, which is
    exactly the dishonesty the index exists to prevent.
    """
    for entry in index.get("sources", []):
        if entry.get("status") != "ok" or not entry.get("last_run_at"):
            continue
        try:
            if now - parse_datetime(entry["last_run_at"]) > STALE_AFTER:
                entry["status"] = "stale"
        except (ValueError, TypeError):
            entry["status"] = "error"
    return index


def update_source_entry(
    path: Path,
    *,
    source_id: str,
    last_run_at: str,
    event_count: int,
    status: str,
    now: datetime,
) -> dict[str, Any]:
    index = load_index(path)
    entries = [e for e in index.get("sources", []) if e.get("source_id") != source_id]
    entries.append(
        {
            "source_id": source_id,
            "last_run_at": last_run_at,
            "event_count": event_count,
            "status": status,
            "url": f"sources/{source_id}.json",
        }
    )
    entries.sort(key=lambda e: e["source_id"])

    index["sources"] = entries
    index["generated_at"] = to_iso(now)
    return mark_stale_entries(index, now)
