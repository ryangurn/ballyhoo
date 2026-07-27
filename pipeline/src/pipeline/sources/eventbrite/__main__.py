"""Eventbrite source entrypoint.

    uv run python -m pipeline.sources.eventbrite --output /tmp/eventbrite.json

Two passes — unfiltered and free-only — each sliced into weekly windows, deduplicated
by Eventbrite event id. `--summary` reports coverage without publishing anything, which
is the quickest way to see whether a shape change upstream has quietly degraded a field.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from ...common import log as logsetup
from ...common.io import build_per_source_feed, dump_json
from ...common.models import Event
from ...common.publishing import add_publish_arguments, publish_source_feed
from ...common.validate import SchemaValidationError, validate_per_source
from . import config
from .fetch import EventbriteFetchError, fetch_raw
from .normalize import normalize, unmapped_categories

log = logsetup.get_logger("pipeline.sources.eventbrite")


def _summarize(events: list[Event]) -> str:
    total = len(events)
    if not total:
        return "no events"

    def pct(count: int) -> str:
        return f"{count:>5} ({count / total:>4.0%})"

    free = [e for e in events if e.price.is_free]
    priced = [e for e in events if not e.price.is_free and e.price.min is not None]
    categories = Counter(c.value for e in events for c in e.categories)

    lines = [
        f"events                {total}",
        f"  free                {pct(len(free))}",
        f"  paid, price stated  {pct(len(priced))}",
        f"  price unknown       {pct(total - len(free) - len(priced))}",
        f"coordinates           {pct(sum(1 for e in events if e.venue and e.venue.has_coordinates))}",
        f"image                 {pct(sum(1 for e in events if e.image_url))}",
        f"description           {pct(sum(1 for e in events if e.summary))}",
        f"organizer             {pct(sum(1 for e in events if e.organizer))}",
        f"categories            {', '.join(f'{k} {v}' for k, v in categories.most_common())}",
    ]
    if priced:
        amounts = sorted(e.price.min for e in priced)
        lines.append(f"price range           ${amounts[0]:.2f} - ${amounts[-1]:.2f} "
                     f"(median ${amounts[len(amounts) // 2]:.2f})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.sources.eventbrite")
    parser.add_argument("--output", type=Path, help="Write the per-source feed here. Defaults to stdout.")
    parser.add_argument("--summary", action="store_true", help="Print coverage stats instead of the feed.")
    add_publish_arguments(parser)
    args = parser.parse_args(argv)

    logsetup.configure()
    now = datetime.now(UTC)

    try:
        raw, stats = fetch_raw(now=now)
    except EventbriteFetchError as exc:
        log.error("fetch failed: %s", exc)
        return 1

    events, counters = normalize(raw, now=now)
    feed = build_per_source_feed(config.SOURCE.id, events, generated_at=now)

    try:
        validate_per_source(feed)
    except SchemaValidationError as exc:
        log.error("schema validation failed, refusing to publish:\n%s", exc)
        return 1

    log.info("validated %d events; drops: %s; fetch: %s", len(events), counters.as_dict(), stats)
    if gaps := unmapped_categories():
        log.info("categories without a mapping: %s", ", ".join(gaps))

    if args.summary:
        sys.stdout.write(_summarize(events) + "\n")
        return 0

    publish_source_feed(args, source_id=config.SOURCE.id, feed=feed, now=now)

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
