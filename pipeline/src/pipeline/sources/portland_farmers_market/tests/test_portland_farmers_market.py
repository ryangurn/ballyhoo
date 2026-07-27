"""Tests for the Portland Farmers Market source.

The fixture is trimmed from a real API response and keeps the shapes that actually
bite: `venue` arriving as an empty *list* rather than null, two occurrences of one
series sharing a slug while carrying different provisional numeric ids, a venue
upstream never geocoded, and offset-free UTC timestamps.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.validate import validate_per_source
from pipeline.sources.portland_farmers_market.fetch import parse_events
from pipeline.sources.portland_farmers_market.normalize import (
    is_the_market_itself,
    normalize,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)

PAYLOAD = {
    "events": [
        {
            # First occurrence of the King series.
            "id": 10003167,
            "slug": "king-farmers-market-3",
            "title": "King Farmers Market",
            "all_day": False,
            "start_date": "2026-08-02 10:00:00",
            "utc_start_date": "2026-08-02 17:00:00",
            "utc_end_date": "2026-08-02 21:00:00",
            "url": "https://www.portlandfarmersmarket.org/event/king-farmers-market-3/2026-08-02/",
            "excerpt": "<p>King Farmers Market features about 30 farmers and food producers.</p>",
            "cost": "",
            "website": "https://www.portlandfarmersmarket.org/our-markets/king/",
            "image": {"url": "https://www.portlandfarmersmarket.org/wp-content/uploads/2023/08/King.jpg"},
            "categories": [{"name": "King Farmers Market"}],
            "organizer": [],
            "venue": {
                "venue": "King Farmers Market",
                "address": "NE Wygant St &, NE 7th Ave, Portland, OR 97211",
                "city": "Portland",
                "geo_lat": 45.5582344,
                "geo_lng": -122.6590884,
            },
        },
        {
            # Same series a week later. Note the numeric id simply increments: these
            # are provisional ids, which is exactly why we do not key on them.
            "id": 10003168,
            "slug": "king-farmers-market-3",
            "title": "King Farmers Market",
            "all_day": False,
            "start_date": "2026-08-09 10:00:00",
            "utc_start_date": "2026-08-09 17:00:00",
            "utc_end_date": "2026-08-09 21:00:00",
            "url": "https://www.portlandfarmersmarket.org/event/king-farmers-market-3/2026-08-09/",
            "excerpt": "",
            "categories": [{"name": "King Farmers Market"}],
            "organizer": [],
            "venue": {
                "venue": "King Farmers Market",
                "address": "NE Wygant St &, NE 7th Ave, Portland, OR 97211",
                "city": "Portland",
                "geo_lat": 45.5582344,
                "geo_lng": -122.6590884,
            },
        },
        {
            # Shemanski is the one venue upstream never geocoded.
            "id": 10003227,
            "slug": "shemanski-park-farmers-market-2026",
            "title": "Shemanski Park Farmers Market",
            "all_day": False,
            "start_date": "2026-08-05 10:00:00",
            "utc_start_date": "2026-08-05 17:00:00",
            "utc_end_date": "2026-08-05 21:00:00",
            "url": "https://www.portlandfarmersmarket.org/event/shemanski-park-farmers-market-2026/2026-08-05/",
            "categories": [{"name": "Shemanski Park Farmers Market"}],
            "venue": {
                "venue": "Shemanski Park Farmers Market",
                "address": "SW Park & Main",
                "city": "Portland",
                "geo_lat": None,
                "geo_lng": None,
            },
        },
        {
            # A musician booked into a market. `venue` comes back as an empty list,
            # not null, and the taxonomy still names the market.
            "id": 31475,
            "slug": "josh-faber-hammond",
            "title": "Josh Faber-Hammond",
            "all_day": False,
            "start_date": "2026-07-29 17:00:00",
            "utc_start_date": "2026-07-30 00:00:00",
            "utc_end_date": "2026-07-30 02:00:00",
            "url": "https://www.portlandfarmersmarket.org/event/josh-faber-hammond/",
            "categories": [{"name": "Kenton Farmers Market"}],
            "organizer": [],
            "venue": [],
            "website": "",
        },
        {
            # Long past; the plugin keeps some history in the collection.
            "id": 31000,
            "slug": "old-market-day",
            "title": "King Farmers Market",
            "all_day": False,
            "start_date": "2025-05-04 10:00:00",
            "utc_start_date": "2025-05-04 17:00:00",
            "url": "https://www.portlandfarmersmarket.org/event/old-market-day/2025-05-04/",
            "categories": [{"name": "King Farmers Market"}],
            "venue": [],
        },
        # Missing a title entirely: unusable, must not become an event.
        {"id": 999, "slug": "broken", "utc_start_date": "2026-08-02 17:00:00", "url": "https://example.com/x"},
    ]
}


def parsed():
    return parse_events(PAYLOAD)


def normalized():
    return normalize(parsed(), now=NOW)


class TestParsing:
    def test_skips_records_missing_required_fields(self):
        assert len(parsed()) == 5

    def test_an_empty_list_venue_is_read_as_no_venue(self):
        # The API sends [] rather than null for an unset object field.
        performer = next(e for e in parsed() if e.slug == "josh-faber-hammond")
        assert performer.venue is None

    def test_venue_is_read_when_present(self):
        king = parsed()[0]
        assert king.venue is not None
        assert king.venue.name == "King Farmers Market"
        assert king.venue.latitude == pytest.approx(45.5582344)

    def test_null_coordinates_survive_parsing_as_none(self):
        shemanski = next(e for e in parsed() if "shemanski" in e.slug)
        assert shemanski.venue is not None
        assert shemanski.venue.latitude is None

    def test_reads_the_utc_timestamp_not_the_local_one(self):
        assert parsed()[0].utc_start_raw == "2026-08-02 17:00:00"


class TestIdentity:
    def test_id_is_slug_plus_date_not_the_numeric_id(self):
        events, _ = normalized()
        king = [e for e in events if e.title == "King Farmers Market"]
        assert {e.id for e in king} == {
            "portland_farmers_market:king-farmers-market-3@2026-08-02",
            "portland_farmers_market:king-farmers-market-3@2026-08-09",
        }
        # The provisional numeric ids must not appear anywhere in an id.
        assert not any("10003167" in e.id for e in events)

    def test_occurrences_of_one_series_stay_distinct(self):
        events, _ = normalized()
        assert len({e.id for e in events}) == len(events)

    def test_ids_are_stable_when_the_run_time_moves(self):
        # Bookmarks break if an id depends on anything but upstream identity.
        first, _ = normalize(parsed(), now=NOW)
        later, _ = normalize(parsed(), now=NOW + timedelta(days=3))
        assert [e.id for e in first] == [e.id for e in later]


class TestNormalize:
    def test_offsetless_timestamps_are_utc_not_local(self):
        events, _ = normalized()
        king = next(e for e in events if e.id.endswith("@2026-08-02"))
        assert king.start_at.isoformat() == "2026-08-02T10:00:00-07:00"
        assert king.end_at.isoformat() == "2026-08-02T14:00:00-07:00"

    def test_stale_occurrences_are_dropped(self):
        events, counters = normalized()
        assert counters.stale == 1
        assert all(e.start_at >= NOW - timedelta(days=8) for e in events)

    def test_ungeocoded_venue_falls_back_to_the_baked_table(self):
        events, _ = normalized()
        shemanski = next(e for e in events if e.venue and e.venue.name == "Shemanski Park Farmers Market")
        assert shemanski.venue.latitude == pytest.approx(45.517, abs=0.01)
        assert shemanski.venue.longitude == pytest.approx(-122.682, abs=0.01)

    def test_html_is_stripped_from_the_summary(self):
        events, _ = normalized()
        king = next(e for e in events if e.id.endswith("@2026-08-02"))
        assert king.summary == "King Farmers Market features about 30 farmers and food producers."

    def test_an_empty_excerpt_becomes_no_summary(self):
        events, _ = normalized()
        assert next(e for e in events if e.id.endswith("@2026-08-09")).summary is None

    def test_events_are_sorted(self):
        events, _ = normalized()
        assert [e.start_at for e in events] == sorted(e.start_at for e in events)

    def test_output_validates(self):
        events, _ = normalized()
        validate_per_source(build_per_source_feed("portland_farmers_market", events, generated_at=NOW))


class TestPrice:
    def test_markets_are_free_to_enter(self):
        # The deliberate exception to Price.unknown(): a farmers market has no gate
        # and no ticket, so free-to-attend is a fact rather than an inference.
        events, _ = normalized()
        assert all(e.price == Price.free() for e in events)
        assert all(e.price.is_free for e in events)


class TestClassification:
    def test_a_market_day_is_recognised_by_its_venue_name(self):
        assert is_the_market_itself(parsed()[0]) is True

    def test_a_performer_is_not_the_market(self):
        performer = next(e for e in parsed() if e.slug == "josh-faber-hammond")
        assert is_the_market_itself(performer) is False

    def test_markets_are_categorised_as_market_and_food(self):
        events, _ = normalized()
        king = next(e for e in events if e.id.endswith("@2026-08-02"))
        assert king.categories == (Category.MARKET, Category.FOOD)

    def test_performers_are_music_but_still_market(self):
        events, _ = normalized()
        performer = next(e for e in events if e.title == "Josh Faber-Hammond")
        assert performer.categories == (Category.MUSIC, Category.MARKET)
