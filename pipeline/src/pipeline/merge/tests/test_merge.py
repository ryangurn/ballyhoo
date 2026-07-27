"""Tests for cross-source merge, deduplication, and the floor check."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pipeline.common.models import Category, Event, Price, Source, Venue
from pipeline.merge.dedupe import deduplicate
from pipeline.merge.floor import FLOOR_RATIO, MIN_HISTORY_RUNS, append_history, evaluate

TM = Source(id="ticketmaster", name="Ticketmaster")
CAL = Source(id="calagator", name="Calagator")
START = datetime(2026, 9, 15, 20, 0, tzinfo=UTC)


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
