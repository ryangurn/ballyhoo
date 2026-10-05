"""Tests for the neighborhood farmers markets source.

Two halves. The tripwire: a market's days publish only while every sentence its rules
were encoded from is still on its page, and the comparison has to survive re-rendered
markup without surviving a changed schedule. And the encoding: `through` keeping a
dated sentence from repeating into the next year, explicit days, skipped dates, and
nth-weekday rules.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
import requests
import responses

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.validate import validate_per_source
from pipeline.sources.neighborhood_markets import config
from pipeline.sources.neighborhood_markets.fetch import NeighborhoodFetchError, fetch_pages, page_text, squash
from pipeline.sources.neighborhood_markets.markets import MARKETS, Market
from pipeline.sources.neighborhood_markets.normalize import (
    COORDINATES,
    check_statements,
    normalize,
    occurrences,
)

ZONE = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)


def market(slug: str) -> Market:
    return next(m for m in MARKETS if m.slug == slug)


def pages_as_published(markets=MARKETS) -> dict[str, str]:
    """Every cited page, containing exactly the statements copied from it."""
    texts: dict[str, list[str]] = {}
    for m in markets:
        for statement in m.statements:
            texts.setdefault(statement.url, []).append(statement.text)
    return {url: squash(" ".join(parts)) for url, parts in texts.items()}


def days(slug: str, today: date) -> list[date]:
    return [o.day for o in occurrences(market(slug), today=today, zone=ZONE)]


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    monkeypatch.setattr("pipeline.sources.neighborhood_markets.fetch.time.sleep", lambda _s: None)


class TestComparison:
    def test_ignores_case_and_whitespace(self):
        assert squash("Every  SATURDAY\n9am - 1pm") == squash("every saturday 9am - 1pm")

    def test_survives_a_word_split_across_spans_and_zero_width_padding(self):
        # Beaverton's Wix page, verbatim: "Apr il", with U+200B between clauses.
        rendered = page_text(
            "<p>Every Saturday \u200b February - March</p><p><span>Apr</span><span>il</span> - Nov</p>"
        )
        assert squash("Every Saturday February - March April - Nov") in rendered

    def test_folds_curly_quotes_and_dashes(self):
        assert squash("Camas Farmer\u2019s Market \u2013 Wednesdays") == squash("Camas Farmer's Market - Wednesdays")

    def test_a_changed_hour_still_registers(self):
        assert squash("9am - 1pm") != squash("10am - 1pm")

    def test_scripts_and_styles_are_not_page_text(self):
        assert "hidden" not in page_text("<p>Saturdays</p><script>var hidden = 1</script><style>.hidden{}</style>")


class TestStatements:
    def test_every_statement_holds_on_the_pages_as_published(self):
        pages = pages_as_published()
        assert all(check_statements(m, pages) is None for m in MARKETS)

    def test_a_reworded_sentence_is_reported(self):
        woodlawn = market("woodlawn")
        pages = pages_as_published([woodlawn])
        url = woodlawn.statements[0].url
        pages[url] = pages[url].replace("9am", "10am")
        assert "no longer on" in check_statements(woodlawn, pages)

    def test_an_unreadable_page_is_reported(self):
        woodlawn = market("woodlawn")
        assert check_statements(woodlawn, {}).startswith("page unreadable")

    def test_every_statement_is_needed_not_just_one(self):
        st_johns = market("st-johns")
        url = st_johns.statements[0].url
        assert check_statements(st_johns, {url: squash(st_johns.statements[0].text)}) is not None


class TestTable:
    def test_slugs_are_unique(self):
        slugs = [m.slug for m in MARKETS]
        assert len(slugs) == len(set(slugs))

    def test_every_market_is_on_the_map(self):
        assert {m.slug for m in MARKETS} <= set(COORDINATES)

    def test_every_listed_day_falls_inside_its_season(self):
        for m in MARKETS:
            for listed in m.days:
                assert m.through is not None and listed.day <= m.through, m.slug

    def test_every_market_states_something_to_check(self):
        assert all(m.statements and (m.rules or m.days) for m in MARKETS)


class TestEncoding:
    def test_a_dated_season_stops_on_its_last_date(self):
        assert days("sellwood-moreland", date(2026, 10, 1))[-1] == date(2026, 10, 24)

    def test_a_dated_season_does_not_repeat_into_next_year(self):
        # "May 16th through October 24th 2026" says nothing about 2027.
        assert days("sellwood-moreland", date(2027, 5, 1)) == []

    def test_a_standing_schedule_does_repeat(self):
        # "May through October" with no year is the operator's schedule every year.
        assert days("rocky-butte", date(2027, 5, 1))[0] == date(2027, 5, 1)

    def test_a_skipped_date_is_left_out(self):
        events, counters = normalize(pages_as_published(), now=datetime(2026, 7, 1, 17, 0, tzinfo=UTC))
        assert counters.skipped_dates == 1
        assert not [e for e in events if e.id == "neighborhood_markets:mount-hood@2026-07-10"]
        assert [e for e in events if e.id == "neighborhood_markets:mount-hood@2026-07-17"]

    def test_first_and_third_mondays_only(self):
        assert days("come-thru", date(2026, 9, 1)) == [
            date(2026, 9, 7),
            date(2026, 9, 21),
            date(2026, 10, 5),
            date(2026, 10, 19),
        ]

    def test_listed_winter_days_follow_the_weekly_season(self):
        hillsdale = days("hillsdale", date(2026, 11, 15))
        assert hillsdale[:4] == [date(2026, 11, 15), date(2026, 11, 22), date(2026, 12, 6), date(2026, 12, 20)]
        assert date(2026, 11, 29) not in hillsdale

    def test_a_listed_day_carries_its_own_title_and_hours(self):
        december = occurrences(market("st-johns"), today=date(2026, 12, 1), zone=ZONE)
        holiday = next(o for o in december if o.day == date(2026, 12, 12))
        assert holiday.title == "St. Johns Holiday Market"
        assert holiday.start_at.time() == time(10)

    def test_two_seasons_with_different_hours(self):
        beaverton = market("beaverton")
        spring = occurrences(beaverton, today=date(2026, 3, 1), zone=ZONE)
        assert spring[0].start_at.time() == time(10)
        summer = occurrences(beaverton, today=date(2026, 6, 1), zone=ZONE)
        assert summer[0].start_at.time() == time(8, 30)

    def test_expansion_is_bounded_by_the_window(self):
        peoples = days("peoples", date(2026, 10, 4))
        assert peoples[-1] <= date(2026, 10, 4) + config.EXPANSION_WINDOW


class TestNormalize:
    def test_a_changed_statement_withholds_only_that_market(self):
        pages = pages_as_published()
        url = market("woodlawn").statements[0].url
        pages[url] = pages[url].replace(squash("June 6th-October 24th"), squash("June 5th-October 23rd"))
        events, counters = normalize(pages, now=NOW)
        assert counters.markets_statement_changed == 1
        assert not [e for e in events if e.id.startswith("neighborhood_markets:woodlawn@")]
        assert [e for e in events if e.id.startswith("neighborhood_markets:sellwood-moreland@")]

    def test_an_unreadable_page_withholds_every_market_citing_it(self):
        pages = pages_as_published()
        pages["https://www.adelantefarmersmarket.org/"] = None
        _, counters = normalize(pages, now=NOW)
        assert counters.markets_page_unreadable == 2

    def test_ids_are_slug_plus_date_and_do_not_move(self):
        first, _ = normalize(pages_as_published(), now=NOW)
        later, _ = normalize(pages_as_published(), now=NOW + timedelta(days=3))
        assert "neighborhood_markets:woodstock@2026-10-11" in {e.id for e in first}
        starts = {e.id: e.start_at for e in first}
        shared = [e for e in later if e.id in starts]
        assert len(shared) > 50
        assert all(starts[e.id] == e.start_at for e in shared)

    def test_times_are_portland_local(self):
        events, _ = normalize(pages_as_published(), now=NOW)
        tigard = next(e for e in events if e.id == "neighborhood_markets:tigard@2026-10-11")
        assert tigard.start_at.isoformat() == "2026-10-11T09:00:00-07:00"
        assert tigard.end_at.isoformat() == "2026-10-11T13:30:00-07:00"

    def test_markets_are_free_market_and_food_with_a_venue(self):
        events, _ = normalize(pages_as_published(), now=NOW)
        assert events
        assert all(e.price == Price.free() for e in events)
        assert all(e.categories == (Category.MARKET, Category.FOOD) for e in events)
        assert all(e.venue is not None and e.venue.has_coordinates for e in events)

    def test_the_venue_is_named_for_the_market_so_dedup_can_match_it(self):
        events, _ = normalize(pages_as_published(), now=NOW)
        hillsdale = next(e for e in events if e.id.startswith("neighborhood_markets:hillsdale@"))
        assert hillsdale.venue.name == "Hillsdale Farmers Market"
        assert hillsdale.venue.address.startswith("Rieke Elementary School")
        assert all(e.venue.name == e.organizer for e in events)

    def test_a_finished_season_counts_as_out_of_season(self):
        _, counters = normalize(pages_as_published(), now=NOW)
        # Cully, OHSU, Cornelius and Camas all ended in August or September 2026.
        assert counters.markets_out_of_season == 4

    def test_output_validates(self):
        events, _ = normalize(pages_as_published(), now=NOW)
        validate_per_source(build_per_source_feed("neighborhood_markets", events, generated_at=NOW))


class TestFetch:
    @responses.activate
    def test_each_page_is_read_once_however_many_markets_cite_it(self):
        both = (market("forest-grove"), market("cornelius"))
        responses.add(responses.GET, "https://www.adelantefarmersmarket.org/", body="<p>markets</p>")
        pages, stats = fetch_pages(both, session=requests.Session())
        assert stats == {"pages": 1, "pages_read": 1}
        assert len(responses.calls) == 1
        assert pages["https://www.adelantefarmersmarket.org/"] == "markets"

    @responses.activate
    def test_a_failed_page_is_none_rather_than_fatal(self):
        pair = (market("woodlawn"), market("tigard"))
        responses.add(responses.GET, market("woodlawn").listing_url, body="<p>ok</p>")
        for _ in range(config.MAX_RETRIES):
            responses.add(responses.GET, market("tigard").listing_url, status=503)
        pages, _ = fetch_pages(pair, session=requests.Session())
        assert pages[market("tigard").listing_url] is None
        assert pages[market("woodlawn").listing_url] == "ok"

    @responses.activate
    def test_no_readable_page_at_all_fails_the_run(self):
        for _ in range(config.MAX_RETRIES):
            responses.add(responses.GET, market("tigard").listing_url, status=403)
        with pytest.raises(NeighborhoodFetchError):
            fetch_pages((market("tigard"),), session=requests.Session())
