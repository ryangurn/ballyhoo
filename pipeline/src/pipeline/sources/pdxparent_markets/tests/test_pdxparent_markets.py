"""Tests for the PDX Parent farmers-market roundup source.

Every schedule string here is copied verbatim from the live page. That matters more
than usual: this source infers the dates it publishes from English prose, so the test
suite is the record of which sentences we have actually seen and what each one means.
An invented sentence would prove nothing about whether the parser works on the page.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.recurrence import expand
from pipeline.common.validate import validate_per_source
from pipeline.sources.pdxparent_markets import config
from pipeline.sources.pdxparent_markets.fetch import RawMarket, parse_roundup
from pipeline.sources.pdxparent_markets.normalize import (
    is_covered_elsewhere,
    market_slug,
    normalize,
)
from pipeline.sources.pdxparent_markets.schedule import parse, parse_season, parse_time_range

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)

MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = range(7)

# The page's unclosed <p> tags are reproduced exactly; a tree parse nests them.
ROUNDUP_HTML = """
<div class="post-content">
<p class="wp-block-paragraph"><a href="#Sundays">Sundays</a>, jump link<br>not a market
<p class="wp-block-paragraph"><a href="https://www.montavillamarket.org/">Montavilla Farmers Market</a>, SE Stark &amp; 76th<br>Every Sunday, May-December 20, 10 am-2 pm; every other Sunday, January-April.
<p class="wp-block-paragraph"><a href="https://www.portlandfarmersmarket.org/index.php/markets/king/">King Portland Farmers Market</a>, NE 7th &amp; NE Wygant<br>Sundays, May 3-November 22, 2026, 10 am-2 pm
<p class="wp-block-paragraph"><a href="https://www.peoples.coop/farmers-market">People&#8217;s Farmers Market</a>, 3029 SE 21st Ave.<br>Wednesdays, 2-7 pm (Winter hours 2-6 pm)
<p class="wp-block-paragraph"><a href="https://cullyfarmersmarket.com/">Cully Farmers Market</a>, NE 42nd Ave. &amp; NE Alberta St., Portland<br>Thursdays, May-September 2026, 4-8 pm
<p class="wp-block-paragraph"><a href="https://hollywoodfarmersmarket.org/">Hollywood&#8217;s Farmers Market</a>, NE Hancock<br>Saturdays, year-round. April-December 19, 8 am-1 pm
</div>
"""


class TestRoundupParsing:
    def test_reads_markets_from_unclosed_paragraphs(self):
        markets = parse_roundup(ROUNDUP_HTML)
        assert [m.name for m in markets] == [
            "Montavilla Farmers Market",
            "King Portland Farmers Market",
            "People’s Farmers Market",
            "Cully Farmers Market",
            "Hollywood’s Farmers Market",
        ]

    def test_a_paragraph_does_not_swallow_the_ones_after_it(self):
        # The page never closes a <p>, so a tree parse nests every market inside the
        # first. Each schedule here must belong to its own market.
        markets = parse_roundup(ROUNDUP_HTML)
        montavilla = markets[0]
        assert montavilla.schedule_line.startswith("Every Sunday, May-December 20")
        assert "Wednesdays" not in montavilla.schedule_line

    def test_splits_name_address_and_schedule(self):
        montavilla = parse_roundup(ROUNDUP_HTML)[0]
        assert montavilla.address == "SE Stark & 76th"
        assert montavilla.url == "https://www.montavillamarket.org/"

    def test_the_day_jump_links_are_not_markets(self):
        assert not [m for m in parse_roundup(ROUNDUP_HTML) if m.name == "Sundays"]

    def test_html_entities_are_decoded(self):
        peoples = next(m for m in parse_roundup(ROUNDUP_HTML) if "People" in m.name)
        assert peoples.name == "People’s Farmers Market"


class TestTimeRange:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("10 am-2 pm", (time(10, 0), time(14, 0))),
            ("9:30 am-2 pm", (time(9, 30), time(14, 0))),
            ("8:30 am-1:30 pm", (time(8, 30), time(13, 30))),
            ("5-8:30 pm", (time(17, 0), time(20, 30))),
            ("4:30-8 pm", (time(16, 30), time(20, 0))),
            ("2-7 pm", (time(14, 0), time(19, 0))),
            ("3-7 pm", (time(15, 0), time(19, 0))),
        ],
    )
    def test_reads_the_forms_the_page_uses(self, text, expected):
        assert parse_time_range(text) == expected

    def test_a_bare_start_crossing_noon_is_read_as_morning(self):
        # "12-5 pm" means noon to five, and "10-2 pm" means ten in the morning.
        # Sharing the trailing meridiem blindly would invert both.
        assert parse_time_range("12-5 pm") == (time(12, 0), time(17, 0))
        assert parse_time_range("10-2 pm") == (time(10, 0), time(14, 0))

    @pytest.mark.parametrize("text", ["", "all day", "whenever", "10 am"])
    def test_rejects_what_it_cannot_read(self, text):
        assert parse_time_range(text) is None


class TestSeason:
    def test_a_year_after_the_month_is_not_a_day_of_the_month(self):
        # "June-September 2026" ends on 30 September, not the 20th. Reading the 20
        # out of 2026 shortened six markets' seasons by ten days before this was
        # caught.
        season = parse_season("Thursdays, June-September 2026, 10 am-2 pm")
        assert season.end.month == 9
        assert season.end.day == 30

    def test_an_explicit_closing_day_is_kept(self):
        season = parse_season("Sundays, April 26-October 25, 2026, 10 am-2 pm")
        assert (season.start.month, season.start.day) == (4, 26)
        assert (season.end.month, season.end.day) == (10, 25)

    def test_a_month_with_no_day_runs_to_its_end(self):
        season = parse_season("Sundays, May-October, 9:30 am-2 pm")
        assert (season.start.month, season.start.day) == (5, 1)
        assert (season.end.month, season.end.day) == (10, 31)

    def test_february_ends_on_the_29th_at_the_latest(self):
        season = parse_season("Saturdays, February-March 2026, 10 am-1:30 pm")
        assert (season.start.month, season.start.day) == (2, 1)
        assert (season.end.month, season.end.day) == (3, 31)

    def test_the_word_through_works_like_a_dash(self):
        season = parse_season("Tuesdays, 10 am-2 pm, June through September 2026")
        assert (season.start.month, season.end.month) == (6, 9)

    def test_no_season_is_none(self):
        assert parse_season("Wednesdays, 2-7 pm (Winter hours 2-6 pm)") is None


class TestScheduleParsing:
    def test_a_plain_weekly_season(self):
        parsed = parse("Sundays, April 26-October 25, 2026, 10 am-2 pm")
        assert len(parsed.rules) == 1
        rule = parsed.rules[0]
        assert rule.weekday == SUNDAY
        assert rule.start_time == time(10, 0)
        assert rule.ordinals == frozenset()

    def test_time_stated_before_the_season(self):
        parsed = parse("Sundays, 10 am-2 pm, June-September")
        assert parsed.rules[0].start_time == time(10, 0)
        assert parsed.rules[0].season.start.month == 6

    def test_numeric_ordinals(self):
        parsed = parse("1st and 3rd Mondays, June-October, 3-7 pm")
        assert parsed.rules[0].weekday == MONDAY
        assert parsed.rules[0].ordinals == frozenset({1, 3})

    def test_written_ordinals(self):
        parsed = parse("Second and fourth Thursdays, June 11-October 22, 2026, 4-8 pm")
        assert parsed.rules[0].weekday == THURSDAY
        assert parsed.rules[0].ordinals == frozenset({2, 4})

    def test_a_singular_ordinal(self):
        parsed = parse("First Wednesdays, May 6-October 7, 2026, 4:30-8 pm")
        assert parsed.rules[0].ordinals == frozenset({1})

    def test_no_season_means_year_round(self):
        parsed = parse("Wednesdays, 2-7 pm (Winter hours 2-6 pm)")
        assert parsed.rules[0].weekday == WEDNESDAY
        assert parsed.rules[0].season.contains(date(2026, 1, 15))
        assert parsed.rules[0].season.contains(date(2026, 7, 15))

    def test_two_seasons_separated_by_a_semicolon_both_survive(self):
        parsed = parse(
            "Saturdays, February-March 2026, 10 am-1:30 pm; April-November 21, 2026, 8:30 am-1:30 pm."
        )
        assert len(parsed.rules) == 2
        # The second clause names no weekday and must inherit Saturday.
        assert [r.weekday for r in parsed.rules] == [SATURDAY, SATURDAY]
        assert [r.start_time for r in parsed.rules] == [time(10, 0), time(8, 30)]

    def test_an_unanchored_secondary_schedule_is_dropped(self):
        # "every other Sunday" has no anchor date, so its dates cannot be derived.
        parsed = parse("Every Sunday, May-December 20, 10 am-2 pm; every other Sunday, January-April.")
        assert len(parsed.rules) == 1
        assert parsed.rules[0].season.end.day == 20
        assert parsed.problems

    def test_a_trailing_vague_note_does_not_void_the_primary_rule(self):
        # Hillsdale states a perfectly good schedule and then mentions winter dates
        # it does not specify. Rejecting the whole clause lost a real market.
        parsed = parse(
            "Sundays, April 12-November 22, 2026, 9 am-1 pm. Open select dates twice monthly in winter."
        )
        assert len(parsed.rules) == 1
        assert parsed.rules[0].weekday == SUNDAY
        assert parsed.rules[0].start_time == time(9, 0)

    def test_a_clause_that_moves_the_market_is_dropped(self):
        # Woodlawn's winter market is at a different address, and the roundup gives
        # only one address per market, so those dates would get the wrong pin.
        parsed = parse(
            "Saturdays, June-October 2026, 9 am-1 pm; December-May at Classic Foods, "
            "817 NE Madrona St., on the second Saturday of the month, 11 am-2 pm"
        )
        assert len(parsed.rules) == 1
        assert parsed.rules[0].season.start.month == 6
        assert any("elsewhere" in p for p in parsed.problems)

    def test_only_the_first_weekday_in_a_clause_counts(self):
        # Otherwise Troutdale's Friday hours attach to its Sunday listing.
        parsed = parse("Sundays, 10 am-4 pm. Also open Fridays, 2-7 pm, and Saturdays, 10 am-4 pm.")
        assert len(parsed.rules) == 1
        assert parsed.rules[0].weekday == SUNDAY
        assert parsed.rules[0].start_time == time(10, 0)

    def test_explicit_closures_are_captured(self):
        parsed = parse("Fridays, May 15-October 16, 2026, 2-7 pm. No market July 10")
        assert parsed.skipped_dates == frozenset({(7, 10)})

    def test_the_next_sections_heading_is_stripped(self):
        # Paragraphs run into the following heading, which would otherwise supply a
        # spurious weekday.
        parsed = parse("1st and 3rd Mondays, June-October, 3-7 pm Tuesday Farmers Markets Courtesy of X")
        assert len(parsed.rules) == 1
        assert parsed.rules[0].weekday == MONDAY

    @pytest.mark.parametrize("line", ["", "Open seasonally", "Call for hours"])
    def test_unreadable_schedules_yield_nothing(self, line):
        parsed = parse(line)
        assert not parsed.is_usable
        assert parsed.problems


class TestCoverageExclusion:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://www.portlandfarmersmarket.org/index.php/markets/king/", True),
            ("https://hollywoodfarmersmarket.org/", True),
            ("https://www.montavillamarket.org/", False),
            ("https://woodstockmarketpdx.com/", False),
        ],
    )
    def test_markets_with_their_own_calendar_are_skipped(self, url, expected):
        market = RawMarket(name="X", address=None, schedule_line="Sundays, 10 am-2 pm", url=url)
        assert is_covered_elsewhere(market) is expected

    def test_the_excluded_markets_produce_no_events(self):
        events, counters = normalize(parse_roundup(ROUNDUP_HTML), now=NOW)
        assert counters.covered_elsewhere == 2
        assert not [e for e in events if "King" in e.title or "Hollywood" in e.title]


class TestSlugs:
    def test_a_curly_apostrophe_slugs_the_same_as_a_straight_one(self):
        # An invisible character swap upstream must not orphan every bookmark.
        assert market_slug("Camas Farmer’s Market") == market_slug("Camas Farmer's Market")

    def test_slugs_are_readable(self):
        assert market_slug("Montavilla Farmers Market") == "montavilla-farmers-market"


class TestNormalize:
    def test_expands_markets_into_dated_events(self):
        events, counters = normalize(parse_roundup(ROUNDUP_HTML), now=NOW)
        assert counters.markets_expanded == 3
        assert events

    def test_ids_are_slug_plus_date(self):
        events, _ = normalize(parse_roundup(ROUNDUP_HTML), now=NOW)
        montavilla = [e for e in events if e.title == "Montavilla Farmers Market"]
        assert all(e.id.startswith("pdxparent_markets:montavilla-farmers-market@") for e in montavilla)
        assert len({e.id for e in events}) == len(events)

    def test_ids_do_not_move_when_the_run_time_does(self):
        first, _ = normalize(parse_roundup(ROUNDUP_HTML), now=NOW)
        later, _ = normalize(parse_roundup(ROUNDUP_HTML), now=NOW + timedelta(days=21))
        by_id = {e.id: e.start_at for e in first}
        overlap = [e for e in later if e.id in by_id]
        assert len(overlap) > 10
        assert all(e.start_at == by_id[e.id] for e in overlap)

    def test_expansion_is_bounded(self):
        events, _ = normalize(parse_roundup(ROUNDUP_HTML), now=NOW)
        latest = max(e.start_at for e in events)
        assert latest <= NOW + config.EXPANSION_WINDOW + timedelta(days=1)
        per_market = {}
        for event in events:
            per_market[event.title] = per_market.get(event.title, 0) + 1
        assert all(count <= config.MAX_OCCURRENCES_PER_MARKET for count in per_market.values())

    def test_each_market_lands_on_its_own_weekday(self):
        events, _ = normalize(parse_roundup(ROUNDUP_HTML), now=NOW)
        assert all(e.start_at.weekday() == WEDNESDAY for e in events if "People" in e.title)
        assert all(e.start_at.weekday() == SUNDAY for e in events if "Montavilla" in e.title)

    def test_times_are_portland_local(self):
        events, _ = normalize(parse_roundup(ROUNDUP_HTML), now=NOW)
        peoples = next(e for e in events if "People" in e.title)
        assert peoples.start_at.hour == 14
        assert peoples.start_at.utcoffset() == timedelta(hours=-7)

    def test_known_venues_get_coordinates(self):
        events, _ = normalize(parse_roundup(ROUNDUP_HTML), now=NOW)
        montavilla = next(e for e in events if "Montavilla" in e.title)
        assert montavilla.venue.latitude == pytest.approx(45.519, abs=0.02)

    def test_markets_are_free(self):
        events, _ = normalize(parse_roundup(ROUNDUP_HTML), now=NOW)
        assert all(e.price == Price.free() for e in events)

    def test_markets_are_categorised(self):
        events, _ = normalize(parse_roundup(ROUNDUP_HTML), now=NOW)
        assert all(e.categories == (Category.MARKET, Category.FOOD) for e in events)

    def test_events_are_sorted(self):
        events, _ = normalize(parse_roundup(ROUNDUP_HTML), now=NOW)
        assert [e.start_at for e in events] == sorted(e.start_at for e in events)

    def test_output_validates(self):
        events, _ = normalize(parse_roundup(ROUNDUP_HTML), now=NOW)
        validate_per_source(build_per_source_feed("pdxparent_markets", events, generated_at=NOW))


class TestExplicitClosures:
    def test_a_no_market_date_is_not_published(self):
        market = RawMarket(
            name="Mt Hood Farmers Market (Sandy)",
            address="38600 Proctor Blvd, Sandy",
            schedule_line="Fridays, May 15-October 16, 2026, 2-7 pm. No market July 10",
            url="https://mounthoodfarmersmarket.org/",
        )
        # Run from before the closure so the date falls inside the window.
        events, counters = normalize([market], now=datetime(2026, 6, 20, 12, 0, tzinfo=UTC))
        assert counters.skipped_dates == 1
        assert not [e for e in events if e.start_at.date() == date(2026, 7, 10)]
        assert [e for e in events if e.start_at.date() == date(2026, 7, 17)]


class TestSeasonBoundaries:
    def test_a_market_out_of_season_produces_nothing(self):
        market = RawMarket(
            name="Winter Only Market",
            address=None,
            schedule_line="Saturdays, December-February, 10 am-2 pm",
            url="https://example.com/",
        )
        events, counters = normalize([market], now=NOW)
        assert events == []
        assert counters.no_occurrences == 1

    def test_a_season_wrapping_new_year_is_continuous(self):
        parsed = parse("Saturdays, November-February, 10 am-2 pm")
        occurrences = expand(
            parsed.rules,
            window_start=date(2026, 12, 20),
            window_end=date(2027, 1, 20),
            zone=__import__("zoneinfo").ZoneInfo("America/Los_Angeles"),
        )
        days = [o.day for o in occurrences]
        assert date(2026, 12, 26) in days
        assert date(2027, 1, 2) in days
