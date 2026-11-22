"""Tests for the DoPDX source.

The fixture mirrors the merged record fetch.py produces: listing fields overlaid
with the detail page's fields. The important cases are the timestamp field
choice — only `tz_adjusted_*` carries a correct offset — and the venue merge,
which is the only place city and coordinates still exist.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.validate import validate_per_source
from pipeline.sources.dopdx import fetch
from pipeline.sources.dopdx.normalize import infer_categories, normalize

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

IMAGE = "https://assets0.dostuffmedia.com/uploads/aws_asset/aws_asset/1/abc.jpg"


def raw_event(**overrides):
    base = {
        "id": 16978458,
        "permalink": "/events/2026/7/26/young-the-giant-tickets",
        "title": "Young the Giant",
        "description": "Young the Giant<br><br>An ode to radical empathy.",
        "category": "Music",
        # Deliberately wrong offset: the real payload carries -05:00 here on events
        # that actually run at -07:00, so this field must never be used.
        "begin_time": "2026-07-26T16:30:00-05:00",
        "tz_adjusted_begin_time": "2026-07-26T16:30:00-07:00",
        "tz_adjusted_end_time": "2026-07-27T02:00:00-07:00",
        "is_past": False,
        "free_event": False,
        "ticket_info": "$73 to $669, All Ages",
        "presented_by": "Elsinore presents",
        "image_url": IMAGE,
        "venue": {
            "title": "McMenamins Edgefield",
            "address": "2126 S.W. Halsey St.",
            "city": "Troutdale",
            "latitude": 45.537115,
            "longitude": -122.4065816,
        },
    }
    base.update(overrides)
    return base


def one(**overrides):
    events, counters = normalize([raw_event(**overrides)], now=NOW)
    return (events[0] if events else None), counters


class TestNormalize:
    def test_happy_path(self):
        event, _ = one()
        assert event.id == "dopdx:16978458"
        assert event.title == "Young the Giant"
        assert event.organizer == "Elsinore presents"
        assert event.listing_url == "https://dopdx.com/events/2026/7/26/young-the-giant-tickets"

    def test_uses_the_tz_adjusted_timestamp_not_begin_time(self):
        # begin_time claims -05:00 for an event that runs at -07:00.
        event, _ = one()
        assert event.start_at.isoformat() == "2026-07-26T16:30:00-07:00"
        assert event.end_at.isoformat() == "2026-07-27T02:00:00-07:00"

    def test_past_events_are_dropped(self):
        event, counters = one(is_past=True)
        assert event is None
        assert counters.past == 1

    def test_venue_coordinates_are_carried_through(self):
        event, _ = one()
        assert event.venue.name == "McMenamins Edgefield"
        assert event.venue.latitude == pytest.approx(45.537115)
        assert event.venue.city == "Troutdale"

    def test_html_is_stripped_from_the_summary(self):
        event, _ = one()
        assert "<br>" not in event.summary
        assert "radical empathy" in event.summary

    def test_missing_venue_is_tolerated(self):
        event, _ = one(venue={})
        assert event.venue is None


class TestPricing:
    def test_free_event_flag_is_honoured(self):
        # No other source states this explicitly.
        event, _ = one(free_event=True)
        assert event.price == Price.free()

    def test_a_price_range_is_parsed_from_ticket_info(self):
        event, _ = one()
        assert (event.price.min, event.price.max) == (73.0, 669.0)

    def test_a_single_price_sets_both_bounds(self):
        event, _ = one(ticket_info="$45.96")
        assert (event.price.min, event.price.max) == (45.96, 45.96)

    def test_paid_with_no_figure_is_unknown_not_free(self):
        event, _ = one(ticket_info="")
        assert event.price == Price.unknown()
        assert event.price.is_free is False


class TestImages:
    def test_the_pre_rendered_asset_url_is_used(self):
        # doxyz serves already-rendered image assets; no resize transform applies.
        event, _ = one()
        assert event.image_url == IMAGE

    def test_no_image_is_not_an_error(self):
        event, _ = one(image_url=None)
        assert event.image_url is None


class TestMetroFilter:
    """DoPDX covers the wider Pacific Northwest; a Portland feed must not carry a
    Seattle show. Coordinates decide it when present, city name otherwise."""

    def test_a_portland_venue_is_kept(self):
        event, counters = one()
        assert event is not None
        assert counters.outside_metro == 0

    @pytest.mark.parametrize(
        "city,lat,lon",
        [
            ("Seattle", 47.6062, -122.3321),
            ("Bend", 44.0582, -121.3153),
            ("George", 47.0937, -119.8560),   # the Gorge amphitheatre
        ],
    )
    def test_distant_venues_are_dropped_on_coordinates(self, city, lat, lon):
        event, counters = one(venue={"title": "Somewhere Else", "city": city, "latitude": lat, "longitude": lon})
        assert event is None
        assert counters.outside_metro == 1

    @pytest.mark.parametrize("city", ["Troutdale", "Hillsboro", "Oregon City", "Forest Grove"])
    def test_metro_edges_are_kept(self, city):
        # 40 miles is chosen to hold the metro's edges while excluding other cities.
        coords = {"Troutdale": (45.5395, -122.3873), "Hillsboro": (45.5229, -122.9898),
                  "Oregon City": (45.3573, -122.6068), "Forest Grove": (45.5198, -123.1106)}
        lat, lon = coords[city]
        event, _ = one(venue={"title": f"{city} Venue", "city": city, "latitude": lat, "longitude": lon})
        assert event is not None

    def test_a_known_distant_city_is_dropped_without_coordinates(self):
        event, counters = one(venue={"title": "No Coords Hall", "city": "Seattle"})
        assert event is None
        assert counters.outside_metro == 1

    def test_an_unrecognised_city_is_kept_without_coordinates(self):
        # An unknown string is likelier a neighbourhood or typo than a distant metro,
        # so the coordinate-less fallback errs toward keeping the event.
        event, _ = one(venue={"title": "Somewhere", "city": "Sellwood-Moreland"})
        assert event is not None

    def test_an_event_with_no_venue_at_all_is_kept(self):
        event, _ = one(venue={})
        assert event is not None


class TestCategories:
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Music", Category.MUSIC),
            ("Comedy", Category.ARTS),
            ("Theatre & Performing Arts", Category.ARTS),
            ("Movies", Category.FILM),
            ("Beer", Category.FOOD),
            ("Sports & Rec", Category.SPORTS),
            ("Children & Family", Category.FAMILY),
            ("Culture", Category.COMMUNITY),
        ],
    )
    def test_dopdx_vocabulary_maps(self, label, expected):
        assert infer_categories(label) == (expected,)

    def test_an_unknown_category_falls_back(self):
        assert infer_categories("Sound Bath") == (Category.COMMUNITY,)
        assert infer_categories(None) == (Category.COMMUNITY,)


class TestDevalue:
    """The devalue wire format: every dict/list value is an index into the flat
    array. These tests pin the decoder so a payload change fails loudly."""

    def payload(self, data: list) -> dict:
        return {"type": "data", "nodes": [
            {"type": "data", "data": [{"layout": 1}, {"name": 2}, "dopdx.com"], "uses": {}},
            {"type": "data", "data": data, "uses": {"url": 1}},
        ]}

    def test_unflatten_reconstructs_nested_objects(self):
        flat = [{"browse": 1}, {"data": 2, "_meta": 5}, [3], {"date": 4, "events": 6},
                "2026-11-22", {"total_pages": 7}, [8, 11],
                3, {"id": 9, "title": 10}, 42, "Gig",
                {"id": 9, "title": 12}, "Other"]
        node = fetch._node_data(self.payload(flat), "browse")
        assert node["browse"]["_meta"]["total_pages"] == 3
        assert node["browse"]["data"][0]["events"] == [
            {"id": 42, "title": "Gig"}, {"id": 42, "title": "Other"},
        ]

    def test_negative_indices_decode_as_none(self):
        # devalue sentinels (e.g. `void 0`) arrive as negative indices.
        flat = [{"browse": 1}, {"total_dates": -1, "note": 2}, "x"]
        node = fetch._node_data(self.payload(flat), "browse")
        assert node["browse"]["total_dates"] is None
        assert node["browse"]["note"] == "x"

    def test_a_node_without_the_key_is_skipped(self):
        flat = [{"event": 1}, {"title": 2}, "Gig"]
        assert fetch._node_data(self.payload(flat), "browse") is None
        assert fetch._node_data(self.payload(flat), "event")["event"]["title"] == "Gig"


class TestVenueMerge:
    def test_detail_geo_wins_over_listing(self):
        detail = {
            "venue": {"title": "Aladdin Theater", "address": "3017 SE Milwaukie Ave."},
            "seo_source": {"venue": {"name": "Aladdin Theater", "city": "Portland",
                                     "latitude": 45.5, "longitude": -122.65}},
        }
        merged = fetch._merge_venue(detail, {"title": "Aladdin Theater", "area_name": "Inner Southeast"})
        assert merged == {"title": "Aladdin Theater", "address": "3017 SE Milwaukie Ave.",
                          "city": "Portland", "latitude": 45.5, "longitude": -122.65}

    def test_detail_address_beats_seo(self):
        detail = {
            "venue": {"title": "V", "address": "detail addr"},
            "seo_source": {"venue": {"address": "seo addr"}},
        }
        assert fetch._merge_venue(detail, None)["address"] == "detail addr"

    def test_no_seo_venue_leaves_geo_empty(self):
        merged = fetch._merge_venue({"venue": {"title": "Mystery Hall"}}, None)
        assert merged["title"] == "Mystery Hall"
        assert merged["latitude"] is None


def test_output_validates():
    events, _ = normalize([raw_event()], now=NOW)
    validate_per_source(build_per_source_feed("dopdx", events, generated_at=NOW))
