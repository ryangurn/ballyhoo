"""Shared publishing wiring for source and merge entrypoints.

Keeps the CLI surface and the publish-then-archive ordering identical across every
command, so a new source inherits correct behavior instead of reimplementing it.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from .archive import try_archive
from .io import dump_json
from .log import get_logger
from .publish import PublishResult, publish

log = get_logger(__name__)


def add_publish_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pages-dir", type=Path, help="Checkout of the gh-pages branch to publish into.")
    parser.add_argument("--archive-dir", type=Path, help="Checkout of the archive branch for snapshots.")
    parser.add_argument("--pages-branch", default="gh-pages")
    parser.add_argument("--archive-branch", default="archive")
    parser.add_argument("--dry-run", action="store_true", help="Do everything except commit and push.")


def publish_source_feed(
    args: argparse.Namespace,
    *,
    source_id: str,
    feed: dict[str, Any],
    now: datetime,
) -> PublishResult | None:
    """Publish one source's file and its health-index entry, then snapshot it."""
    if not args.pages_dir:
        return None

    payload = dump_json(feed)
    events = feed.get("events", [])

    # A source writes only its own file. It deliberately does not touch
    # sources/index.json: that is a single shared file, so every source rewriting it
    # broke the disjoint-paths guarantee the moment two runs overlapped. DoPDX takes
    # four minutes, and a faster source publishing meanwhile left its rebase
    # unresolvable. The merge already reads every per-source file and rebuilds the
    # index from them, so it owns that write alone.
    result = publish(
        args.pages_dir,
        {f"sources/{source_id}.json": payload},
        message=f"{source_id}: {len(events)} events",
        branch=args.pages_branch,
        dry_run=args.dry_run,
    )
    log.info("publish: %s", result.reason)

    # Only after the live artifact is safely published, and never fatally.
    if not args.dry_run:
        snapshot = try_archive(
            args.archive_dir,
            f"sources/{source_id}",
            payload.encode(),
            event_count=len(events),
            captured_at=now,
        )
        if args.archive_dir and snapshot.written:
            publish(
                args.archive_dir,
                {},
                message=f"archive {source_id}: {len(events)} events",
                branch=args.archive_branch,
            )
        log.info("archive: %s", snapshot.reason)

    return result
