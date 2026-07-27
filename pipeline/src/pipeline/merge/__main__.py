"""Merge every per-source file into the canonical feed.

    uv run python -m pipeline.merge --sources-dir <dir> --output-dir <dir>

This is the only step that writes `events.json`. It reads whatever per-source files
exist, deduplicates across them, validates, applies the floor check, and writes the
merged feed plus the health index the app's Sources tab reads.

A source whose most recent run failed simply has a stale file on disk; the merge uses
it rather than dropping that source's events entirely, so one broken upstream degrades
freshness instead of removing content. A source that has never published at all has no
file, and the index reports it from the configured-source registry so that it surfaces
as broken rather than as absent.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..common import log as logsetup
from ..common.archive import try_archive
from ..common.index import mark_stale_entries
from ..common.io import build_merged_feed, dump_json, event_from_dict, parse_datetime
from ..common.models import Source
from ..common.publish import publish
from ..common.publishing import add_publish_arguments
from ..common.validate import SchemaValidationError, validate_merged, validate_sources_index
from .dedupe import deduplicate
from .floor import append_history, evaluate, load_history
from .registry import configured_sources

log = logsetup.get_logger("pipeline.merge")


def _load_source_files(sources_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    payloads: list[dict[str, Any]] = []
    problems: list[str] = []

    for path in sorted(sources_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            payloads.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError) as exc:
            # One unreadable source file must not take down the whole feed.
            problems.append(f"{path.name}: {exc}")
            log.error("skipping unreadable source file %s: %s", path.name, exc)

    return payloads, problems


def _build_index(payloads: list[dict[str, Any]], configured: list[Source], now: datetime) -> dict[str, Any]:
    entries = []
    for payload in payloads:
        source_id = payload.get("source_id", "unknown")
        generated_raw = payload.get("generated_at")

        status = payload.get("status", "ok")
        last_run_at = None
        if generated_raw:
            try:
                parse_datetime(generated_raw)
                last_run_at = generated_raw
            except (ValueError, TypeError):
                # An unparseable stamp is left off the entry rather than published as
                # it arrived: the client would decode it as a date or not at all.
                status = "error"

        entries.append(
            {
                "source_id": source_id,
                "last_run_at": last_run_at,
                "event_count": len(payload.get("events", [])),
                "status": status,
                "url": f"sources/{source_id}.json",
            }
        )

    published = {entry["source_id"] for entry in entries}
    for source in configured:
        if source.id in published:
            continue
        # Configured and wired into CI, but nothing on gh-pages: the source has never
        # completed a run. Leaving it out would hide the very failure the index exists
        # to surface, so it reports as broken with nothing behind it. `url` is null
        # because there is no file at that path to link to yet.
        log.warning("configured source %s has never published; reporting it as error", source.id)
        entries.append(
            {
                "source_id": source.id,
                "last_run_at": None,
                "event_count": 0,
                "status": "error",
                "url": None,
            }
        )

    entries.sort(key=lambda e: e["source_id"])
    index = {"generated_at": now.replace(microsecond=0).isoformat(), "sources": entries}

    # Staleness lives in one place rather than being restated here. Two copies of the
    # threshold is how a rule ends up enforced in one path and not the other.
    return mark_stale_entries(index, now)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.merge")
    parser.add_argument("--sources-dir", type=Path, required=True, help="Directory of per-source *.json files.")
    parser.add_argument("--output-dir", type=Path, help="Write artifacts here locally instead of publishing.")
    parser.add_argument(
        "--override-floor",
        action="store_true",
        help="Publish even if the event count collapsed. Use only when the drop is known to be real.",
    )
    add_publish_arguments(parser)
    args = parser.parse_args(argv)

    logsetup.configure()
    now = datetime.now(UTC)

    if not args.sources_dir.is_dir():
        log.error("no such directory: %s", args.sources_dir)
        return 1

    payloads, problems = _load_source_files(args.sources_dir)
    if not payloads:
        log.error("no readable per-source files in %s; refusing to publish an empty feed", args.sources_dir)
        return 1

    events = []
    for payload in payloads:
        source_id = payload.get("source_id", "unknown")
        decoded = 0
        for raw in payload.get("events", []):
            try:
                events.append(event_from_dict(raw))
                decoded += 1
            except (KeyError, ValueError, TypeError) as exc:
                # Drop the individual event, keep the rest of the source.
                problems.append(f"{source_id}: undecodable event {raw.get('id')}: {exc}")
                log.warning("skipping undecodable event %s from %s: %s", raw.get("id"), source_id, exc)
        log.info("loaded %d events from %s", decoded, source_id)

    merged, audit = deduplicate(events)

    # History has to be read from wherever the artifacts will be written, or the floor
    # has nothing to compare against. Both sides are derived from one value for exactly
    # that reason: this read used to be hard-coded to --output-dir while CI publishes
    # with --pages-dir, so history loaded empty on every production run, every merge
    # reported "insufficient history", and the published file was overwritten with the
    # single count from the run that just finished. The guard was never once armed.
    destination = args.pages_dir or args.output_dir
    history = load_history(destination / "history.json") if destination else []
    log.info("floor baseline: %d prior run(s) from %s", len(history), destination or "nowhere")

    check = evaluate(len(merged), history, override=args.override_floor)
    if not check.passed:
        log.error("floor check failed: %s", check.reason)
        return 3
    log.info("floor check passed: %s", check.reason)

    feed = build_merged_feed(merged, generated_at=now)
    index = _build_index(payloads, configured_sources(), now)

    try:
        validate_merged(feed)
        validate_sources_index(index)
    except SchemaValidationError as exc:
        log.error("schema validation failed, refusing to publish:\n%s", exc)
        return 1

    log.info(
        "merged %d events from %d source(s); %d duplicate(s) collapsed; %d problem(s)",
        len(merged),
        len(payloads),
        len(audit),
        len(problems),
    )

    feed_json = dump_json(feed)
    report = dump_json(
        {
            "generated_at": now.replace(microsecond=0).isoformat(),
            "event_count": len(merged),
            "sources": [p.get("source_id") for p in payloads],
            "duplicates_merged": audit,
            "problems": problems,
            "floor_check": check.reason,
        }
    )
    history_json = dump_json({"counts": append_history(history, len(merged))})

    # The merge owns events.json, history.json, and the aggregate index; each source
    # workflow owns its own per-source file. Disjoint paths are what keep concurrent
    # pushes to gh-pages from conflicting.
    artifacts = {
        "events.json": feed_json,
        "history.json": history_json,
        "merge-report.json": report,
        "sources/index.json": dump_json(index),
    }

    if args.pages_dir:
        result = publish(
            args.pages_dir,
            artifacts,
            message=f"merge: {len(merged)} events from {len(payloads)} source(s)",
            branch=args.pages_branch,
            dry_run=args.dry_run,
        )
        log.info("publish: %s", result.reason)

        if not args.dry_run:
            snapshot = try_archive(
                args.archive_dir, "events", feed_json.encode(), event_count=len(merged), captured_at=now
            )
            if args.archive_dir and snapshot.written:
                publish(
                    args.archive_dir,
                    {},
                    message=f"archive events: {len(merged)} events",
                    branch=args.archive_branch,
                )
            log.info("archive: %s", snapshot.reason)
        return 0

    if args.dry_run:
        log.info("dry run, not writing")
        return 0

    if not args.output_dir:
        sys.stdout.write(feed_json)
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for relative, content in artifacts.items():
        target = args.output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    log.info("wrote %s", args.output_dir / "events.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
