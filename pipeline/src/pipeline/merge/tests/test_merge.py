"""Tests for cross-source merge, deduplication, and the floor check."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pipeline.common.io import build_per_source_feed, dump_json
from pipeline.common.models import Category, Event, Price, Source, Venue
from pipeline.common.validate import validate_sources_index
from pipeline.merge.__main__ import _build_index, main
from pipeline.merge.dedupe import deduplicate
from pipeline.merge.floor import FLOOR_RATIO, MIN_HISTORY_RUNS, append_history, evaluate, load_history
from pipeline.merge.registry import configured_sources

TM = Source(id="ticketmaster", name="Ticketmaster")
CAL = Source(id="calagator", name="Calagator")
START = datetime(2026, 9, 15, 20, 0, tzinfo=UTC)
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def event(source: Source, upstream: str, *, venue: str | None = "Wonder Ballroom", start=START, **kw) -> Event:
    return Event(
        id=f"{source.id}:{upstream}",
        title=kw.pop("title", "Of Montreal"),
        start_at=start,
        price=kw.pop("price", Price.unknown()),
        source=source,
        venue=Venue(name=venue) if venue else None,
        **kw,
    )


def source_payload(source: Source, count: int, *, generated_at: str | None = None, status: str = "ok") -> dict:
    """A per-source file of the shape the merge reads off `gh-pages`."""
    events = [
        event(source, str(i), venue=f"{source.name} Room {i}", start=START + timedelta(hours=i))
        for i in range(count)
    ]
    payload = build_per_source_feed(source.id, events, status=status, generated_at=NOW)
    if generated_at is not None:
        payload["generated_at"] = generated_at
    return payload


def write_sources(sources_dir: Path, counts: dict[Source, int]) -> None:
    sources_dir.mkdir(parents=True, exist_ok=True)
    for source, count in counts.items():
        (sources_dir / f"{source.id}.json").write_text(dump_json(source_payload(source, count)))


def make_pages_dir(tmp_path: Path, *, counts: list[int] | None = None) -> Path:
    """A stand-in for the `gh-pages` checkout CI hands the merge.

    `publish` refuses a directory that is not a checkout, so the marker has to exist
    even under `--dry-run`.
    """
    pages_dir = tmp_path / "gh-pages"
    (pages_dir / ".git").mkdir(parents=True)
    if counts is not None:
        (pages_dir / "history.json").write_text(dump_json({"counts": counts}))
    return pages_dir


def merge_into_pages(sources_dir: Path, pages_dir: Path, *extra: str) -> int:
    # `--dry-run` still writes every artifact into the checkout; only the commit and
    # push are skipped. That is the whole publishing path this suite cares about, and
    # it keeps these tests off git and off the archive.
    return main(
        ["--sources-dir", str(sources_dir), "--pages-dir", str(pages_dir), "--dry-run", *extra]
    )


def published_history(pages_dir: Path) -> list[int]:
    return json.loads((pages_dir / "history.json").read_text())["counts"]


class TestDeduplication:
    def test_same_venue_and_time_across_sources_merges(self):
        merged, audit = deduplicate([event(TM, "1"), event(CAL, "2")])
        assert len(merged) == 1
        assert len(audit) == 1

    def test_ticketmaster_wins_for_ticketed_events(self):
        merged, _ = deduplicate([event(CAL, "2"), event(TM, "1")])
        assert merged[0].id == "ticketmaster:1"

    def test_both_origins_are_preserved_so_no_attribution_is_lost(self):
        merged, _ = deduplicate([event(TM, "1"), event(CAL, "2")])
        assert merged[0].merged_sources == ("calagator", "ticketmaster")

    def test_the_survivor_backfills_fields_it_lacks(self):
        rich = event(CAL, "2", summary="Doors at 7", listing_url="https://calagator.org/e/2")
        merged, _ = deduplicate([event(TM, "1"), rich])
        assert merged[0].id == "ticketmaster:1"
        assert merged[0].summary == "Doors at 7"

    def test_real_price_data_survives_over_unknown(self):
        priced = event(CAL, "2", price=Price(is_free=False, min=20.0, max=40.0))
        merged, _ = deduplicate([event(TM, "1"), priced])
        assert merged[0].price.min == 20.0

    def test_within_tolerance_still_merges(self):
        # Two listings of one show rarely agree to the minute; one may use doors time.
        merged, _ = deduplicate([event(TM, "1"), event(CAL, "2", start=START + timedelta(minutes=20))])
        assert len(merged) == 1

    def test_beyond_tolerance_does_not_merge(self):
        merged, _ = deduplicate([event(TM, "1"), event(CAL, "2", start=START + timedelta(hours=3))])
        assert len(merged) == 2

    def test_different_venues_do_not_merge(self):
        merged, _ = deduplicate([event(TM, "1"), event(CAL, "2", venue="Holocene")])
        assert len(merged) == 2

    def test_venue_naming_differences_still_match(self):
        merged, _ = deduplicate([event(TM, "1", venue="The Wonder Ballroom"), event(CAL, "2", venue="Wonder Ballroom")])
        assert len(merged) == 1

    def test_events_within_one_source_never_merge(self):
        # Recurring events legitimately repeat at the same venue and time.
        merged, _ = deduplicate([event(CAL, "1"), event(CAL, "2")])
        assert len(merged) == 2

    def test_missing_venue_is_not_evidence_of_sameness(self):
        merged, _ = deduplicate([event(TM, "1", venue=None), event(CAL, "2", venue=None)])
        assert len(merged) == 2

    def test_output_is_chronological(self):
        late = event(TM, "1", start=START + timedelta(days=2), venue="Holocene")
        early = event(CAL, "2", start=START, venue="Dante's")
        merged, _ = deduplicate([late, early])
        assert [e.id for e in merged] == ["calagator:2", "ticketmaster:1"]

    def test_a_pair_straddling_a_time_bucket_boundary_still_merges(self):
        # Bucketing is an optimization; it must not decide the outcome.
        base = datetime(2026, 9, 15, 19, 59, tzinfo=UTC)
        merged, _ = deduplicate([event(TM, "1", start=base), event(CAL, "2", start=base + timedelta(minutes=5))])
        assert len(merged) == 1

    def test_no_false_merges_across_a_realistic_mixed_feed(self):
        feed = [event(TM, str(i), venue=f"Venue {i}", start=START + timedelta(hours=i)) for i in range(20)]
        feed += [event(CAL, str(i), venue=f"Other {i}", start=START + timedelta(hours=i)) for i in range(20)]
        merged, audit = deduplicate(feed)
        assert len(merged) == 40
        assert audit == []


class TestFloorCheck:
    def test_passes_without_enough_history_to_judge(self):
        result = evaluate(10, [500] * (MIN_HISTORY_RUNS - 1))
        assert result.passed
        assert "insufficient history" in result.reason

    def test_passes_on_a_normal_run(self):
        assert evaluate(700, [720, 715, 730, 725]).passed

    def test_blocks_a_collapse(self):
        result = evaluate(50, [720, 715, 730, 725])
        assert not result.passed
        assert "below the floor" in result.reason

    def test_blocks_an_empty_run(self):
        assert not evaluate(0, [720, 715, 730]).passed

    def test_override_lets_a_real_drop_through(self):
        assert evaluate(0, [720, 715, 730], override=True).passed

    def test_boundary_is_the_configured_ratio_of_the_median(self):
        history = [100, 100, 100]
        threshold = int(100 * FLOOR_RATIO)
        assert evaluate(threshold, history).passed
        assert not evaluate(threshold - 1, history).passed

    def test_growth_is_never_blocked(self):
        assert evaluate(5000, [700, 710, 720]).passed

    def test_history_is_bounded(self):
        history: list[int] = []
        for i in range(100):
            history = append_history(history, i)
        assert len(history) <= 30
        assert history[-1] == 99


class TestHistoryLoading:
    """A history file we cannot read disarms the floor; it must never block a publish."""

    def test_a_missing_file_is_an_empty_baseline(self, tmp_path):
        assert load_history(tmp_path / "history.json") == []

    def test_counts_are_read_in_order(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text(json.dumps({"counts": [700, 710, 720]}))
        assert load_history(path) == [700, 710, 720]

    def test_malformed_json_does_not_raise(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text("{ truncated")
        assert load_history(path) == []

    def test_an_unexpected_top_level_shape_does_not_raise(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text("[700, 710]")
        assert load_history(path) == []

    def test_non_numeric_entries_are_discarded(self, tmp_path):
        # One bad entry would otherwise skew the median for the next thirty runs, and a
        # silently wrong baseline is worse than no baseline at all.
        path = tmp_path / "history.json"
        path.write_text(json.dumps({"counts": [700, None, "710", 720, True]}))
        assert load_history(path) == [700, 720]


class TestThePublishingPathConsultsHistory:
    """The floor was inert in production for exactly one reason: this path.

    `history.json` was read from `--output-dir`, and CI publishes with `--pages-dir`,
    so the baseline loaded empty on every run, every merge report said "insufficient
    history (0 run(s), need 3)", and the published file was overwritten with the single
    count from the run that had just finished. These tests fail if the publishing path
    ever stops reading the history it is about to rewrite.
    """

    def test_the_published_history_is_appended_to_rather_than_replaced(self, tmp_path):
        sources_dir = tmp_path / "sources"
        write_sources(sources_dir, {TM: 6, CAL: 4})
        pages_dir = make_pages_dir(tmp_path, counts=[9, 10, 11])

        assert merge_into_pages(sources_dir, pages_dir) == 0

        history = published_history(pages_dir)
        assert history == [9, 10, 11, 10], "prior runs were discarded"

    def test_history_accumulates_across_successive_runs(self, tmp_path):
        sources_dir = tmp_path / "sources"
        pages_dir = make_pages_dir(tmp_path)

        for count in (10, 12, 14, 16):
            write_sources(sources_dir, {TM: count})
            assert merge_into_pages(sources_dir, pages_dir) == 0

        assert published_history(pages_dir) == [10, 12, 14, 16]

    def test_the_floor_blocks_a_collapse_once_history_exists(self, tmp_path):
        sources_dir = tmp_path / "sources"
        write_sources(sources_dir, {TM: 2})
        pages_dir = make_pages_dir(tmp_path, counts=[800, 810, 820])

        assert merge_into_pages(sources_dir, pages_dir) == 3

    def test_a_blocked_run_publishes_nothing_at_all(self, tmp_path):
        # Refusing to publish is the entire point; a gutted feed must not reach users.
        sources_dir = tmp_path / "sources"
        write_sources(sources_dir, {TM: 2})
        pages_dir = make_pages_dir(tmp_path, counts=[800, 810, 820])

        merge_into_pages(sources_dir, pages_dir)

        assert not (pages_dir / "events.json").exists()
        assert published_history(pages_dir) == [800, 810, 820]

    def test_an_operator_override_still_publishes_a_collapse(self, tmp_path):
        sources_dir = tmp_path / "sources"
        write_sources(sources_dir, {TM: 2})
        pages_dir = make_pages_dir(tmp_path, counts=[800, 810, 820])

        assert merge_into_pages(sources_dir, pages_dir, "--override-floor") == 0
        assert (pages_dir / "events.json").exists()

    def test_a_healthy_run_against_a_real_baseline_is_not_blocked(self, tmp_path):
        sources_dir = tmp_path / "sources"
        write_sources(sources_dir, {TM: 12, CAL: 8})
        pages_dir = make_pages_dir(tmp_path, counts=[19, 20, 21])

        assert merge_into_pages(sources_dir, pages_dir) == 0

    def test_a_one_entry_history_is_one_run_of_evidence_not_three(self, tmp_path):
        # The live file was flattened to {"counts": [2511]} by the bug this fixes.
        # Rearming must not read that lone sample as a baseline: a single count is one
        # run of evidence, and judging a collapse against it would be guessing.
        sources_dir = tmp_path / "sources"
        write_sources(sources_dir, {TM: 2})
        pages_dir = make_pages_dir(tmp_path, counts=[2511])

        assert merge_into_pages(sources_dir, pages_dir) == 0
        assert published_history(pages_dir) == [2511, 2]

    def test_the_floor_arms_on_the_third_run_after_a_flattened_history(self, tmp_path):
        # The recovery path from the live state: the flattened entry counts as one run,
        # two healthy runs accumulate on top of it, and the guard is live from there.
        sources_dir = tmp_path / "sources"
        pages_dir = make_pages_dir(tmp_path, counts=[2511])

        for count in (20, 20):
            write_sources(sources_dir, {TM: count})
            assert merge_into_pages(sources_dir, pages_dir) == 0

        write_sources(sources_dir, {TM: 1})
        assert merge_into_pages(sources_dir, pages_dir) == 3

    def test_an_unreadable_history_disarms_the_floor_rather_than_blocking(self, tmp_path):
        sources_dir = tmp_path / "sources"
        write_sources(sources_dir, {TM: 3})
        pages_dir = make_pages_dir(tmp_path)
        (pages_dir / "history.json").write_text("{ truncated")

        assert merge_into_pages(sources_dir, pages_dir) == 0
        assert published_history(pages_dir) == [3]

    def test_the_local_output_path_accumulates_too(self, tmp_path):
        # The branch that always worked. It has to keep working: it is how a collapse
        # gets reproduced off CI before anyone reaches for --override-floor.
        output_dir = tmp_path / "feed"
        sources_dir = tmp_path / "sources"
        output_dir.mkdir()
        (output_dir / "history.json").write_text(dump_json({"counts": [6, 7, 8]}))
        write_sources(sources_dir, {TM: 7})

        assert main(["--sources-dir", str(sources_dir), "--output-dir", str(output_dir)]) == 0
        assert json.loads((output_dir / "history.json").read_text())["counts"] == [6, 7, 8, 7]


def entry_for(index: dict, source_id: str) -> dict | None:
    return next((e for e in index["sources"] if e["source_id"] == source_id), None)


class TestConfiguredSourcesAppearInTheIndex:
    """A source that has never published must report as broken, not go missing.

    Built only from the files on disk, the index could describe a source that failed
    its last run but not one that has never succeeded at all: with no file there was
    no entry, so the app's Sources tab omitted it silently. That is the dishonesty the
    index was created to prevent, applied to the worst case it has.
    """

    def test_a_configured_source_with_no_file_is_reported_as_error(self):
        index = _build_index([source_payload(TM, 3)], [TM, CAL], NOW)
        assert entry_for(index, "calagator")["status"] == "error"

    def test_it_reports_a_null_last_run_and_a_zero_count(self):
        index = _build_index([], [CAL], NOW)
        entry = entry_for(index, "calagator")
        assert entry["last_run_at"] is None
        assert entry["event_count"] == 0

    def test_its_url_is_null_because_no_such_file_exists(self):
        assert entry_for(_build_index([], [CAL], NOW), "calagator")["url"] is None

    def test_a_published_source_is_not_duplicated_by_its_registry_entry(self):
        index = _build_index([source_payload(TM, 3)], [TM, CAL], NOW)
        assert [e["source_id"] for e in index["sources"]] == ["calagator", "ticketmaster"]

    def test_a_published_source_keeps_its_own_status_and_count(self):
        index = _build_index([source_payload(TM, 3)], [TM, CAL], NOW)
        entry = entry_for(index, "ticketmaster")
        assert entry["status"] == "ok"
        assert entry["event_count"] == 3
        assert entry["url"] == "sources/ticketmaster.json"

    def test_a_source_on_disk_but_not_configured_is_still_reported(self):
        # A source removed from the tree while its file lingers on gh-pages. Dropping
        # it would hide events that are still in the feed.
        index = _build_index([source_payload(TM, 3)], [], NOW)
        assert entry_for(index, "ticketmaster")["status"] == "ok"

    def test_the_index_still_validates_with_a_never_published_source(self):
        validate_sources_index(_build_index([source_payload(TM, 3)], [TM, CAL], NOW))

    def test_entries_stay_sorted_by_source_id(self):
        index = _build_index([source_payload(TM, 1)], [TM, CAL, Source(id="obt", name="OBT")], NOW)
        ids = [e["source_id"] for e in index["sources"]]
        assert ids == sorted(ids)


class TestStalenessSurvivesTheRegistry:
    """The existing downgrade has to keep working now that it lives in one place."""

    def test_a_quiet_source_is_downgraded_to_stale(self):
        quiet = source_payload(TM, 3, generated_at="2026-07-27T02:00:00+00:00")
        assert entry_for(_build_index([quiet], [TM], NOW), "ticketmaster")["status"] == "stale"

    def test_a_recent_source_stays_ok(self):
        recent = source_payload(TM, 3, generated_at="2026-07-27T11:00:00+00:00")
        assert entry_for(_build_index([recent], [TM], NOW), "ticketmaster")["status"] == "ok"

    def test_a_source_reporting_error_is_not_relabelled_stale(self):
        broken = source_payload(TM, 3, generated_at="2026-07-27T02:00:00+00:00", status="error")
        assert entry_for(_build_index([broken], [TM], NOW), "ticketmaster")["status"] == "error"

    def test_an_unparseable_timestamp_is_an_error_with_no_last_run(self):
        garbled = source_payload(TM, 3, generated_at="not a timestamp")
        entry = entry_for(_build_index([garbled], [TM], NOW), "ticketmaster")
        assert entry["status"] == "error"
        assert entry["last_run_at"] is None

    def test_a_never_published_source_is_not_downgraded_further(self):
        assert entry_for(_build_index([], [CAL], NOW), "calagator")["status"] == "error"


class TestTheRegistryTracksThePackageTree:
    """Discovery from `pipeline.sources` rather than a hand-kept list.

    A constant would go stale the first time someone adds a source directory and
    forgets the entry, and the symptom would be the same one being fixed here: a
    source that is missing rather than one that is broken.
    """

    def test_every_source_package_is_discovered(self):
        package_dirs = {
            p.name
            for p in (Path(__file__).resolve().parents[2] / "sources").iterdir()
            if p.is_dir() and (p / "config.py").exists()
        }
        assert {s.id for s in configured_sources()} == package_dirs

    def test_eventbrite_is_configured_even_though_it_has_never_published(self):
        assert "eventbrite" in {s.id for s in configured_sources()}

    def test_discovery_is_ordered_so_the_index_is_stable(self):
        ids = [s.id for s in configured_sources()]
        assert ids == sorted(ids)


class TestABrokenSourceSurfacesEndToEnd:
    def test_a_configured_source_with_no_file_reaches_the_published_index(self, tmp_path):
        sources_dir = tmp_path / "sources"
        write_sources(sources_dir, {TM: 5})
        pages_dir = make_pages_dir(tmp_path)

        assert merge_into_pages(sources_dir, pages_dir) == 0

        index = json.loads((pages_dir / "sources" / "index.json").read_text())
        assert entry_for(index, "eventbrite") == {
            "source_id": "eventbrite",
            "last_run_at": None,
            "event_count": 0,
            "status": "error",
            "url": None,
        }

    def test_no_configured_source_is_missing_from_the_published_index(self, tmp_path):
        sources_dir = tmp_path / "sources"
        write_sources(sources_dir, {TM: 5})
        pages_dir = make_pages_dir(tmp_path)
        merge_into_pages(sources_dir, pages_dir)

        index = json.loads((pages_dir / "sources" / "index.json").read_text())
        reported = {e["source_id"] for e in index["sources"]}
        assert {s.id for s in configured_sources()} <= reported
