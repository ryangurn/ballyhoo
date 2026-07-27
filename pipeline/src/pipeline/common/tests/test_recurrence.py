"""Tests for weekly recurrence expansion.

The cases here are the real ones from Portland farmers markets rather than invented
ones: a plain weekly season, a "2nd and 4th Saturdays" winter schedule, a market that
runs to a specific day in December, and the pair of rules Hollywood publishes, whose
seasons abut and must not both claim a date.
"""

from __future__ import annotations

from datetime import date, time
from zoneinfo import ZoneInfo

import pytest

from pipeline.common.recurrence import (
    YEAR_ROUND,
    MonthDay,
    Season,
    WeeklyRule,
    expand,
    ordinal_of_weekday,
)

PORTLAND = ZoneInfo("America/Los_Angeles")

SATURDAY = 5
WEDNESDAY = 2

# "April-December 19th: Every Saturday 8am-1pm" — Hollywood's main season.
MAIN_SEASON = WeeklyRule(
    weekday=SATURDAY,
    start_time=time(8, 0),
    end_time=time(13, 0),
    season=Season(MonthDay(4, 1), MonthDay(12, 19)),
)

# "January-March: 2nd and 4th Saturdays 9am-1pm" — the winter schedule.
WINTER_SEASON = WeeklyRule(
    weekday=SATURDAY,
    start_time=time(9, 0),
    end_time=time(13, 0),
    season=Season(MonthDay(1, 1), MonthDay(3, 31)),
    ordinals=frozenset({2, 4}),
)


class TestOrdinalOfWeekday:
    @pytest.mark.parametrize(
        "day,expected",
        [
            (date(2026, 8, 1), 1),
            (date(2026, 8, 8), 2),
            (date(2026, 8, 15), 3),
            (date(2026, 8, 22), 4),
            (date(2026, 8, 29), 5),
        ],
    )
    def test_counts_within_the_month(self, day, expected):
        assert ordinal_of_weekday(day) == expected

    def test_is_position_in_month_not_week_of_year(self):
        # The 1st of a month is always the first of its weekday, whatever the
        # surrounding week looks like.
        assert ordinal_of_weekday(date(2026, 9, 1)) == 1


class TestSeason:
    def test_a_plain_season_contains_its_bounds(self):
        season = Season(MonthDay(4, 1), MonthDay(12, 19))
        assert season.contains(date(2026, 4, 1))
        assert season.contains(date(2026, 12, 19))
        assert not season.contains(date(2026, 12, 20))
        assert not season.contains(date(2026, 3, 31))

    def test_a_season_wrapping_new_year(self):
        # November through February is one continuous season, not an empty one.
        season = Season(MonthDay(11, 1), MonthDay(2, 28))
        assert season.wraps_year_end
        assert season.contains(date(2026, 12, 25))
        assert season.contains(date(2026, 1, 15))
        assert not season.contains(date(2026, 6, 1))

    def test_year_round_contains_everything(self):
        for month in range(1, 13):
            assert YEAR_ROUND.contains(date(2026, month, 15))

    def test_last_of_month_bound_tolerates_short_months(self):
        # `last_of` uses day 31 as an upper bound; February must still end correctly.
        season = Season(MonthDay(1, 1), MonthDay.last_of(2))
        assert season.contains(date(2026, 2, 28))
        assert not season.contains(date(2026, 3, 1))


class TestExpansion:
    def test_produces_one_occurrence_per_matching_week(self):
        occurrences = expand(
            [MAIN_SEASON], window_start=date(2026, 8, 1), window_end=date(2026, 8, 31), zone=PORTLAND
        )
        assert [o.day for o in occurrences] == [
            date(2026, 8, 1),
            date(2026, 8, 8),
            date(2026, 8, 15),
            date(2026, 8, 22),
            date(2026, 8, 29),
        ]

    def test_times_are_localised(self):
        occurrences = expand(
            [MAIN_SEASON], window_start=date(2026, 8, 1), window_end=date(2026, 8, 1), zone=PORTLAND
        )
        assert occurrences[0].start_at.isoformat() == "2026-08-01T08:00:00-07:00"
        assert occurrences[0].end_at.isoformat() == "2026-08-01T13:00:00-07:00"

    def test_crossing_the_dst_boundary_keeps_wall_clock_time(self):
        # A market opens at 8am by the clock on the wall, both sides of the change.
        occurrences = expand(
            [WeeklyRule(weekday=SATURDAY, start_time=time(8, 0), end_time=time(13, 0))],
            window_start=date(2026, 10, 31),
            window_end=date(2026, 11, 14),
            zone=PORTLAND,
        )
        offsets = {o.day: o.start_at.utcoffset().total_seconds() / 3600 for o in occurrences}
        assert offsets[date(2026, 10, 31)] == -7
        assert offsets[date(2026, 11, 7)] == -8
        assert all(o.start_at.hour == 8 for o in occurrences)

    def test_the_season_bounds_the_expansion(self):
        occurrences = expand(
            [MAIN_SEASON], window_start=date(2026, 12, 1), window_end=date(2027, 1, 31), zone=PORTLAND
        )
        # Season ends 19 December, so nothing after it and nothing in January.
        assert [o.day for o in occurrences] == [date(2026, 12, 5), date(2026, 12, 12), date(2026, 12, 19)]

    def test_ordinals_restrict_to_those_weeks(self):
        occurrences = expand(
            [WINTER_SEASON], window_start=date(2027, 1, 1), window_end=date(2027, 1, 31), zone=PORTLAND
        )
        # January 2027's Saturdays are 2, 9, 16, 23, 30 — the 2nd and 4th are 9 and 23.
        assert [o.day for o in occurrences] == [date(2027, 1, 9), date(2027, 1, 23)]

    def test_the_window_clamps_a_rule_that_would_run_forever(self):
        occurrences = expand(
            [WeeklyRule(weekday=SATURDAY, start_time=time(9, 0))],
            window_start=date(2026, 8, 1),
            window_end=date(2026, 9, 30),
            zone=PORTLAND,
        )
        # Nine Saturdays, not an unbounded sequence.
        assert len(occurrences) == 9
        assert all(date(2026, 8, 1) <= o.day <= date(2026, 9, 30) for o in occurrences)

    def test_max_occurrences_is_a_backstop(self):
        occurrences = expand(
            [WeeklyRule(weekday=SATURDAY, start_time=time(9, 0))],
            window_start=date(2026, 1, 1),
            window_end=date(2036, 1, 1),
            zone=PORTLAND,
            max_occurrences=5,
        )
        assert len(occurrences) == 5

    def test_an_inverted_window_yields_nothing(self):
        assert expand([MAIN_SEASON], window_start=date(2026, 9, 1), window_end=date(2026, 8, 1), zone=PORTLAND) == []

    def test_an_end_time_before_the_start_is_dropped_not_wrapped(self):
        occurrences = expand(
            [WeeklyRule(weekday=SATURDAY, start_time=time(14, 0), end_time=time(9, 0))],
            window_start=date(2026, 8, 1),
            window_end=date(2026, 8, 1),
            zone=PORTLAND,
        )
        assert occurrences[0].end_at is None


