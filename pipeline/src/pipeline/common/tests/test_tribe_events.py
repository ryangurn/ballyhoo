"""Tests for the shared Events Calendar client.

The records here keep the quirks that differ between real sites: an empty-list venue,
HTML-escaped titles and venue names, page-builder shortcodes in the excerpt, a site
configured with a named timezone next to one configured with a fixed offset, and the
two different status codes sites return for a page past the end.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import requests
import responses

from pipeline.common.tribe_events import (
    PAGE_SIZE,
    TribeFetchError,
    fetch_events,
    has_fixed_offset_zone,
    html_to_text,
    occurrence_key,
    occurrence_times,
    parse_events,
)

PORTLAND = ZoneInfo("America/Los_Angeles")
ENDPOINT = "https://market.example/wp-json/tribe/events/v1/events"


def record(**overrides):
    base = {
        "slug": "downtown-market-72",
        "title": "Downtown Market",
        "start_date": "2026-10-10 09:00:00",
        "end_date": "2026-10-10 15:00:00",
        "utc_start_date": "2026-10-10 16:00:00",
        "utc_end_date": "2026-10-10 22:00:00",
        "timezone": "America/Los_Angeles",
        "all_day": False,
        "url": "https://market.example/event/downtown-market-72/",
        "cost": "",
        "categories": [],
        "venue": [],
        "image": False,
    }
    return {**base, **overrides}


def only(**overrides):
    parsed = parse_events({"events": [record(**overrides)]})
    assert len(parsed) == 1
    return parsed[0]


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    monkeypatch.setattr("pipeline.common.tribe_events.time.sleep", lambda _s: None)


class TestParsing:
    def test_an_empty_list_venue_is_no_venue(self):
        assert only(venue=[]).venue is None

    def test_titles_and_venue_names_are_unescaped(self):
        raw = only(
            title="Celebration of Matt Choi&#8217;s Legacy &amp; Fundraiser",
            venue={"venue": "East Market (June &#8211; September)", "address": "17199 SE Mill Plain Blvd"},
        )
        assert raw.title == "Celebration of Matt Choi\u2019s Legacy & Fundraiser"
        assert raw.venue.name == "East Market (June \u2013 September)"

    def test_records_missing_a_required_field_are_skipped(self):
        assert parse_events({"events": [record(title=""), record(url=None), record()]}) == [only()]

    def test_an_empty_cost_states_no_price(self):
        assert only(cost="").states_no_price is True
        assert only(cost="Free").states_no_price is True

    def test_a_stated_cost_is_not_read_as_free(self):
        assert only(cost="$5").states_no_price is False


class TestTimes:
    def test_a_named_zone_reads_the_utc_pair(self):
        start, end = occurrence_times(only(), PORTLAND)
        assert start.isoformat() == "2026-10-10T09:00:00-07:00"
        assert end.isoformat() == "2026-10-10T15:00:00-07:00"

    def test_a_fixed_offset_zone_reads_the_local_pair(self):
        # Oregon City's site is set to "UTC-8", so its UTC fields run an hour late all
        # summer: a 9am market comes back as 17:00 UTC, which is 10am PDT.
        raw = only(
            timezone="UTC-8",
            start_date="2026-10-10 09:00:00",
            end_date="2026-10-10 13:00:00",
            utc_start_date="2026-10-10 17:00:00",
            utc_end_date="2026-10-10 21:00:00",
        )
        assert has_fixed_offset_zone(raw) is True
        start, end = occurrence_times(raw, PORTLAND)
        assert start.isoformat() == "2026-10-10T09:00:00-07:00"
        assert end.isoformat() == "2026-10-10T13:00:00-07:00"

    @pytest.mark.parametrize("zone", ["UTC", "UTC-8", "UTC+5:30", "UTC-7"])
    def test_recognises_the_manual_offset_forms(self, zone):
        assert has_fixed_offset_zone(only(timezone=zone)) is True

    @pytest.mark.parametrize("zone", ["America/Los_Angeles", None])
    def test_a_named_or_missing_zone_is_not_a_fixed_offset(self, zone):
        assert has_fixed_offset_zone(only(timezone=zone)) is False

    def test_an_unreadable_end_becomes_no_end(self):
        _, end = occurrence_times(only(utc_end_date="soon"), PORTLAND)
        assert end is None

    def test_an_unreadable_start_raises(self):
        with pytest.raises(ValueError):
            occurrence_times(only(utc_start_date="soon"), PORTLAND)


class TestIdentity:
    def test_key_is_slug_plus_local_date(self):
        start = datetime(2026, 10, 10, 9, 0, tzinfo=PORTLAND)
        assert occurrence_key("downtown-market-72", start) == "downtown-market-72@2026-10-10"


class TestHtmlToText:
    def test_strips_page_builder_shortcodes(self):
        assert html_to_text('[vc_row full_width="stretch_row"][vc_column]<p>Fresh bread</p>[/vc_column]') == (
            "Fresh bread"
        )

    def test_empty_markup_is_no_text(self):
        assert html_to_text("<p> </p>") is None
        assert html_to_text(None) is None


def page(events, total_pages):
    return {"events": events, "total": len(events), "total_pages": total_pages}


def full_page(prefix):
    return [record(slug=f"{prefix}-{i}", url=f"https://market.example/event/{prefix}-{i}/") for i in range(PAGE_SIZE)]


class TestFetch:
    @responses.activate
    def test_stops_on_total_pages_without_asking_past_the_end(self):
        responses.add(responses.GET, ENDPOINT, json=page(full_page("a"), total_pages=1))
        collected, stats = fetch_events(ENDPOINT, seconds_between_pages=0, session=requests.Session())
        assert len(collected) == PAGE_SIZE
        assert stats["pages_read"] == 1
        assert len(responses.calls) == 1

    @responses.activate
    @pytest.mark.parametrize("status", [400, 404])
    def test_a_past_the_end_error_ends_pagination(self, status):
        # Sites disagree on which status means "no such page".
        responses.add(responses.GET, ENDPOINT, json=page(full_page("a"), total_pages=None))
        responses.add(responses.GET, ENDPOINT, status=status)
        collected, _ = fetch_events(ENDPOINT, seconds_between_pages=0, session=requests.Session())
        assert len(collected) == PAGE_SIZE

    @responses.activate
    def test_a_malformed_record_on_a_full_page_does_not_end_pagination(self):
        first = full_page("a")
        first[0] = record(title="")
        responses.add(responses.GET, ENDPOINT, json=page(first, total_pages=2))
        responses.add(responses.GET, ENDPOINT, json=page([record(slug="b-0", url="https://market.example/b-0/")], 2))
        collected, stats = fetch_events(ENDPOINT, seconds_between_pages=0, session=requests.Session())
        assert stats["pages_read"] == 2
        assert len(collected) == PAGE_SIZE

    @responses.activate
    def test_a_failed_first_page_raises(self):
        for _ in range(3):
            responses.add(responses.GET, ENDPOINT, status=503)
        with pytest.raises(TribeFetchError):
            fetch_events(ENDPOINT, seconds_between_pages=0, session=requests.Session())

    @responses.activate
    def test_identifies_itself_with_the_project_user_agent(self):
        responses.add(responses.GET, ENDPOINT, json=page([record()], total_pages=1))
        fetch_events(ENDPOINT, seconds_between_pages=0, session=requests.Session())
        assert responses.calls[0].request.headers["User-Agent"].startswith("ballyhoo-pipeline/")
