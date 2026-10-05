"""Neighborhood farmers markets source entrypoint.

    uv run python -m pipeline.sources.neighborhood_markets --output /tmp/markets.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from ...common import log as logsetup
from ...common.io import build_per_source_feed, dump_json
from ...common.publishing import add_publish_arguments, publish_source_feed
from ...common.validate import SchemaValidationError, validate_per_source
from . import config
from .fetch import NeighborhoodFetchError, fetch_pages
from .markets import MARKETS
from .normalize import normalize

log = logsetup.get_logger("pipeline.sources.neighborhood_markets")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.sources.neighborhood_markets")
    parser.add_argument("--output", type=Path, help="Write the per-source feed here. Defaults to stdout.")
    add_publish_arguments(parser)
    args = parser.parse_args(argv)

    logsetup.configure()
    now = datetime.now(UTC)

    try:
        pages, _ = fetch_pages(MARKETS)
    except NeighborhoodFetchError as exc:
        log.error("fetch failed: %s", exc)
        return 1

    events, counters = normalize(pages, now=now)
    feed = build_per_source_feed(config.SOURCE.id, events, generated_at=now)

    try:
        validate_per_source(feed)
    except SchemaValidationError as exc:
        log.error("schema validation failed, refusing to publish:\n%s", exc)
        return 1

    log.info("validated %d events; counters: %s", len(events), counters.as_dict())

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
