"""Calagator source entrypoint.

    uv run python -m pipeline.sources.calagator --output /tmp/calagator.json

Publishing to gh-pages and archiving are added in a later milestone; today this
fetches, normalizes, validates, and writes a local file.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from ...common import log as logsetup
from ...common.io import build_per_source_feed, dump_json
from ...common.validate import SchemaValidationError, validate_per_source
from . import config
from .fetch import CalagatorFetchError, fetch_raw
from .normalize import normalize

log = logsetup.get_logger("pipeline.sources.calagator")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.sources.calagator")
    parser.add_argument("--output", type=Path, help="Write the per-source feed here. Defaults to stdout.")
    parser.add_argument("--dry-run", action="store_true", help="Validate but write nothing.")
    args = parser.parse_args(argv)

    logsetup.configure()
    now = datetime.now(UTC)

    try:
        raw = fetch_raw(now=now)
    except CalagatorFetchError as exc:
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