class TestOverlappingRules:
    def test_the_first_matching_rule_wins_a_date(self):
        # Hollywood's two seasons abut rather than overlap, but a source that states
        # a general rule plus a seasonal override must not produce two events on one
        # day. Most specific first.
        general = WeeklyRule(weekday=SATURDAY, start_time=time(9, 0), end_time=time(14, 0))
        specific = WeeklyRule(
            weekday=SATURDAY,
            start_time=time(8, 0),
            end_time=time(13, 0),
            season=Season(MonthDay(8, 1), MonthDay(8, 31)),
        )
        occurrences = expand(
            [specific, general], window_start=date(2026, 8, 1), window_end=date(2026, 8, 8), zone=PORTLAND
        )
        assert len(occurrences) == 2
        assert all(o.start_at.hour == 8 for o in occurrences)

    def test_both_hollywood_seasons_together_cover_the_year_without_collision(self):
        occurrences = expand(
            [MAIN_SEASON, WINTER_SEASON],
            window_start=date(2026, 12, 1),
            window_end=date(2027, 2, 28),
            zone=PORTLAND,
        )
        days = [o.day for o in occurrences]
        assert len(days) == len(set(days))
        # December runs weekly to the 19th, then the winter schedule resumes.
        assert date(2026, 12, 19) in days
        assert date(2026, 12, 26) not in days
        assert date(2027, 1, 9) in days
        # December occurrences open at 8, January ones at 9.
        by_day = {o.day: o.start_at.hour for o in occurrences}
        assert by_day[date(2026, 12, 19)] == 8
        assert by_day[date(2027, 1, 9)] == 9


class TestIdStability:
    def test_the_date_key_does_not_depend_on_the_run(self):
        # The whole point: a bookmark must survive the pipeline running again.
        early = expand([MAIN_SEASON], window_start=date(2026, 8, 1), window_end=date(2026, 9, 30), zone=PORTLAND)
        late = expand([MAIN_SEASON], window_start=date(2026, 8, 15), window_end=date(2026, 10, 31), zone=PORTLAND)
        overlap_early = {o.date_key for o in early}
        overlap_late = {o.date_key for o in late}
        shared = overlap_early & overlap_late
        assert shared
        assert shared == {
            o.date_key for o in early if date(2026, 8, 15) <= o.day <= date(2026, 9, 30)
        }

    def test_the_date_key_is_the_iso_date(self):
        occurrence = expand(
            [MAIN_SEASON], window_start=date(2026, 8, 1), window_end=date(2026, 8, 1), zone=PORTLAND
        )[0]
        assert occurrence.date_key == "2026-08-01"


class TestValidation:
    def test_a_bad_weekday_is_rejected(self):
        with pytest.raises(ValueError, match="weekday"):
            WeeklyRule(weekday=7, start_time=time(9, 0))

    def test_a_bad_ordinal_is_rejected(self):
        with pytest.raises(ValueError, match="ordinals"):
            WeeklyRule(weekday=SATURDAY, start_time=time(9, 0), ordinals=frozenset({0}))

    def test_a_bad_month_is_rejected(self):
        with pytest.raises(ValueError, match="month"):
            MonthDay(13, 1)


class TestWednesdayMarket:
    def test_a_midweek_market_expands_on_its_own_weekday(self):
        # Shemanski Park runs Wednesdays; nothing about the code assumes Saturday.
        rule = WeeklyRule(
            weekday=WEDNESDAY,
            start_time=time(10, 0),
            end_time=time(14, 0),
            season=Season(MonthDay(5, 6), MonthDay(10, 28)),
        )
        occurrences = expand(
            [rule], window_start=date(2026, 5, 1), window_end=date(2026, 5, 31), zone=PORTLAND
        )
        assert [o.day for o in occurrences] == [
            date(2026, 5, 6),
            date(2026, 5, 13),
            date(2026, 5, 20),
            date(2026, 5, 27),
        ]
        assert all(o.day.weekday() == WEDNESDAY for o in occurrences)
