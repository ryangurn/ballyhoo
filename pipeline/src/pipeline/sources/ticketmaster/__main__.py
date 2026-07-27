"""Ticketmaster source entrypoint.

    uv run python -m pipeline.sources.ticketmaster --output /tmp/ticketmaster.json
    uv run python -m pipeline.sources.ticketmaster --histogram

The histogram mode is how the current config was derived; keep it for re-tuning as
Portland's volume shifts.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...common import env
from ...common import log as logsetup
from ...common.io import build_per_source_feed, dump_json
from ...common.validate import SchemaValidationError, validate_per_source
from . import config
from .categories import unmapped_segments
from .fetch import DeepPagingLimitExceeded, TicketmasterFetchError, fetch_raw
from .normalize import normalize

log = logsetup.get_logger("pipeline.sources.ticketmaster")


def _print_histogram(raw_events: list[dict[str, Any]], stats: dict[str, Any]) -> None:
    segments: Counter[str] = Counter()
    genres: Counter[str] = Counter()
    priced = 0

    for raw in raw_events:
        classifications = raw.get("classifications") or []
        primary = next((c for c in classifications if c.get("primary")), classifications[0] if classifications else {})
        segments[((primary.get("segment") or {}).get("name")) or "«none»"] += 1
        genres[((primary.get("genre") or {}).get("name")) or "«none»"] += 1
        if raw.get("priceRanges"):
            priced += 1

    total = len(raw_events) or 1
    out = sys.stdout
    out.write(f"\nTicketmaster — {config.RADIUS_MILES} mi, {config.FETCH_WINDOW.days} day window\n")
    out.write(f"  totalElements reported : {stats['total_elements']}\n")
    out.write(f"  collected              : {stats['collected']}\n")
    out.write(f"  requests made          : {stats['requests_made']}\n")
    out.write(f"  deep-paging headroom   : {config.DEEP_PAGING_LIMIT - stats['total_elements']}\n")
    out.write(f"  with price data        : {priced} ({priced * 100 // total}%)\n")

    out.write("\n  Segments\n")
    for name, count in segments.most_common():
        out.write(f"    {name:<22} {count:>4}  {count * 100 // total:>3}%\n")

    out.write("\n  Genres (top 15)\n")
    for name, count in genres.most_common(15):
        out.write(f"    {name:<22} {count:>4}\n")

    out.write("\n  Sample titles\n")
    for raw in raw_events[:8]:
        classifications = raw.get("classifications") or []
        primary = next((c for c in classifications if c.get("primary")), classifications[0] if classifications else {})
        seg = ((primary.get("segment") or {}).get("name")) or "?"
        out.write(f"    {raw.get('name', '')[:56]:<58} [{seg}]\n")
    out.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.sources.ticketmaster")
    parser.add_argument("--output", type=Path, help="Write the per-source feed here. Defaults to stdout.")
    parser.add_argument("--dry-run", action="store_true", help="Validate but write nothing.")
    parser.add_argument(
        "--histogram",
        action="store_true",
        help="Print a segment/genre breakdown and exit without normalizing or writing.",
    )
    args = parser.parse_args(argv)

    logsetup.configure()
    env.load_env_file()

    try:
        api_key = env.require(config.API_KEY_ENV)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1

    now = datetime.now(UTC)

    try:
        raw, stats = fetch_raw(api_key, now=now)
    except DeepPagingLimitExceeded as exc:
        log.error("refusing to publish a silently truncated feed: %s", exc)
        return 2
    except TicketmasterFetchError as exc:
        log.error("fetch failed: %s", exc)
        return 1

    if args.histogram:
        _print_histogram(raw, stats)
        return 0

    events, counters = normalize(raw, now=now)
    feed = build_per_source_feed(config.SOURCE.id, events, generated_at=now)

    try:
        validate_per_source(feed)
    except SchemaValidationError as exc:
        log.error("schema validation failed, refusing to publish:\n%s", exc)
        return 1

    log.info("validated %d events; drops: %s", len(events), counters.as_dict())
    if gaps := unmapped_segments():
        log.warning("segments missing from the category table: %s", ", ".join(gaps))

    payload = dump_json(feed)
    if args.dry_run:
        log.info("dry run, not writing")
    elif args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
        log.info("wrote %s (%d bytes)", args.output, len(payload))
    else:
        sys.stdout.write(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
