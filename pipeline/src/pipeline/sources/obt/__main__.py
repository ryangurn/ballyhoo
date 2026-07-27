"""Oregon Ballet Theatre source entrypoint.

    uv run python -m pipeline.sources.obt --output /tmp/obt.json

A run makes one Tessitura API call, two requests to the marketing site for venues,
and one media lookup per distinct production image. The crawl-delay OBT's robots.txt
asks for dominates the wall clock; the whole thing is well under a minute.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests

from ...common import log as logsetup
from ...common.io import build_per_source_feed, dump_json
from ...common.publishing import add_publish_arguments, publish_source_feed
from ...common.validate import SchemaValidationError, validate_per_source
from . import config
from .fetch import OBTFetchError, fetch_image_renditions, fetch_raw
from .normalize import normalize

log = logsetup.get_logger("pipeline.sources.obt")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.sources.obt")
    parser.add_argument("--output", type=Path, help="Write the per-source feed here. Defaults to stdout.")
    add_publish_arguments(parser)
    args = parser.parse_args(argv)

    logsetup.configure()
    now = datetime.now(UTC)
    session = requests.Session()

    try:
        raw, stats = fetch_raw(session)
    except OBTFetchError as exc:
        log.error("fetch failed: %s", exc)
        return 1

    # One lookup per distinct image, not per performance: a whole run shares one piece
    # of artwork, so this is a handful of requests rather than one per event.
    renditions_by_image = {
        url: fetch_image_renditions(session, url)
        for url in {p.image_url for p in raw.productions if p.image_url}
    }

    events, counters = normalize(raw, now=now, renditions_by_image=renditions_by_image)
    feed = build_per_source_feed(config.SOURCE.id, events, generated_at=now)

    try:
        validate_per_source(feed)
    except SchemaValidationError as exc:
        log.error("schema validation failed, refusing to publish:\n%s", exc)
        return 1

    log.info("validated %d events from %s; drops: %s", len(events), stats, counters.as_dict())

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
