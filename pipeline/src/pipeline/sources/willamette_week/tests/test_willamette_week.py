"""Tests for the Willamette Week / CitySpark source.

`fixtures/get_events_page.json` is a real response envelope from
`portal.cityspark.com/api/events/GetEvents/WillametteWeek`. Every event record in it is
byte-for-byte what the endpoint returned on 2026-07-27; only which records are in the
list was curated, to cover the edge cases in one file. The assertions below quote those
real values rather than invented ones, so a change in the upstream shape shows up here.

The load-bearing test is `TestTheTimestampTrap`. Everything else can be wrong by a
little; that one being wrong is wrong by seven hours on every event in the feed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import requests
import responses

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.validate import validate_per_source
from pipeline.sources.willamette_week import config
from pipeline.sources.willamette_week.categories import (
    DEFAULT_CATEGORY,
    FACET_TAGS,
    REFINEMENTS,
    ROOTS,
    infer_categories,
    reset_unmapped,
    unmapped_tags,
)
from pipeline.sources.willamette_week.fetch import (
    ResultCeilingExceeded,
    WillametteWeekFetchError,
    fetch_raw,
)
from pipeline.sources.willamette_week.normalize import normalize

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)

_FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "get_events_page.json").read_text())
RAW_EVENTS: list[dict] = _FIXTURE["Value"]


def raw_by_name(prefix: str) -> dict:
    for event in RAW_EVENTS:
        if event["Name"].startswith(prefix):
            return event
    raise AssertionError(f"no fixture event starting with {prefix!r}")


def one(raw: dict, **overrides):
    """Normalize a single record, with optional overrides applied to a copy."""
    payload = {**raw, **overrides}
    events, counters = normalize([payload], now=NOW)
    return (events[0] if events else None), counters


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    """The fetcher paces itself politely; the tests should not pay for that."""
    monkeypatch.setattr("pipeline.sources.willamette_week.fetch.time.sleep", lambda _s: None)


@pytest.fixture(autouse=True)
def _clean_category_gaps():
    reset_unmapped()
    yield
    reset_unmapped()


class TestTheTimestampTrap:
    """`DateStart`/`DateEnd` are Portland local time wearing a `Z`. Only `*UTC` is real.

    Measured across 2,025 live events, `StartUTC - DateStart` was exactly 7 hours on
    every single one — the Pacific daylight offset. Reading `DateStart` as the UTC it
    claims to be would move the whole feed by that much.
    """

    def test_the_fixture_still_contains_the_contradiction(self):
        # If upstream ever fixes this, the guard below stops proving anything, so the
        # trap itself is asserted rather than assumed.
        camp = raw_by_name("Champ Camp")
        assert camp["DateStart"] == "2026-07-27T07:30:00Z"
        assert camp["StartUTC"] == "2026-07-27T14:30:00Z"

    def test_start_comes_from_startutc_not_datestart(self):
        event, _ = one(raw_by_name("Champ Camp"))
        # 14:30Z is 07:30 in Portland, which is what DateStart says in local terms.
        # Had DateStart been parsed as UTC, this would read 00:30-07:00.
        assert event.start_at.isoformat() == "2026-07-27T07:30:00-07:00"
        assert event.start_at.astimezone(UTC).isoformat() == "2026-07-27T14:30:00+00:00"

    def test_end_comes_from_endutc_not_dateend(self):
        camp = raw_by_name("Champ Camp")
        assert camp["DateEnd"] == "2026-07-27T17:30:00Z"
        assert camp["EndUTC"] == "2026-07-28T00:30:00Z"
        event, _ = one(camp)
        assert event.end_at.isoformat() == "2026-07-27T17:30:00-07:00"

    def test_every_fixture_event_lands_on_its_local_wall_clock(self):
        # The whole-corpus version of the same claim: for each record, the local time
        # we publish must equal the wall time DateStart states.
        events, _ = normalize(RAW_EVENTS, now=NOW)
        by_pid = {int(e.id.split(":")[1].split("@")[0]): e for e in events}
        for raw in RAW_EVENTS:
            event = by_pid.get(raw["PId"])
            if event is None:
                continue  # dropped for some other reason; covered elsewhere
            assert event.start_at.strftime("%Y-%m-%dT%H:%M:%S") == raw["DateStart"][:19], raw["Name"]

    def test_events_are_published_in_portland_time(self):
        event, _ = one(raw_by_name("7 Wonders"))
        assert event.start_at.utcoffset().total_seconds() == -7 * 3600


class TestIdentifiers:
    """`Id` embeds the last-modified date and so cannot anchor a bookmark."""

    def test_id_is_the_series_id_plus_the_occurrence_instant(self):
        event, _ = one(raw_by_name("Champ Camp"))
        assert event.id == "willamette_week:2027211856@2026-07-27T07:30"

    def test_the_volatile_upstream_id_is_not_used(self):
        camp = raw_by_name("Champ Camp")
        # Its first six characters are the `lm` date: this held on 2,025 of 2,025
        # sampled events, so an upstream edit would rewrite it.
        assert camp["Id"][:6] == camp["lm"][2:10].replace("-", "")
        event, _ = one(camp)
        assert camp["Id"] not in event.id

    def test_occurrences_of_one_series_get_distinct_ids(self):
        raw = raw_by_name("All abilities")
        later = {**raw, "StartUTC": "2026-07-28T17:00:00Z", "EndUTC": "2026-07-28T19:00:00Z"}
        events, _ = normalize([raw, later], now=NOW)
        assert len({e.id for e in events}) == 2

    def test_an_edit_that_only_moves_the_last_modified_date_keeps_the_id(self):
        raw = raw_by_name("Champ Camp")
        edited = {**raw, "lm": "2026-07-27T09:00:00Z", "Id": "260727somethingelse", "Description": "Reworded."}
        assert one(raw)[0].id == one(edited)[0].id

    def test_two_occurrences_at_the_same_instant_collapse_rather_than_collide(self):
        raw = raw_by_name("Woven Light")
        events, _ = normalize([raw, {**raw, "Name": "Woven Light (duplicate row)"}], now=NOW)
        assert len(events) == 1


class TestAllDayHandling:
    def test_allday_flag_is_honoured(self):
        event, _ = one(raw_by_name("Everett AquaSox"))
        assert event.is_all_day is True

    def test_hastime_false_counts_as_all_day_even_without_the_flag(self):
        # 86 events had HasTime false while only 10 set AllDay, and every AllDay event
        # also had HasTime false, so AllDay alone under-reports by 8x.
        hearing = raw_by_name("Historic Landmarks")
        assert hearing["AllDay"] is False and hearing["HasTime"] is False
        event, _ = one(hearing)
        assert event.is_all_day is True

    def test_an_all_day_event_starts_at_local_midnight(self):
        # Upstream stores 07:00Z as the placeholder, which is midnight in Portland.
        # Left in UTC it would render as 7am and file under the wrong day.
        event, _ = one(raw_by_name("Everett AquaSox"))
        assert event.start_at.isoformat() == "2026-07-28T00:00:00-07:00"

    def test_a_timed_event_is_not_marked_all_day(self):
        event, _ = one(raw_by_name("7 Wonders"))
        assert event.is_all_day is False


class TestFiltering:
    def test_virtual_events_are_dropped(self):
        lutop = raw_by_name("LUTOP")
        assert lutop["isVirtual"] is True
        event, counters = one(lutop)
        assert event is None
        assert counters.virtual == 1

    def test_hybrid_and_remote_labels_do_not_drop_an_event(self):
        # csHybrid events have a real venue; only isVirtual is authoritative.
        event, _ = one(raw_by_name("7 Wonders"), Labels=["csRemote", "csHybrid"])
        assert event is not None

    def test_events_beyond_the_radius_are_dropped(self):
        gleaners = raw_by_name("Gales Creek")
        assert gleaners["Distance"] == 26.4
        event, counters = one(gleaners)
        assert event is None
        assert counters.outside_radius == 1

    def test_an_event_at_the_metro_edge_is_kept(self):
        # Forest Grove measured 23.5 miles out and belongs in a Portland feed.
        event, _ = one(raw_by_name("Champ Camp"), Distance=23.5)
        assert event is not None

    def test_a_missing_distance_is_not_grounds_for_dropping(self):
        event, _ = one(raw_by_name("7 Wonders"), Distance=None)
        assert event is not None

    def test_an_event_without_a_start_is_dropped(self):
        event, counters = one(raw_by_name("7 Wonders"), StartUTC=None)
        assert event is None
        assert counters.no_start == 1

    def test_an_unparseable_start_is_dropped_not_guessed(self):
        event, counters = one(raw_by_name("7 Wonders"), StartUTC="soon")
        assert event is None
        assert counters.unparseable_time == 1

    def test_an_unparseable_end_does_not_lose_the_event(self):
        event, _ = one(raw_by_name("7 Wonders"), EndUTC="later")
        assert event is not None
        assert event.end_at is None

    def test_a_titleless_event_is_dropped(self):
        event, counters = one(raw_by_name("7 Wonders"), Name="   ")
        assert event is None
        assert counters.no_title == 1

    def test_stale_events_are_dropped(self):
        events, counters = normalize([raw_by_name("7 Wonders")], now=datetime(2026, 9, 1, tzinfo=UTC))
        assert events == []
        assert counters.stale == 1


class TestPricing:
    def test_the_free_flag_wins(self):
        biennial = raw_by_name("Youth Arts Biennial")
        assert biennial["Free"] is True
        event, _ = one(biennial)
        assert event.price == Price.free()

    def test_a_range_uses_price_as_the_low_and_pricehigh_as_the_high(self):
        gorge = raw_by_name("7 Wonders")
        assert (gorge["Price"], gorge["PriceHigh"]) == (72, 87)
        event, _ = one(gorge)
        assert (event.price.min, event.price.max, event.price.is_free) == (72.0, 87.0, False)

    def test_a_single_price_sets_both_bounds(self):
        event, _ = one(raw_by_name("Play, Bounce"))
        assert (event.price.min, event.price.max) == (13.0, 13.0)

    def test_a_zero_low_with_a_paid_tier_is_a_range_not_free(self):
        # 32 live events look like this: a free tier alongside paid ones. Badging them
        # "Free" would be a promise the door does not keep.
        sordid = raw_by_name("Sordid Behavior")
        assert (sordid["Free"], sordid["Price"], sordid["PriceHigh"]) == (False, 0, 10)
        event, _ = one(sordid)
        assert event.price.is_free is False
        assert (event.price.min, event.price.max) == (0.0, 10.0)

    def test_no_price_information_is_unknown_not_free(self):
        # 60% of live events. Unknown and free are different claims.
        event, _ = one(raw_by_name("Champ Camp"))
        assert event.price == Price.unknown()
        assert event.price.is_free is False

    def test_pricetext_is_not_parsed_into_a_number(self):
        event, _ = one(raw_by_name("Champ Camp"), PriceText="$5 advance/$6 doors")
        assert event.price == Price.unknown()


class TestImages:
    def test_the_large_rendition_is_preferred(self):
        # CitySpark caps its own renditions at 700 px / 1.83 MB decoded, measured over
        # 90 images — a seventh of the Ticketmaster artwork that exhausted the app's
        # memory, and well inside the same bound.
        event, _ = one(raw_by_name("7 Wonders"))
        assert event.image_url.endswith(".large.jpg")

    def test_it_falls_back_down_the_ladder(self):
        raw = raw_by_name("7 Wonders")
        event, _ = one(raw, LargeImg=None)
        assert event.image_url == raw["MediumImg"]
        event, _ = one(raw, LargeImg=None, MediumImg=None)
        assert event.image_url == raw["SmallImg"]

    def test_the_images_array_is_the_last_resort(self):
        raw = raw_by_name("7 Wonders")
        event, _ = one(raw, LargeImg=None, MediumImg=None, SmallImg=None)
        assert event.image_url == raw["Images"][0]["url"]

    def test_no_image_is_not_an_error(self):
        event, _ = one(raw_by_name("Salary Review"), LargeImg=None, MediumImg=None, SmallImg=None, Images=[])
        assert event is not None
        assert event.image_url is None


class TestUrls:
    def test_the_organizer_page_is_the_listing(self):
        event, _ = one(raw_by_name("Woven Light"))
        assert event.listing_url.startswith("https://japanesegarden.org/")

    def test_the_ticket_url_is_carried_separately(self):
        event, _ = one(raw_by_name("7 Wonders"))
        assert event.ticket_url == "https://www.portlandspirit.com/cruise/7wonders/"

    def test_the_ticket_url_stands_in_when_there_is_no_listing(self):
        event, _ = one(raw_by_name("Champ Camp"))
        assert event.listing_url == event.ticket_url
        assert "discoverchampions.com" in event.listing_url

    def test_no_urls_at_all_is_tolerated(self):
        event, _ = one(raw_by_name("Everett AquaSox"))
        assert event.listing_url is None
        assert event.ticket_url is None

    def test_the_get_busy_deep_link_is_never_emitted(self):
        # It is reconstructible from PId and DateStart, and it 404s: the path is a
        # client-side route inside the embedded widget, not a page the site serves.
        for event, _ in (one(raw) for raw in RAW_EVENTS):
            if event is not None and event.listing_url:
                assert "/getbusy/calendar/events/details/" not in event.listing_url


class TestVenue:
    def test_the_named_venue_carries_its_coordinates(self):
        event, _ = one(raw_by_name("Woven Light"))
        assert event.venue.name == "Portland Japanese Garden"
        assert event.venue.city == "Portland"
        assert event.venue.address == "611 SW Kingston Ave"
        assert event.venue.latitude == pytest.approx(45.5194078)
        assert event.venue.longitude == pytest.approx(-122.7090681)

    def test_every_event_is_pre_geocoded(self):
        # Coordinates were present on all 2,025 sampled events, so this source needs no
        # geocoding step and no venue lookup table.
        events, _ = normalize(RAW_EVENTS, now=NOW)
        assert all(e.venue.has_coordinates for e in events)

    def test_an_unnamed_venue_falls_back_to_the_city_rather_than_vanishing(self):
        # 135 live events have no Venue string, mostly city meetings. Dropping the
        # venue would drop the coordinates too and take them off the map.
        hearing = raw_by_name("Historic Landmarks")
        assert hearing["Venue"] is None
        event, _ = one(hearing)
        assert event.venue.name == "Portland"
        assert event.venue.has_coordinates

    def test_the_city_is_split_off_the_citystate_pair(self):
        event, _ = one(raw_by_name("Work Party"))
        assert event.venue.city == "Vancouver"


class TestSummary:
    def test_the_description_is_the_summary(self):
        event, _ = one(raw_by_name("Champ Camp"))
        assert event.summary.startswith("Champ Camp Great Outdoors at River Grove Elementary is a summer camp")

    def test_the_boilerplate_short_field_is_never_used(self):
        # All 2,025 sampled events began "The event is held on ...". It is generated
        # filler, not a summary.
        for raw in RAW_EVENTS:
            assert raw["Short"].startswith("The event is held on")
        events, _ = normalize(RAW_EVENTS, now=NOW)
        assert not any((e.summary or "").startswith("The event is held on") for e in events)

    def test_markdown_is_unwrapped(self):
        event, _ = one(
            raw_by_name("7 Wonders"),
            Description="Join us for **the best** cruise. [Book here](https://example.com/x) now.",
        )
        assert event.summary == "Join us for the best cruise. Book here now."

    def test_an_empty_description_is_none_not_an_empty_string(self):
        event, _ = one(raw_by_name("7 Wonders"), Description="")
        assert event.summary is None


class TestCategories:
    def test_music_beats_the_audience_facet(self):
        # A kids' concert is music, not family: what it is beats who it is for.
        assert infer_categories([15, 80, 2, 17]) == (Category.MUSIC,)

    def test_government_meetings_outrank_the_talks_tag_they_also_carry(self):
        hearing = raw_by_name("Historic Landmarks")
        assert 439 in hearing["Tags"]
        assert infer_categories(hearing["Tags"]) == (Category.CIVIC,)
        conference = raw_by_name("Pre-Application")
        assert {40, 439} <= set(conference["Tags"])
        assert infer_categories(conference["Tags"]) == (Category.CIVIC,)

    def test_farmers_markets_outrank_the_general_shopping_tag(self):
        assert infer_categories([76, 54, 385]) == (Category.MARKET,)
        assert infer_categories([76, 54]) == (Category.MARKET,)

    @pytest.mark.parametrize(
        "prefix,expected",
        [
            ("7 Wonders", Category.OUTDOORS),        # Outdoor Recreation
            ("Youth Arts Biennial", Category.ARTS),  # Visual Arts
            ("Everett AquaSox", Category.SPORTS),    # Sports
            ("Play, Bounce", Category.FAMILY),       # Zoos & Animals
            ("Woven Light", Category.ARTS),          # Museums & Exhibits
            ("Historic Landmarks", Category.CIVIC),  # Government Meetings
        ],
    )
    def test_real_events_land_where_expected(self, prefix, expected):
        assert infer_categories(raw_by_name(prefix)["Tags"]) == (expected,)

    def test_a_deep_leaf_resolves_through_the_ancestors_sent_alongside_it(self):
        # 98.9% of tagged events carry the whole chain, which is why no 720-entry
        # taxonomy file is shipped. Ska(242) means nothing here; Music(17) does.
        assert infer_categories([2, 17, 96, 242, 270]) == (Category.MUSIC,)

    def test_the_special_audience_root_alone_does_not_mean_family(self):
        # It covers Special Needs (204 events) and LGBT (176) as well as Kids.
        assert infer_categories([15, 429]) == (DEFAULT_CATEGORY,)
        assert infer_categories([15, 363]) == (DEFAULT_CATEGORY,)
        assert infer_categories([15, 80]) == (Category.FAMILY,)

    def test_drag_shows_are_an_event_type_not_an_audience(self):
        # The one Special Audience descendant that names what happens on stage.
        assert infer_categories([15, 363, 9363]) == (Category.NIGHTLIFE,)

    def test_audience_facets_are_not_reported_as_gaps_run_after_run(self):
        # A live run flagged 82, 363 and 9363 before the whole facet subtree was
        # enumerated. Anything reported every run drowns out the one that matters.
        infer_categories([15, 363])
        infer_categories([15, 82])
        infer_categories([15, 429])
        infer_categories([421, 442])
        assert unmapped_tags() == []

    def test_an_untagged_event_falls_back(self):
        untagged = raw_by_name("Kevian Kraemer")
        assert untagged["Tags"] == []
        assert infer_categories(untagged["Tags"]) == (DEFAULT_CATEGORY,)
        assert infer_categories(None) == (DEFAULT_CATEGORY,)

    def test_an_unknown_tag_falls_back_and_is_reported(self):
        assert infer_categories([999999]) == (DEFAULT_CATEGORY,)
        assert unmapped_tags() == [999999]

    def test_a_facet_tag_is_not_reported_as_a_gap(self):
        # Excluded on purpose, so it must not show up as a table to fill in.
        assert infer_categories([423]) == (DEFAULT_CATEGORY,)
        assert unmapped_tags() == []

    def test_an_untagged_event_reports_no_gap(self):
        infer_categories([])
        assert unmapped_tags() == []

    def test_the_tables_have_no_duplicate_ids(self):
        # A repeated id is dead code: the earlier entry always wins, silently.
        refinement_ids = [t for t, _ in REFINEMENTS]
        root_ids = [t for t, _ in ROOTS]
        assert len(refinement_ids) == len(set(refinement_ids))
        assert len(root_ids) == len(set(root_ids))
        assert not set(refinement_ids) & set(root_ids)
        assert not set(root_ids) & FACET_TAGS
        # A tag listed as an ignorable facet must not also be mapped, or one of the two
        # entries is dead code. Kids, Family, Teens and Drag Show all sit under a facet
        # root and are mapped, so they belong in exactly one table: this one's.
        assert not set(refinement_ids) & FACET_TAGS


class TestNormalizeOverTheWholeFixture:
    def test_the_expected_records_survive(self):
        events, counters = normalize(RAW_EVENTS, now=NOW)
        # 16 records in, minus one virtual and one beyond the radius.
        assert len(events) == len(RAW_EVENTS) - 2
        assert counters.virtual == 1
        assert counters.outside_radius == 1

    def test_events_come_back_in_chronological_order(self):
        events, _ = normalize(RAW_EVENTS, now=NOW)
        assert events == sorted(events, key=lambda e: e.start_at)

    def test_the_feed_validates_against_the_schema(self):
        events, _ = normalize(RAW_EVENTS, now=NOW)
        validate_per_source(build_per_source_feed(config.SOURCE.id, events, generated_at=NOW))


def _page(events, success=True, error=None):
    return {
        "Value": events,
        "Possible": 0,
        "ErrorMessage": error,
        "Success": success,
        "UserOkErrorMsg": False,
    }


class TestFetch:
    @responses.activate
    def test_it_slices_the_window_and_deduplicates_the_overlap(self, monkeypatch):
        # A request for one range returns the day after it too, so the same event
        # arrives in two consecutive windows.
        monkeypatch.setattr(config, "FETCH_WINDOW", config.FETCH_WINDOW.__class__(days=13))
        responses.add(responses.POST, config.EVENTS_URL, json=_page(RAW_EVENTS[:3]))
        responses.add(responses.POST, config.EVENTS_URL, json=_page([]))
        responses.add(responses.POST, config.EVENTS_URL, json=_page(RAW_EVENTS[2:5]))
        responses.add(responses.POST, config.EVENTS_URL, json=_page([]))

        collected, stats = fetch_raw(now=NOW, session=requests.Session())
        assert stats["windows"] == 2
        assert len(collected) == 5
        assert len({e["Id"] for e in collected}) == 5

    @responses.activate
    def test_it_pages_within_a_window_until_a_page_comes_back_empty(self, monkeypatch):
        monkeypatch.setattr(config, "FETCH_WINDOW", config.FETCH_WINDOW.__class__(days=1))
        responses.add(responses.POST, config.EVENTS_URL, json=_page(RAW_EVENTS[:8]))
        responses.add(responses.POST, config.EVENTS_URL, json=_page(RAW_EVENTS[8:]))
        responses.add(responses.POST, config.EVENTS_URL, json=_page([]))

        collected, stats = fetch_raw(now=NOW, session=requests.Session())
        assert len(collected) == len(RAW_EVENTS)
        assert stats["requests_made"] == 3

    @responses.activate
    def test_skip_advances_by_the_page_size_actually_returned(self, monkeypatch):
        monkeypatch.setattr(config, "FETCH_WINDOW", config.FETCH_WINDOW.__class__(days=1))
        responses.add(responses.POST, config.EVENTS_URL, json=_page(RAW_EVENTS[:5]))
        responses.add(responses.POST, config.EVENTS_URL, json=_page([]))
        fetch_raw(now=NOW, session=requests.Session())
        assert [json.loads(c.request.body)["skip"] for c in responses.calls] == [0, 5]

    @responses.activate
    def test_the_result_ceiling_aborts_the_run(self, monkeypatch):
        # The endpoint stops at ~2,025 results and says so instead of returning an
        # empty page. Publishing the prefix would look healthy and be incomplete.
        monkeypatch.setattr(config, "FETCH_WINDOW", config.FETCH_WINDOW.__class__(days=1))
        responses.add(responses.POST, config.EVENTS_URL, json=_page(RAW_EVENTS[:2]))
        responses.add(
            responses.POST,
            config.EVENTS_URL,
            json=_page([], success=False, error=config.CEILING_ERROR_MESSAGE),
        )
        with pytest.raises(ResultCeilingExceeded, match="Shorten config.WINDOW_DAYS"):
            fetch_raw(now=NOW, session=requests.Session())

    @responses.activate
    def test_any_other_unsuccessful_body_is_also_fatal(self, monkeypatch):
        # HTTP 200 with Success=false is the shape a .NET envelope fails in. Reading it
        # as "no events" would publish whole missing weeks silently.
        monkeypatch.setattr(config, "FETCH_WINDOW", config.FETCH_WINDOW.__class__(days=1))
        responses.add(responses.POST, config.EVENTS_URL, json=_page([], success=False, error="ppid not found"))
        with pytest.raises(WillametteWeekFetchError, match="ppid not found"):
            fetch_raw(now=NOW, session=requests.Session())

    @responses.activate
    def test_an_unrecognised_envelope_is_fatal(self, monkeypatch):
        monkeypatch.setattr(config, "FETCH_WINDOW", config.FETCH_WINDOW.__class__(days=1))
        responses.add(responses.POST, config.EVENTS_URL, json={"events": []})
        with pytest.raises(WillametteWeekFetchError, match="unrecognised response shape"):
            fetch_raw(now=NOW, session=requests.Session())

    @responses.activate
    def test_an_empty_run_is_fatal_rather_than_an_empty_feed(self, monkeypatch):
        monkeypatch.setattr(config, "FETCH_WINDOW", config.FETCH_WINDOW.__class__(days=1))
        responses.add(responses.POST, config.EVENTS_URL, json=_page([]))
        with pytest.raises(WillametteWeekFetchError, match="no events"):
            fetch_raw(now=NOW, session=requests.Session())

    @responses.activate
    def test_the_page_cap_stops_a_runaway_loop(self, monkeypatch):
        # A response that never empties must not become an unbounded crawl of someone
        # else's server.
        monkeypatch.setattr(config, "FETCH_WINDOW", config.FETCH_WINDOW.__class__(days=1))
        monkeypatch.setattr(config, "MAX_PAGES_PER_WINDOW", 4)
        responses.add(responses.POST, config.EVENTS_URL, json=_page(RAW_EVENTS[:2]))
        _, stats = fetch_raw(now=NOW, session=requests.Session())
        assert stats["requests_made"] == 4

    @responses.activate
    def test_it_identifies_itself_honestly_and_impersonates_nothing(self, monkeypatch):
        # Measured: the project User-Agent with no Origin and no Referer returns a
        # byte-identical response to the browser's request, so the honest headers cost
        # nothing. See pipeline/common/http.py.
        monkeypatch.setattr(config, "FETCH_WINDOW", config.FETCH_WINDOW.__class__(days=1))
        responses.add(responses.POST, config.EVENTS_URL, json=_page(RAW_EVENTS[:1]))
        responses.add(responses.POST, config.EVENTS_URL, json=_page([]))
        fetch_raw(now=NOW, session=requests.Session())

        headers = responses.calls[0].request.headers
        assert headers["User-Agent"] == "ballyhoo-pipeline/0.1 (github.com/ryangurn/ballyhoo)"
        assert "Origin" not in headers
        assert "Referer" not in headers

    @responses.activate
    def test_the_request_carries_the_partner_id_and_radius(self, monkeypatch):
        monkeypatch.setattr(config, "FETCH_WINDOW", config.FETCH_WINDOW.__class__(days=1))
        responses.add(responses.POST, config.EVENTS_URL, json=_page(RAW_EVENTS[:1]))
        responses.add(responses.POST, config.EVENTS_URL, json=_page([]))
        fetch_raw(now=NOW, session=requests.Session())

        body = json.loads(responses.calls[0].request.body)
        assert body["ppid"] == 9934
        assert body["distance"] == config.RADIUS_MILES
        # A one-day FETCH_WINDOW covers today and tomorrow, and both fit in one slice.
        # The bounds are sent without an offset because they are local wall times, the
        # same convention the `DateStart` field uses.
        assert body["start"] == "2026-07-27T00:00"
        assert body["end"] == "2026-07-28T23:59"

    @responses.activate
    def test_transport_failures_are_retried(self, monkeypatch):
        monkeypatch.setattr(config, "FETCH_WINDOW", config.FETCH_WINDOW.__class__(days=1))
        responses.add(responses.POST, config.EVENTS_URL, body=requests.ConnectionError("reset"))
        responses.add(responses.POST, config.EVENTS_URL, json=_page(RAW_EVENTS[:1]))
        responses.add(responses.POST, config.EVENTS_URL, json=_page([]))
        collected, _ = fetch_raw(now=NOW, session=requests.Session())
        assert len(collected) == 1


class TestRegistration:
    def test_the_source_is_discovered_by_the_merge_registry(self):
        # Sources are found by walking the package tree, so creating the package is
        # the registration. This asserts that actually holds.
        from pipeline.merge.registry import configured_sources

        assert config.SOURCE in configured_sources()

    def test_the_source_id_is_a_legal_identifier(self):
        assert config.SOURCE.id == "willamette_week"


class TestCrossSourceDedup:
    """About 6% of live results carry Ticketmaster or Vivid Seats ticketing links, so
    overlap with the existing ticketmaster source is expected rather than hypothetical.

    `willamette_week` is deliberately absent from `merge.dedupe._SOURCE_PRIORITY`. These
    tests check that the resulting behavior is the one we want rather than the one we
    assumed: it must still *match*, and it must always *lose*.
    """

    @staticmethod
    def _counterpart(source_id: str, ww_event, **overrides):
        from pipeline.common.models import Event, Price, Source, Venue

        base = {
            "id": f"{source_id}:1",
            "title": ww_event.title,
            "start_at": ww_event.start_at,
            "price": Price.free(),
            "source": Source(id=source_id, name=source_id),
            # A different rendering of the same venue, which is what dedup has to see
            # through: the normalizer strips leading articles and punctuation.
            "venue": Venue(name=f"The {ww_event.venue.name}"),
        }
        return Event(**{**base, **overrides})

    def test_a_ticketmaster_duplicate_matches_and_ticketmaster_survives(self):
        from pipeline.merge.dedupe import deduplicate

        ww, _ = one(raw_by_name("7 Wonders"))
        merged, audit = deduplicate([ww, self._counterpart("ticketmaster", ww)])
        assert len(merged) == 1
        assert merged[0].source.id == "ticketmaster"
        assert merged[0].merged_sources == ("ticketmaster", "willamette_week")
        assert audit[0]["dropped"] == ww.id

    def test_the_survivor_backfills_from_the_willamette_week_copy(self):
        # Losing the tie must not lose the data: WW carries coordinates on 100% of
        # events, which Ticketmaster's venue block sometimes lacks.
        from pipeline.merge.dedupe import deduplicate

        ww, _ = one(raw_by_name("Woven Light"))
        merged, _ = deduplicate([ww, self._counterpart("ticketmaster", ww, image_url=None)])
        assert merged[0].image_url == ww.image_url

    @pytest.mark.parametrize(
        "other",
        ["calagator", "dopdx", "oregon_metro", "portland_parks", "portland_farmers_market", "obt"],
    )
    def test_it_ranks_below_every_existing_source(self, other):
        # Absent sources are ordered by id, and `willamette_week` sorts last. That is
        # the intended outcome — every one of these is the first-party record for its
        # own events, where WW is republishing a submission.
        from pipeline.merge.dedupe import deduplicate

        ww, _ = one(raw_by_name("7 Wonders"))
        merged, _ = deduplicate([ww, self._counterpart(other, ww)])
        assert len(merged) == 1
        assert merged[0].source.id == other

    def test_two_occurrences_within_one_source_are_never_collapsed(self):
        # A recurring series legitimately repeats; only cross-source pairs merge.
        from pipeline.merge.dedupe import deduplicate

        raw = raw_by_name("All abilities")
        events, _ = normalize([raw, {**raw, "StartUTC": "2026-07-28T17:00:00Z"}], now=NOW)
        merged, audit = deduplicate(events)
        assert len(merged) == 2
        assert audit == []
