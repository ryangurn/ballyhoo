"""Tests for the Oregon City Farmers Market source.

The fixture is trimmed from a real API response. The record that matters is the
timestamp pair: this site's timezone is set to a fixed `UTC-8`, so its UTC fields are an
hour late through the summer and the local fields are the ones that match the posted
9am-1pm hours.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.tribe_events import parse_events
from pipeline.common.validate import validate_per_source
from pipeline.sources.oregon_city_farmers_market.normalize import normalize

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)

VENUE = {
    "id": 6769,
    "venue": "Oregon City Farmers Market",
    "address": "Clackamas Community College, Green Lot #1, near corner of Beavercreek Road and Clairmont Drive",
    "city": "Oregon City",
    "geo_lat": 45.3328976,
    "geo_lng": -122.5987329,
}


def record(slug, title, local_start, local_end, utc_start, utc_end, **overrides):
    base = {
        "slug": slug,
        "title": title,
        "start_date": local_start,
        "end_date": local_end,
        "utc_start_date": utc_start,
        "utc_end_date": utc_end,
        "timezone": "UTC-8",
        "all_day": False,
        "url": f"https://orcityfarmersmarket.com/event/{slug}/",
        "excerpt": "Contact (503) 734-0192 Email us! Mailing Address: PO Box 2931",
        "cost": "",
        "categories": [{"name": "Market"}],
        "venue": VENUE,
        "image": {"url": "https://orcityfarmersmarket.com/wp-content/uploads/2020/04/New-logo.jpg"},
    }
    return {**base, **overrides}


PAYLOAD = {
    "events": [
        record(
            "oregon-city-summer-farmers-market-8-2026-10-10",
            "Oregon City Summer Farmers Market",
            "2026-10-10 09:00:00",
            "2026-10-10 13:00:00",
            "2026-10-10 17:00:00",
            "2026-10-10 21:00:00",
        ),
        record(
            "oregon-city-winter-farmers-market-3-2027-01-09",
            "Oregon City Winter Farmers Market",
            "2027-01-09 10:00:00",
            "2027-01-09 14:00:00",
            "2027-01-09 18:00:00",
            "2027-01-09 22:00:00",
        ),
        record(
            "cooking-class",
            "Cooking Class",
            "2026-10-15 18:00:00",
            "2026-10-15 20:00:00",
            "2026-10-16 02:00:00",
            "2026-10-16 04:00:00",
            categories=[{"name": "Workshop"}],
        ),
    ]
}


def normalized():
    return normalize(parse_events(PAYLOAD), now=NOW)


def by_title(title):
    events, _ = normalized()
    return next(e for e in events if e.title == title)


class TestTimes:
    def test_a_summer_market_opens_at_nine_not_ten(self):
        day = by_title("Oregon City Summer Farmers Market")
        assert day.start_at.isoformat() == "2026-10-10T09:00:00-07:00"
        assert day.end_at.isoformat() == "2026-10-10T13:00:00-07:00"

    def test_a_winter_market_is_on_standard_time(self):
        day = by_title("Oregon City Winter Farmers Market")
        assert day.start_at.isoformat() == "2027-01-09T10:00:00-08:00"


class TestNormalize:
    def test_id_is_slug_plus_local_date(self):
        assert by_title("Oregon City Summer Farmers Market").id == (
            "oregon_city_farmers_market:oregon-city-summer-farmers-market-8-2026-10-10@2026-10-10"
        )

    def test_market_days_are_free_market_and_food(self):
        day = by_title("Oregon City Summer Farmers Market")
        assert day.categories == (Category.MARKET, Category.FOOD)
        assert day.price == Price.free()

    def test_anything_else_claims_no_price(self):
        other = by_title("Cooking Class")
        assert other.categories == (Category.COMMUNITY, Category.MARKET)
        assert other.price == Price.unknown()

    def test_the_footer_excerpt_is_not_used_as_a_summary(self):
        assert by_title("Oregon City Summer Farmers Market").summary is None

    def test_the_upstream_venue_is_already_geocoded(self):
        venue = by_title("Oregon City Summer Farmers Market").venue
        assert venue.name == "Oregon City Farmers Market"
        assert venue.latitude == pytest.approx(45.333, abs=0.01)

    def test_output_validates(self):
        events, _ = normalized()
        validate_per_source(build_per_source_feed("oregon_city_farmers_market", events, generated_at=NOW))
