"""Tests for archive snapshotting, and specifically for the dedup actually firing.

The check that skips an unchanged snapshot hashed the whole payload including
`generated_at`, which is fresh on every run, so it could never match. Across eighteen
live runs it skipped nothing. These tests pin the behaviour it was always meant to
have, and the two edges that behaviour opens up: a day whose first run finds unchanged
content still has to appear in the daily tier, and a manifest written before content
digests existed must not be read as a match.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta

from pipeline.common.archive import archive_snapshot

NOON = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def feed(*, generated_at: datetime, events: list | None = None) -> bytes:
    """A payload shaped like the real ones: sorted keys, timestamp sorting last."""
    payload = {
        "events": events if events is not None else [{"id": "ticketmaster:abc", "title": "Of Montreal"}],
        "generated_at": generated_at.isoformat(),
        "source_id": "ticketmaster",
        "status": "ok",
    }
    return (json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()


def manifest_of(archive_dir, artifact="sources/ticketmaster", moment=NOON) -> dict:
    path = archive_dir / artifact / "daily" / f"{moment:%Y}" / f"{moment:%m}" / "index.json"
    return json.loads(path.read_text())


def recent_files(archive_dir, artifact="sources/ticketmaster") -> list[str]:
    root = archive_dir / artifact / "recent"
    return sorted(str(p.relative_to(root)) for p in root.rglob("*.json.gz")) if root.exists() else []


class TestContentDedup:
    def test_a_second_run_with_only_a_new_timestamp_is_skipped(self, tmp_path):
        # The whole defect. Both payloads describe the same events; only the
        # generation stamp moved, and that is not a change worth a snapshot.
        first = archive_snapshot(tmp_path, "sources/ticketmaster", feed(generated_at=NOON), captured_at=NOON)
        second = archive_snapshot(
            tmp_path,
            "sources/ticketmaster",
            feed(generated_at=NOON + timedelta(hours=1)),
            captured_at=NOON + timedelta(hours=1),
        )

        assert first.written is True
        assert second.written is False
        assert second.reason == "unchanged since the last snapshot"

    def test_a_skipped_run_leaves_the_archive_untouched(self, tmp_path):
        archive_snapshot(tmp_path, "sources/ticketmaster", feed(generated_at=NOON), captured_at=NOON)
        before = recent_files(tmp_path)
        before_manifest = manifest_of(tmp_path)

        archive_snapshot(
            tmp_path,
            "sources/ticketmaster",
            feed(generated_at=NOON + timedelta(hours=1)),
            captured_at=NOON + timedelta(hours=1),
        )

        assert recent_files(tmp_path) == before
        assert manifest_of(tmp_path) == before_manifest

    def test_a_real_content_change_still_writes(self, tmp_path):
        archive_snapshot(tmp_path, "sources/ticketmaster", feed(generated_at=NOON), captured_at=NOON)
        later = NOON + timedelta(hours=1)
        changed = archive_snapshot(
            tmp_path,
            "sources/ticketmaster",
            feed(generated_at=later, events=[{"id": "ticketmaster:abc", "title": "Of Montreal w/ Sloppy Jane"}]),
            captured_at=later,
        )

        assert changed.written is True
        assert changed.reason == "snapshot written"
        assert len(recent_files(tmp_path)) == 2

    def test_one_changed_image_url_is_enough_to_count_as_a_change(self, tmp_path):
        # Guards the dedup against becoming too clever: it excludes the timestamp and
        # nothing else. Ticketmaster's rendition churn was a real content change in the
        # published artifact, and hiding it here would have hidden the bug.
        archive_snapshot(
            tmp_path,
            "sources/ticketmaster",
            feed(generated_at=NOON, events=[{"id": "a", "image_url": "https://img/a_RETINA_LANDSCAPE_16_9.jpg"}]),
            captured_at=NOON,
        )
        later = NOON + timedelta(hours=1)
        result = archive_snapshot(
            tmp_path,
            "sources/ticketmaster",
            feed(generated_at=later, events=[{"id": "a", "image_url": "https://img/a_SOURCE"}]),
            captured_at=later,
        )
        assert result.written is True

    def test_the_manifest_separates_the_stored_hash_from_the_content_hash(self, tmp_path):
        archive_snapshot(tmp_path, "sources/ticketmaster", feed(generated_at=NOON), captured_at=NOON)
        entry = manifest_of(tmp_path)["snapshots"][0]

        # `sha256` checksums the bytes on disk; `content_sha256` is what dedup compares.
        # Conflating the two is exactly what made the skip unreachable.
        assert entry["sha256"] != entry["content_sha256"]
        assert entry["unchanged"] is False

    def test_the_content_hash_ignores_only_the_timestamp(self, tmp_path):
        archive_snapshot(tmp_path, "sources/ticketmaster", feed(generated_at=NOON), captured_at=NOON)
        first = manifest_of(tmp_path)["snapshots"][0]

        tomorrow = NOON + timedelta(days=1)
        archive_snapshot(tmp_path, "sources/ticketmaster", feed(generated_at=tomorrow), captured_at=tomorrow)
        second = manifest_of(tmp_path, moment=tomorrow)["snapshots"][-1]

        assert first["content_sha256"] == second["content_sha256"]
        assert first["sha256"] != second["sha256"]


class TestDailyTierStaysComplete:
    def test_an_unchanged_first_run_of_a_new_day_still_writes_that_day(self, tmp_path):
        # Skipping is only safe once the day is represented. An artifact that sits
        # still for a week would otherwise leave a week of holes in a tier whose whole
        # promise is one entry per day.
        archive_snapshot(tmp_path, "sources/ticketmaster", feed(generated_at=NOON), captured_at=NOON)

        tomorrow = NOON + timedelta(days=1)
        result = archive_snapshot(
            tmp_path, "sources/ticketmaster", feed(generated_at=tomorrow), captured_at=tomorrow
        )

        assert result.written is True
        assert result.reason == "content unchanged; opened today's daily entry"
        assert (tmp_path / "sources/ticketmaster/daily/2026/07/28.json.gz").exists()

    def test_that_days_later_unchanged_runs_are_then_skipped(self, tmp_path):
        archive_snapshot(tmp_path, "sources/ticketmaster", feed(generated_at=NOON), captured_at=NOON)
        tomorrow = NOON + timedelta(days=1)
        archive_snapshot(tmp_path, "sources/ticketmaster", feed(generated_at=tomorrow), captured_at=tomorrow)

        later = tomorrow + timedelta(hours=1)
        third = archive_snapshot(
            tmp_path, "sources/ticketmaster", feed(generated_at=later), captured_at=later
        )
        assert third.written is False

    def test_a_day_opened_on_unchanged_content_is_marked_as_such(self, tmp_path):
        archive_snapshot(tmp_path, "sources/ticketmaster", feed(generated_at=NOON), captured_at=NOON)
        tomorrow = NOON + timedelta(days=1)
        archive_snapshot(tmp_path, "sources/ticketmaster", feed(generated_at=tomorrow), captured_at=tomorrow)

        assert manifest_of(tmp_path, moment=tomorrow)["snapshots"][-1]["unchanged"] is True

    def test_the_daily_entry_holds_the_days_latest_snapshot(self, tmp_path):
        archive_snapshot(tmp_path, "sources/ticketmaster", feed(generated_at=NOON), captured_at=NOON)
        evening = NOON + timedelta(hours=8)
        archive_snapshot(
            tmp_path,
            "sources/ticketmaster",
            feed(generated_at=evening, events=[{"id": "ticketmaster:abc", "title": "rescheduled"}]),
            captured_at=evening,
        )

        stored = json.loads(gzip.decompress((tmp_path / "sources/ticketmaster/daily/2026/07/27.json.gz").read_bytes()))
        assert stored["events"][0]["title"] == "rescheduled"
        assert stored["generated_at"] == evening.isoformat()


class TestManifestCompatibility:
    def test_an_entry_without_a_content_hash_never_reads_as_a_match(self, tmp_path):
        # Manifests written before this fix carry only `sha256`. Treating a missing
        # content hash as a match would skip a snapshot that was never compared.
        path = tmp_path / "sources/ticketmaster/daily/2026/07/index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "artifact": "sources/ticketmaster",
                    "month": "2026-07",
                    "snapshots": [{"captured_at": "2026-07-27T07:12:31+00:00", "sha256": "0" * 64}],
                }
            )
        )

        result = archive_snapshot(tmp_path, "sources/ticketmaster", feed(generated_at=NOON), captured_at=NOON)
        assert result.written is True

    def test_a_payload_that_is_not_a_json_object_still_dedups_on_its_bytes(self, tmp_path):
        blob = b"not json at all"
        first = archive_snapshot(tmp_path, "sources/ticketmaster", blob, captured_at=NOON)
        second = archive_snapshot(
            tmp_path, "sources/ticketmaster", blob, captured_at=NOON + timedelta(hours=1)
        )
        assert (first.written, second.written) == (True, False)

    def test_dedup_survives_a_month_boundary(self, tmp_path):
        last_day = datetime(2026, 7, 31, 23, 0, tzinfo=UTC)
        first_day = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        archive_snapshot(tmp_path, "sources/ticketmaster", feed(generated_at=last_day), captured_at=last_day)

        # A new month means a new manifest, so the previous month has to be consulted.
        # The day is new either way, so this writes — but it must write knowing the
        # content matched, not because it failed to find anything to compare against.
        result = archive_snapshot(
            tmp_path, "sources/ticketmaster", feed(generated_at=first_day), captured_at=first_day
        )
        assert result.written is True
        assert manifest_of(tmp_path, moment=first_day)["snapshots"][-1]["unchanged"] is True

        later = first_day + timedelta(hours=1)
        assert archive_snapshot(
            tmp_path, "sources/ticketmaster", feed(generated_at=later), captured_at=later
        ).written is False
