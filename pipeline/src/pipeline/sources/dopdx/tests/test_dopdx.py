"""Tests for the DoPDX source.

Fixtures mirror the live SvelteKit payloads: a day-listing entry, plus the trimmed
event-page `detail` that fetch.py attaches. The important cases are the timestamp
field choice — only `tz_adjusted_*` carries a correct offset — the metro filter, and
the fallback when an event's page has not been fetched yet.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import responses

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.validate import validate_per_source
from pipeline.sources.dopdx import config
from pipeline.sources.dopdx import fetch as dopdx_fetch
from pipeline.sources.dopdx.normalize import infer_categories, normalize
from pipeline.sources.dopdx.sveltekit import SvelteKitPayloadError, decode_node, find_key

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
IMAGE = "https://assets0.dostuffmedia.com/uploads/aws_asset/aws_asset/33572170/cover.jpg"


def detail(**overrides):
    base = {
        "description": "Young the Giant<br><br>An ode to radical empathy &amp; more.",
        "ticket_info": "$73 to $669, All Ages",
        "free_event": False,
        "is_past": False,
        "presented_by": "Elsinore presents",
        "venue": {
            "name": "McMenamins Edgefield",
            "latitude": 45.537115,
            "longitude": -122.4065816,
            "address": "2126 S.W. Halsey St.",
            "city": "Troutdale",
        },
    }
    base.update(overrides)
    return base


def raw_event(detail_overrides=None, **overrides):
    base = {
        "id": 16978458,
        "permalink": "/events/2026/7/26/young-the-giant-tickets",
        "title": "Young the Giant",
        "category": "Music",
        # A UTC wall time with no offset, so this field must never be used.
        "begin_time": "2026-07-26T23:30:00",
        "tz_adjusted_begin_time": "2026-07-26T16:30:00-07:00",
        "tz_adjusted_end_time": "2026-07-27T02:00:00-07:00",
        "presented_by": None,
        "image_url": IMAGE,
        "venue": {"id": 23673, "title": "McMenamins Edgefield", "area_name": "Suburbs - East", "location": None},
        "detail": detail(**(detail_overrides or {})),
    }
    base.update(overrides)
    return base


def one(detail_overrides=None, **overrides):
    events, counters = normalize([raw_event(detail_overrides, **overrides)], now=NOW)
    return (events[0] if events else None), counters


class TestNormalize:
    def test_happy_path(self):
        event, _ = one()
        assert event.id == "dopdx:16978458"
        assert event.title == "Young the Giant"
        assert event.organizer == "Elsinore presents"
        assert event.listing_url == "https://dopdx.com/events/2026/7/26/young-the-giant-tickets"

    def test_uses_the_tz_adjusted_timestamp_not_begin_time(self):
        event, _ = one()
        assert event.start_at.isoformat() == "2026-07-26T16:30:00-07:00"
        assert event.end_at.isoformat() == "2026-07-27T02:00:00-07:00"

    def test_past_events_are_dropped(self):
        event, counters = one({"is_past": True})
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
        assert event.summary == "Young the Giant An ode to radical empathy & more."

    def test_missing_venue_is_tolerated(self):
        event, _ = one({"venue": {}}, venue={})
        assert event.venue is None

    def test_an_event_without_page_details_ships_from_the_listing(self):
        # A cold cache leaves some events without their page; they must still ship.
        event, _ = one(detail=None)
        assert event.venue.name == "McMenamins Edgefield"
        assert event.venue.latitude is None
        assert event.summary is None
        assert event.price == Price.unknown()
        assert event.start_at.isoformat() == "2026-07-26T16:30:00-07:00"


class TestPricing:
    def test_is_free_flag_is_honoured(self):
        # No other source states this explicitly.
        event, _ = one({"free_event": True})
        assert event.price == Price.free()

    def test_a_price_range_is_parsed_from_ticket_info(self):
        event, _ = one()
        assert (event.price.min, event.price.max) == (73.0, 669.0)

    def test_a_single_price_sets_both_bounds(self):
        event, _ = one({"ticket_info": "$45.96"})
        assert (event.price.min, event.price.max) == (45.96, 45.96)

    def test_a_hyphenated_range_is_parsed(self):
        event, _ = one({"ticket_info": "$40.29-$45.93"})
        assert (event.price.min, event.price.max) == (40.29, 45.93)

    def test_paid_with_no_figure_is_unknown_not_free(self):
        event, _ = one({"ticket_info": None})
        assert event.price == Price.unknown()
        assert event.price.is_free is False


class TestImages:
    def test_uses_the_listing_cover(self):
        # The listing image is the 1200x450 cover crop, already card-sized.
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
        event, counters = one({"venue": {"name": "Somewhere Else", "city": city, "latitude": lat, "longitude": lon}})
        assert event is None
        assert counters.outside_metro == 1

    @pytest.mark.parametrize("city", ["Troutdale", "Hillsboro", "Oregon City", "Forest Grove"])
    def test_metro_edges_are_kept(self, city):
        # 40 miles is chosen to hold the metro's edges while excluding other cities.
        coords = {"Troutdale": (45.5395, -122.3873), "Hillsboro": (45.5229, -122.9898),
                  "Oregon City": (45.3573, -122.6068), "Forest Grove": (45.5198, -123.1106)}
        lat, lon = coords[city]
        event, _ = one({"venue": {"name": f"{city} Venue", "city": city, "latitude": lat, "longitude": lon}})
        assert event is not None

    def test_a_known_distant_city_is_dropped_without_coordinates(self):
        event, counters = one({"venue": {"name": "No Coords Hall", "city": "Seattle"}})
        assert event is None
        assert counters.outside_metro == 1

    def test_an_unrecognised_city_is_kept_without_coordinates(self):
        # An unknown string is likelier a neighbourhood or typo than a distant metro,
        # so the coordinate-less fallback errs toward keeping the event.
        event, _ = one({"venue": {"name": "Somewhere", "city": "Sellwood-Moreland"}})
        assert event is not None

    def test_an_event_with_no_venue_at_all_is_kept(self):
        event, _ = one({"venue": {}}, venue={})
        assert event is not None

    def test_the_eugene_area_is_dropped_without_page_details(self):
        event, counters = one(detail=None, venue={"title": "WOW Hall", "area_name": "Eugene"})
        assert event is None
        assert counters.outside_metro == 1


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


def test_output_validates():
    events, _ = normalize([raw_event(), raw_event(id=2, detail=None)], now=NOW)
    validate_per_source(build_per_source_feed("dopdx", events, generated_at=NOW))


class TestSvelteKitDecoding:
    def test_references_are_resolved(self):
        # {"browse": {"events": [{"id": 7, "title": "Show"}], "next": undefined}}
        values = [{"browse": 1}, {"events": 2, "next": -1}, [3], {"id": 4, "title": 5}, 7, "Show"]
        assert decode_node(values) == {"browse": {"events": [{"id": 7, "title": "Show"}], "next": None}}

    def test_shared_values_are_reused(self):
        values = [{"a": 1, "b": 1}, "same"]
        assert decode_node(values) == {"a": "same", "b": "same"}

    def test_dates_decode_to_their_string(self):
        assert decode_node([{"at": 1}, ["Date", "2026-11-22T00:00:00.000Z"]]) == {"at": "2026-11-22T00:00:00.000Z"}

    def test_the_innermost_node_wins(self):
        payload = {"type": "data", "nodes": [{"type": "data", "data": [{"site": 1}, "x"]},
                                             {"type": "data", "data": [{"event": 1}, {"id": 2}, 9]}]}
        assert find_key(payload, "event") == {"id": 9}

    def test_a_redirect_is_rejected(self):
        with pytest.raises(SvelteKitPayloadError):
            find_key({"type": "redirect", "location": "/"}, "browse")


def _encode(root):
    """A minimal devalue encoder: every object and array member is an index."""
    values: list = []

    def put(value):
        index = len(values)
        values.append(None)
        if isinstance(value, dict):
            values[index] = {key: put(member) for key, member in value.items()}
        elif isinstance(value, list):
            values[index] = [put(member) for member in value]
        else:
            values[index] = value
        return index

    put(root)
    return {"type": "data", "nodes": [None, {"type": "data", "data": values}]}


def _listing_payload(events, *, has_next=False):
    return _encode({"browse": {"data": [{"events": events}], "_meta": {"has_next": has_next}}})


def _detail_payload(event):
    return _encode({"event": event})


LISTED = {
    "id": 17662491,
    "title": "PSYCROPTIC",
    "permalink": "/events/2026/7/20/psycroptic-tickets",
    "tz_adjusted_begin_time": "2026-07-20T19:00:00-07:00",
    "category": "Music",
    "image_url": IMAGE,
    "venue": {"title": "Star Theater", "area_name": "Downtown"},
}


class TestFetch:
    @pytest.fixture(autouse=True)
    def _fast(self, monkeypatch):
        monkeypatch.setattr(config, "SECONDS_BETWEEN_REQUESTS", 0)
        monkeypatch.setattr(config, "FETCH_WINDOW", timedelta(days=1))

    def _register(self, detail_body):
        responses.get("https://dopdx.com/events/2026/7/20/__data.json", json=_listing_payload([LISTED]))
        responses.get(
            "https://dopdx.com/events/2026/7/20/psycroptic-tickets/__data.json",
            json=_detail_payload(detail_body),
        )

    @responses.activate
    def test_listing_and_page_details_are_joined_and_cached(self, tmp_path):
        self._register({"ticket_info": "$27.27", "free_event": False,
                        "seo_source": {"venue": {"name": "Star Theater", "city": "Portland",
                                                 "latitude": 45.52, "longitude": -122.67}}})
        cache = tmp_path / "cache.json"

        raw, stats = dopdx_fetch.fetch_raw(now=NOW, cache_path=cache)

        assert stats["detail_requests"] == 1
        assert raw[0]["detail"]["ticket_info"] == "$27.27"
        assert raw[0]["detail"]["venue"]["city"] == "Portland"
        assert "17662491" in json.loads(cache.read_text())["events"]

        events, _ = normalize(raw, now=NOW)
        assert events[0].price.min == 27.27
        assert events[0].venue.latitude == 45.52

    @responses.activate
    def test_a_fresh_cache_entry_is_not_refetched(self, tmp_path):
        self._register({"ticket_info": "$27.27"})
        cache = tmp_path / "cache.json"
        dopdx_fetch.fetch_raw(now=NOW, cache_path=cache)

        _, stats = dopdx_fetch.fetch_raw(now=NOW + timedelta(hours=3), cache_path=cache)
        assert stats["detail_requests"] == 0
        assert stats["with_detail"] == 1

    @responses.activate
    def test_the_budget_limits_page_fetches(self, tmp_path):
        self._register({"ticket_info": "$27.27"})
        raw, stats = dopdx_fetch.fetch_raw(now=NOW, cache_path=tmp_path / "c.json", detail_budget=0)
        assert stats["detail_requests"] == 0
        assert "detail" not in raw[0]

    @responses.activate
    def test_an_empty_window_fails_the_run(self):
        responses.get("https://dopdx.com/events/2026/7/20/__data.json", status=404)
        with pytest.raises(dopdx_fetch.DoPDXFetchError):
            dopdx_fetch.fetch_raw(now=NOW)


def test_stale_cache_entries_are_refreshed_oldest_first():
    listings = [{"id": 1}, {"id": 2}, {"id": 3}]
    cache = {
        "1": {"fetched_at": (NOW - timedelta(days=3)).isoformat()},
        "2": {"fetched_at": (NOW - timedelta(days=5)).isoformat()},
    }
    planned = dopdx_fetch.plan_detail_fetches(listings, cache, now=NOW, budget=2)
    assert [event["id"] for event in planned] == [3, 2]
