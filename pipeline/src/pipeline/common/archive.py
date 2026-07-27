"""Immutable historical snapshots of every published artifact.

Two retention tiers, maintained inline so no separate cleanup job is needed:

    <artifact>/recent/<YYYY-MM-DD>/<HHMMSS>Z.json.gz   every change, pruned after 7 days
    <artifact>/daily/<YYYY>/<MM>/<DD>.json.gz          one per day, kept indefinitely

The daily tier needs no rollup: each write overwrites the current day's entry, so it
always holds that day's latest snapshot and freezes naturally when the date rolls over.

Snapshots are gzipped because at hourly cadence the uncompressed volume is the
difference between a manageable archive and an unmanageable one. Manifests stay
uncompressed so the archive is navigable without tooling.

Note what pruning does and does not do: it bounds the *working tree*, keeping the
archive browsable and making a future history compaction cheap. It does not reclaim
git history, which grows at the full per-run rate regardless. Compacting that history
is deliberately deferred — see the change's design doc for the runway.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .log import get_logger

log = get_logger(__name__)

RECENT_RETENTION = timedelta(days=7)


class ArchiveError(Exception):
    """Archiving failed. Callers must treat this as non-fatal: the live artifact is
    already published, and losing a snapshot is not worth failing a run over."""


@dataclass(frozen=True)
class ArchiveResult:
    written: bool
    reason: str
    recent_path: str | None = None
    daily_path: str | None = None
    pruned: int = 0


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _manifest_path(archive_dir: Path, artifact: str, moment: datetime) -> Path:
    return archive_dir / artifact / "daily" / f"{moment:%Y}" / f"{moment:%m}" / "index.json"


def _load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"artifact": None, "month": None, "snapshots": []}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        log.warning("manifest at %s is unreadable; starting a fresh one", path)
        return {"artifact": None, "month": None, "snapshots": []}


def _latest_hash(archive_dir: Path, artifact: str, moment: datetime) -> str | None:
    """Most recent recorded hash, checking the previous month at a boundary."""
    for candidate in (moment, moment.replace(day=1) - timedelta(days=1)):
        manifest = _load_manifest(_manifest_path(archive_dir, artifact, candidate))
        snapshots = manifest.get("snapshots") or []
        if snapshots:
            return snapshots[-1].get("sha256")
    return None


def _prune_recent(artifact_dir: Path, moment: datetime) -> int:
    recent_root = artifact_dir / "recent"
    if not recent_root.is_dir():
        return 0

    cutoff = (moment - RECENT_RETENTION).date()
    pruned = 0
    for day_dir in recent_root.iterdir():
        if not day_dir.is_dir():
            continue
        try:
            day = datetime.strptime(day_dir.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day < cutoff:
            shutil.rmtree(day_dir, ignore_errors=True)
            pruned += 1
    return pruned


def archive_snapshot(
    archive_dir: Path,
    artifact: str,
    payload: bytes,
    *,
    event_count: int | None = None,
    captured_at: datetime | None = None,
) -> ArchiveResult:
    """Record one snapshot. Skips writing when content is unchanged."""
    moment = (captured_at or datetime.now(UTC)).astimezone(UTC)
    digest = _sha256(payload)

    if _latest_hash(archive_dir, artifact, moment) == digest:
        return ArchiveResult(False, "unchanged since the last snapshot")

    artifact_dir = archive_dir / artifact
    compressed = gzip.compress(payload, mtime=0)

    recent_rel = f"{artifact}/recent/{moment:%Y-%m-%d}/{moment:%H%M%S}Z.json.gz"
    daily_rel = f"{artifact}/daily/{moment:%Y}/{moment:%m}/{moment:%d}.json.gz"

    for relative in (recent_rel, daily_rel):
        target = archive_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(compressed)

    manifest_path = _manifest_path(archive_dir, artifact, moment)
    manifest = _load_manifest(manifest_path)
    manifest["artifact"] = artifact
    manifest["month"] = f"{moment:%Y-%m}"
    manifest.setdefault("snapshots", []).append(
        {
            "captured_at": moment.replace(microsecond=0).isoformat(),
            "sha256": digest,
            "bytes": len(payload),
            "gzip_bytes": len(compressed),
            "event_count": event_count,
            "recent": recent_rel,
            "daily": daily_rel,
        }
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    pruned = _prune_recent(artifact_dir, moment)

    log.info(
        "archived %s (%d bytes -> %d gzipped)%s",
        artifact,
        len(payload),
        len(compressed),
        f", pruned {pruned} expired day(s)" if pruned else "",
    )
    return ArchiveResult(True, "snapshot written", recent_rel, daily_rel, pruned)


def try_archive(archive_dir: Path | None, artifact: str, payload: bytes, **kwargs) -> ArchiveResult:
    """Archive without ever propagating a failure.

    The live artifact is published before this runs. Failing the job here would mark a
    successful publish as failed and, worse, could trigger a retry that republishes.
    A missing snapshot is reported and moved past.
    """
    if archive_dir is None:
        return ArchiveResult(False, "archiving not configured")
    try:
        return archive_snapshot(archive_dir, artifact, payload, **kwargs)
    except Exception as exc:  # noqa: BLE001 - deliberately broad; archiving is never fatal
        log.error("archiving %s failed (the live artifact is unaffected): %s", artifact, exc)
        return ArchiveResult(False, f"failed: {exc}")
