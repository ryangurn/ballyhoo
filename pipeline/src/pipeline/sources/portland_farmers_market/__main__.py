"""Portland Farmers Market source entrypoint.

    uv run python -m pipeline.sources.portland_farmers_market --output /tmp/pfm.json
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
from .fetch import FarmersMarketFetchError, fetch_raw
from .normalize import normalize

log = logsetup.get_logger("pipeline.sources.portland_farmers_market")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.sources.portland_farmers_market")
    parser.add_argument("--output", type=Path, help="Write the per-source feed here. Defaults to stdout.")
    add_publish_arguments(parser)
    args = parser.parse_args(argv)

    logsetup.configure()
    now = datetime.now(UTC)

    try:
        raw, _ = fetch_raw()
    except FarmersMarketFetchError as exc:
        log.error("fetch failed: %s", exc)
        return 1

    events, counters = normalize(raw, now=now)
    feed = build_per_source_feed(config.SOURCE.id, events, generated_at=now)

    try:
        validate_per_source(feed)
    except SchemaValidationError as exc:
        log.error("schema validation failed, refusing to publish:\n%s", exc)
        return 1

    log.info("validated %d events; drops: %s", len(events), counters.as_dict())

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
