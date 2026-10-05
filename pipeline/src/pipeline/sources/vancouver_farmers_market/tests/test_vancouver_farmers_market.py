"""Tests for the Vancouver Farmers Market source.

The fixture is trimmed from a real API response. It keeps the things this site does
differently: the whole address stuffed into the venue *name*, no coordinates anywhere,
musicians whose description is the performer booking form, a listing with no venue,
and an event at a venue off the market grounds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.tribe_events import parse_events
from pipeline.common.validate import validate_per_source
from pipeline.sources.vancouver_farmers_market.normalize import normalize

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)

DOWNTOWN_VENUE = {
    "id": 16705,
    "venue": "Vancouver Farmers Market, 605 Esther St, Vancouver, WA 98660, USA",
    "address": None,
    "city": None,
    "geo_lat": None,
    "geo_lng": None,
}
MUSIC_VENUE = {"id": 16710, "venue": "605 Esther St, Vancouver, WA 98660", "geo_lat": None, "geo_lng": None}


def record(slug, title, start_utc, end_utc, **overrides):
    base = {
        "slug": slug,
        "title": title,
        "start_date": "",
        "utc_start_date": start_utc,
        "utc_end_date": end_utc,
        "timezone": "America/Los_Angeles",
        "all_day": False,
        "url": f"https://vancouverfarmersmarket.org/event/{slug}/",
        "description": "",
        "excerpt": "",
        "cost": "",
        "categories": [],
        "venue": DOWNTOWN_VENUE,
        "image": False,
    }
    return {**base, **overrides}


PAYLOAD = {
    "events": [
        record(
            "downtown-vancouver-farmers-market-72",
            "Downtown Vancouver Farmers Market",
            "2026-10-04 17:00:00",
            "2026-10-04 22:00:00",
            description="<p>605 Esther Street</p>",
        ),
        record(
            "the-steve-and-margot-show-at-the-vancouver-farmers-market-2",
            "The Steve and Margot Show at the Vancouver Farmers Market",
            "2026-10-04 18:00:00",
            "2026-10-04 20:00:00",
            categories=[{"name": "Market Music"}],
            venue=MUSIC_VENUE,
            description="<p>Thank you for your interest in performing at the Vancouver Farmers Market (VFM)!</p>",
        ),
        record(
            "vancouver-ballet-folklorico-market-performance",
            "Vancouver Ballet Folkl&oacute;rico Market Performance",
            "2026-10-11 19:30:00",
            "2026-10-11 20:30:00",
            venue=[],
        ),
        record(
            "kids-bucks-7",
            "Kids Bucks!",
            "2026-10-31 16:00:00",
            "2026-10-31 22:00:00",
            description="<p>Kids get a $2 coupon to spend on anything at the market!</p>",
        ),
        record(
            "vancouver-holiday-market-4",
            "Vancouver Holiday Market",
            "2026-11-27 23:00:00",
            "2026-11-28 04:00:00",
            venue={"id": 18709, "venue": "Hilton Vancouver Washington, 301 W 6th St, Vancouver, WA 98660, USA"},
        ),
        record(
            "east-vancouver-farmers-market-10",
            "East Vancouver Farmers Market",
            "2027-06-03 17:00:00",
            "2027-06-03 21:00:00",
            venue={"id": 1, "venue": "East Vancouver Farmers Market (June &#8211; September)", "city": "Vancouver"},
        ),
        record(
            "pop-up-somewhere-new",
            "Pop-up Market",
            "2026-10-17 17:00:00",
            "2026-10-17 21:00:00",
            venue={"id": 2, "venue": "Somewhere New, Vancouver, WA"},
        ),
        record("ticketed-dinner", "Harvest Dinner", "2026-10-18 01:00:00", "2026-10-18 04:00:00", cost="$85"),
        record("long-gone", "Downtown Vancouver Farmers Market", "2026-08-01 16:00:00", "2026-08-01 22:00:00"),
    ]
}


def normalized(now=NOW):
    return normalize(parse_events(PAYLOAD), now=now)


def by_slug(slug):
    events, _ = normalized()
    return next(e for e in events if f":{slug}@" in e.id)


class TestIdentity:
    def test_id_is_slug_plus_local_date(self):
        assert by_slug("downtown-vancouver-farmers-market-72").id == (
            "vancouver_farmers_market:downtown-vancouver-farmers-market-72@2026-10-04"
        )

    def test_ids_do_not_move_with_the_run_time(self):
        first, _ = normalized()
        later, _ = normalized(now=NOW + timedelta(days=1))
        assert {e.id for e in later} <= {e.id for e in first}


class TestClassification:
    def test_market_days_are_market_and_food(self):
        assert by_slug("downtown-vancouver-farmers-market-72").categories == (Category.MARKET, Category.FOOD)
        assert by_slug("east-vancouver-farmers-market-10").categories == (Category.MARKET, Category.FOOD)

    def test_booked_musicians_are_music_at_the_market(self):
        music = by_slug("the-steve-and-margot-show-at-the-vancouver-farmers-market-2")
        assert music.categories == (Category.MUSIC, Category.MARKET)

    def test_everything_else_is_a_community_listing(self):
        assert by_slug("kids-bucks-7").categories == (Category.COMMUNITY, Category.MARKET)
        assert by_slug("vancouver-holiday-market-4").categories == (Category.COMMUNITY, Category.MARKET)


class TestVenues:
    def test_an_address_stuffed_into_the_name_is_mapped_to_a_clean_venue(self):
        venue = by_slug("downtown-vancouver-farmers-market-72").venue
        assert venue.name == "Vancouver Farmers Market"
        assert venue.address == "605 Esther St, Vancouver, WA 98660"
        assert venue.latitude == pytest.approx(45.626, abs=0.01)

    def test_the_musicians_bare_address_maps_to_the_same_market(self):
        music = by_slug("the-steve-and-margot-show-at-the-vancouver-farmers-market-2")
        assert music.venue.name == "Vancouver Farmers Market"

    def test_an_escaped_venue_name_still_matches_the_table(self):
        assert by_slug("east-vancouver-farmers-market-10").venue.name == "East Vancouver Farmers Market"
        assert by_slug("east-vancouver-farmers-market-10").venue.has_coordinates

    def test_an_unknown_venue_publishes_without_a_pin(self):
        events, counters = normalized()
        popup = next(e for e in events if e.title == "Pop-up Market")
        assert popup.venue.name == "Somewhere New, Vancouver, WA"
        assert not popup.venue.has_coordinates
        assert counters.no_venue_coordinates == 1

    def test_no_venue_stays_no_venue(self):
        assert by_slug("vancouver-ballet-folklorico-market-performance").venue is None


class TestPrice:
    def test_market_days_music_and_listings_on_the_grounds_are_free(self):
        for slug in (
            "downtown-vancouver-farmers-market-72",
            "the-steve-and-margot-show-at-the-vancouver-farmers-market-2",
            "kids-bucks-7",
        ):
            assert by_slug(slug).price == Price.free(), slug

    def test_off_the_grounds_or_unplaced_is_unknown(self):
        assert by_slug("vancouver-holiday-market-4").price == Price.unknown()
        assert by_slug("vancouver-ballet-folklorico-market-performance").price == Price.unknown()

    def test_a_stated_cost_is_never_marked_free(self):
        assert by_slug("ticketed-dinner").price == Price.unknown()


class TestNormalize:
    def test_times_are_portland_local(self):
        day = by_slug("downtown-vancouver-farmers-market-72")
        assert day.start_at.isoformat() == "2026-10-04T10:00:00-07:00"
        assert day.end_at.isoformat() == "2026-10-04T15:00:00-07:00"

    def test_titles_are_unescaped(self):
        assert by_slug("vancouver-ballet-folklorico-market-performance").title == (
            "Vancouver Ballet Folkl\u00f3rico Market Performance"
        )

    def test_only_community_listings_carry_the_description(self):
        assert by_slug("downtown-vancouver-farmers-market-72").summary is None
        assert by_slug("the-steve-and-margot-show-at-the-vancouver-farmers-market-2").summary is None
        assert by_slug("kids-bucks-7").summary == "Kids get a $2 coupon to spend on anything at the market!"

    def test_stale_occurrences_are_dropped(self):
        _, counters = normalized()
        assert counters.stale == 1

    def test_output_validates(self):
        events, _ = normalized()
        validate_per_source(build_per_source_feed("vancouver_farmers_market", events, generated_at=NOW))
