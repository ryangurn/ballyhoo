"""Tests for the publish/archive wiring.

These exist because of a real production failure: every source workflow was writing
the shared `sources/index.json` alongside its own file, which held only while runs
never overlapped. DoPDX takes four minutes, and a faster source publishing in the
meantime left its rebase unresolvable, so a run that had already fetched and
validated 1,128 events threw the lot away.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from pipeline.common.publishing import publish_source_feed

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)

FEED = {
    "generated_at": "2026-07-27T12:00:00+00:00",
    "source_id": "dopdx",
    "status": "ok",
    "events": [],
}


def args_for(pages_dir: Path) -> argparse.Namespace:
    return argparse.Namespace(
        pages_dir=pages_dir,
        archive_dir=None,
        pages_branch="gh-pages",
        archive_branch="archive",
        dry_run=False,
    )


class TestSourcesWriteDisjointPaths:
    def test_a_source_writes_only_its_own_file(self, tmp_path):
        with patch("pipeline.common.publishing.publish") as publish, \
             patch("pipeline.common.publishing.try_archive"):
            publish_source_feed(args_for(tmp_path), source_id="dopdx", feed=FEED, now=NOW)

        written = set(publish.call_args.args[1].keys())
        assert written == {"sources/dopdx.json"}

    def test_a_source_never_writes_the_shared_index(self, tmp_path):
        # The whole point. sources/index.json is one file shared by every workflow,
        # so any source touching it reintroduces the rebase conflict.
        with patch("pipeline.common.publishing.publish") as publish, \
             patch("pipeline.common.publishing.try_archive"):
            publish_source_feed(args_for(tmp_path), source_id="dopdx", feed=FEED, now=NOW)

        assert "sources/index.json" not in publish.call_args.args[1]

    def test_two_sources_write_paths_that_cannot_collide(self, tmp_path):
        paths = []
        for source_id in ("dopdx", "portland_parks", "calagator"):
            with patch("pipeline.common.publishing.publish") as publish, \
                 patch("pipeline.common.publishing.try_archive"):
                publish_source_feed(
                    args_for(tmp_path), source_id=source_id, feed={**FEED, "source_id": source_id}, now=NOW
                )
            paths.append(set(publish.call_args.args[1].keys()))

        for i, first in enumerate(paths):
            for second in paths[i + 1:]:
                assert first & second == set(), f"overlapping writes: {first & second}"

    def test_nothing_publishes_without_a_pages_directory(self):
        args = args_for(Path("/nonexistent"))
        args.pages_dir = None
        with patch("pipeline.common.publishing.publish") as publish:
            assert publish_source_feed(args, source_id="dopdx", feed=FEED, now=NOW) is None
        publish.assert_not_called()
