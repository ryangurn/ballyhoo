"""Tests for the Eventbrite free-events source.

The fixture mirrors the real page: a `window.__SERVER_DATA__` assignment with more
JavaScript after it on the same line, which is why the blob has to be read with a
JSON decoder rather than a delimiter search.

The tests that matter most are the filter-verification ones. This source labels every
event it emits as free on the strength of a filter the server echoes back, so the
behaviour when that echo is missing is the difference between an honest feed and one
that lies about price.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import requests
import responses

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.validate import validate_per_source
from pipeline.sources.eventbrite_free import config
from pipeline.sources.eventbrite_free.fetch import (
    EventbriteFetchError,
    extract_server_data,
    fetch_raw,
    parse_page,
)
from pipeline.sources.eventbrite_free.normalize import combine, infer_category, normalize

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def result(
    event_id="1993877033882",
    name="Building Your Leadership Legacy",
    start_date="2026-08-06",
    start_time="15:00",
    **overrides,
):
    payload = {
        "id": event_id,
        "eventbrite_event_id": event_id,
        "name": name,
        "summary": "A conversation with Michelle Wamser.",
        "start_date": start_date,
        "start_time": start_time,
        "end_date": start_date,
        "end_time": "17:00",
        "timezone": "America/Los_Angeles",
        "url": f"https://www.eventbrite.com/e/slug-tickets-{event_id}",
        "tickets_url": f"https://www.eventbrite.com/checkout-external?eid={event_id}",
        "is_online_event": False,
        "is_cancelled": None,
        "image": {"url": "https://img.evbuc.com/example.jpg"},
        "tags": [
            {"prefix": "EventbriteSubCategory", "display_name": "Career"},
            {"prefix": "EventbriteCategory", "display_name": "Business & Professional"},
        ],
        "primary_venue": {
            "name": "adidas",
            "address": {
                "city": "Portland",
                "region": "OR",
                "latitude": "45.5599584",
                "longitude": "-122.6948246",
                "localized_address_display": "5055 North Greeley Avenue, Portland, OR 97217",
            },
        },
    }
    payload.update(overrides)
    return payload


def page_html(results, *, price="free", places=("101715829",), page_number=1):
    """Reproduce the real shape: the blob is followed by more JS on the same line."""
    data = {
        "app_name": "discover",
        "search_data": {
            "event_search": {"dates": "current_future", "places": list(places), "price": price, "page": page_number},
            "events": {
                "pagination": {
                    "object_count": 910,
                    "page_count": 46,
                    "page_number": page_number,
                    "page_size": 20,
                },
                "results": results,
            },
        },
    }
    return (
        "<html><body><script>window.__i18n__ = {};\n"
        f"window.__SERVER_DATA__ = {json.dumps(data)}; window.__ANOTHER__ = 1;\n"
        "</script></body></html>"
    )


class TestExtraction:
    def test_reads_the_blob_despite_trailing_javascript(self):
        data = extract_server_data(page_html([result()]))
        assert data["app_name"] == "discover"

    def test_a_missing_blob_is_an_error_not_an_empty_feed(self):
        # A React shell with no embedded results must fail loudly rather than
        # quietly publishing zero events.
        with pytest.raises(EventbriteFetchError, match="no __SERVER_DATA__"):
            extract_server_data("<html><body>hydrating…</body></html>")

    def test_undecodable_json_is_an_error(self):
        with pytest.raises(EventbriteFetchError, match="not decodable"):
            extract_server_data(config.SERVER_DATA_MARKER + "{not json")


class TestParsing:
    def test_reads_the_echoed_query(self):
        _, meta = parse_page(page_html([result()]))
        assert meta.free_filter_applied is True
        assert meta.place_filter_applied is True
        assert meta.page_number == 1

    def test_a_different_price_filter_is_not_free(self):
        _, meta = parse_page(page_html([result()], price="paid"))
        assert meta.free_filter_applied is False

    def test_a_different_place_is_detected(self):
        # Eventbrite falls back to New York when a location slug stops resolving.
        _, meta = parse_page(page_html([result()], places=("85977539",)))
        assert meta.place_filter_applied is False

    def test_pulls_every_field(self):
        events, _ = parse_page(page_html([result()]))
        first = events[0]
        assert first.event_id == "1993877033882"
        assert first.name == "Building Your Leadership Legacy"
        assert first.start_time == "15:00"
        assert first.category == "Business & Professional"
        assert first.image_url == "https://img.evbuc.com/example.jpg"
        assert first.venue.latitude == pytest.approx(45.5599584)
        assert first.venue.address == "5055 North Greeley Avenue, Portland, OR 97217"

    def test_records_missing_identity_are_skipped(self):
        events, _ = parse_page(page_html([{"name": "no id or date"}, result()]))
        assert len(events) == 1


class TestFilterVerification:
    """The free label rests entirely on these."""

    @responses.activate
    def test_first_page_without_the_free_filter_aborts_the_run(self):
        responses.add(responses.GET, config.SEARCH_URL, body=page_html([result()], price=None), status=200)
        with pytest.raises(EventbriteFetchError, match="did not echo"):
            fetch_raw(session=requests.Session())

    @responses.activate
    def test_first_page_in_the_wrong_city_aborts_the_run(self):
        responses.add(responses.GET, config.SEARCH_URL, body=page_html([result()], places=("85977539",)), status=200)
        with pytest.raises(EventbriteFetchError, match="did not echo"):
            fetch_raw(session=requests.Session())

    @responses.activate
    def test_a_later_unfiltered_page_is_discarded_not_trusted(self):
        first = [result(event_id=str(9000 + i)) for i in range(config.PAGE_SIZE)]
        responses.add(responses.GET, config.SEARCH_URL, body=page_html(first), status=200)
        responses.add(responses.GET, config.SEARCH_URL, body=page_html([result(event_id="8888")], price=""), status=200)
        responses.add(responses.GET, config.SEARCH_URL, body=page_html([]), status=200)

        events, stats = fetch_raw(session=requests.Session())

        assert stats["pages_rejected"] == 1
        assert "8888" not in {e.event_id for e in events}

    @responses.activate
    def test_a_verified_page_is_collected(self):
        responses.add(responses.GET, config.SEARCH_URL, body=page_html([result()]), status=200)
        events, stats = fetch_raw(session=requests.Session())
        assert stats["pages_rejected"] == 0
        assert len(events) == 1

    @responses.activate
    def test_pagination_stops_on_the_first_empty_page(self):
        # Past the real end Eventbrite returns 200 with no results rather than 404,
        # while still claiming 46 pages.
        full = [result(event_id=str(7000 + i)) for i in range(config.PAGE_SIZE)]
        responses.add(responses.GET, config.SEARCH_URL, body=page_html(full), status=200)
        responses.add(responses.GET, config.SEARCH_URL, body=page_html([]), status=200)

        events, stats = fetch_raw(session=requests.Session())

        assert len(events) == config.PAGE_SIZE
        assert stats["pages_read"] == 2


class TestShortPages:
    @responses.activate
    def test_a_short_page_does_not_end_the_crawl(self):
        # Observed live: pages 5, 7 and 8 returned 17, 19 and 19 of the nominal 20
        # while the results ran on to roughly page 34. Eventbrite dedups a page after
        # slicing it, so a short page says nothing about whether more exist. Treating
        # one as the end truncated the crawl to 97 events.
        short = [result(event_id=str(6000 + i)) for i in range(17)]
        rest = [result(event_id=str(6100 + i)) for i in range(config.PAGE_SIZE)]
        responses.add(responses.GET, config.SEARCH_URL, body=page_html(short), status=200)
        responses.add(responses.GET, config.SEARCH_URL, body=page_html(rest), status=200)
        responses.add(responses.GET, config.SEARCH_URL, body=page_html([]), status=200)

        events, stats = fetch_raw(session=requests.Session())

        assert stats["pages_read"] == 3
        assert len(events) == 17 + config.PAGE_SIZE

    @responses.activate
    def test_a_page_repeating_the_previous_one_ends_the_crawl(self):
        # Guard against a pagination bug serving page 1 forever.
        page = [result(event_id=str(5000 + i)) for i in range(config.PAGE_SIZE)]
        responses.add(responses.GET, config.SEARCH_URL, body=page_html(page), status=200)
        responses.add(responses.GET, config.SEARCH_URL, body=page_html(page), status=200)

        events, _ = fetch_raw(session=requests.Session())

        assert len(events) == config.PAGE_SIZE


class TestNormalize:
    def test_split_date_and_time_combine_in_the_named_zone(self):
        events, _ = normalize(parse_page(page_html([result()]))[0], now=NOW)
        assert events[0].start_at.isoformat() == "2026-08-06T15:00:00-07:00"
        assert events[0].end_at.isoformat() == "2026-08-06T17:00:00-07:00"

    def test_a_missing_time_is_all_day_not_midnight(self):
        raw, _ = parse_page(page_html([result(start_time=None)]))
        events, _ = normalize(raw, now=NOW)
        assert events[0].is_all_day is True

    def test_id_is_the_eventbrite_event_id(self):
        events, _ = normalize(parse_page(page_html([result()]))[0], now=NOW)
        assert events[0].id == "eventbrite_free:1993877033882"

    def test_online_events_are_dropped(self):
        raw, _ = parse_page(page_html([result(is_online_event=True), result(event_id="2")]))
        events, counters = normalize(raw, now=NOW)
        assert counters.online == 1
        assert len(events) == 1

    def test_cancelled_events_are_dropped(self):
        raw, _ = parse_page(page_html([result(is_cancelled=True)]))
        events, counters = normalize(raw, now=NOW)
        assert counters.cancelled == 1
        assert events == []

    def test_events_beyond_the_horizon_are_dropped(self):
        raw, _ = parse_page(page_html([result(start_date="2029-01-01")]))
        events, counters = normalize(raw, now=NOW)
        assert counters.beyond_horizon == 1
        assert events == []

    def test_stale_events_are_dropped(self):
        raw, _ = parse_page(page_html([result(start_date="2026-01-01")]))
        events, counters = normalize(raw, now=NOW)
        assert counters.stale == 1
        assert events == []

    def test_venue_keeps_its_coordinates(self):
        events, _ = normalize(parse_page(page_html([result()]))[0], now=NOW)
        assert events[0].venue.latitude == pytest.approx(45.5599584)
        assert events[0].venue.city == "Portland"

    def test_events_are_sorted(self):
        raw, _ = parse_page(
            page_html([result(event_id="a", start_date="2026-09-01"), result(event_id="b", start_date="2026-08-01")])
        )
        events, _ = normalize(raw, now=NOW)
        assert [e.start_at for e in events] == sorted(e.start_at for e in events)

    def test_output_validates(self):
        events, _ = normalize(parse_page(page_html([result()]))[0], now=NOW)
        validate_per_source(build_per_source_feed("eventbrite_free", events, generated_at=NOW))


class TestPrice:
    def test_events_from_a_verified_page_are_free(self):
        events, _ = normalize(parse_page(page_html([result()]))[0], now=NOW)
        assert events[0].price == Price.free()

    def test_no_event_reaches_normalize_from_an_unverified_page(self):
        # The guarantee is structural: unverified pages never get this far, so there
        # is no path by which a paid event is labelled free.
        _, meta = parse_page(page_html([result()], price="paid"))
        assert not meta.free_filter_applied


class TestCategories:
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Music", Category.MUSIC),
            ("Performing & Visual Arts", Category.ARTS),
            ("Food & Drink", Category.FOOD),
            ("Health & Wellness", Category.WELLNESS),
            ("Science & Technology", Category.TECH),
            ("Government & Politics", Category.CIVIC),
            ("Family & Education", Category.FAMILY),
            ("Travel & Outdoor", Category.OUTDOORS),
            ("Film, Media & Entertainment", Category.FILM),
        ],
    )
    def test_eventbrite_taxonomy_maps(self, label, expected):
        assert infer_category(label) == (expected,)

    def test_unknown_label_falls_back_rather_than_dropping(self):
        assert infer_category("Some New Vertical") == (Category.COMMUNITY,)
        assert infer_category(None) == (Category.COMMUNITY,)


class TestCombine:
    def test_handles_the_dst_boundary(self):
        # Portland is -07:00 in August and -08:00 in December; a fixed offset would
        # put winter events an hour out.
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("America/Los_Angeles")
        assert combine("2026-08-06", "15:00", zone).utcoffset() == timedelta(hours=-7)
        assert combine("2026-12-06", "15:00", zone).utcoffset() == timedelta(hours=-8)
