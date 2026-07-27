"""Tests for the Ticketmaster source.

Cases come from quirks observed in live Portland responses: an undocumented
`Undefined` segment, cancelled events still present in results, placeholder times,
string coordinates, and price data missing on most events.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import requests
import responses

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.validate import validate_per_source
from pipeline.sources.ticketmaster import config
from pipeline.sources.ticketmaster.categories import (
    DEFAULT_CATEGORY,
    infer_categories,
    reset_unmapped,
    unmapped_segments,
)
from pipeline.sources.ticketmaster.fetch import DeepPagingLimitExceeded, fetch_raw
from pipeline.sources.ticketmaster.normalize import normalize

NOW = datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)


def raw_event(**overrides):
    base = {
        "id": "vv1AaBbCc",
        "name": "Of Montreal w/ Sloppy Jane",
        "test": False,
        "url": "https://www.ticketmaster.com/event/vv1AaBbCc",
        "info": "Doors at 7pm.",
        "images": [
            {"url": "https://img/small.jpg", "ratio": "16_9", "width": 640},
            {"url": "https://img/large.jpg", "ratio": "16_9", "width": 2048},
            {"url": "https://img/huge-wrong-ratio.jpg", "ratio": "3_2", "width": 4096},
        ],
        "dates": {
            "start": {"dateTime": "2026-09-15T03:00:00Z"},
            "timezone": "America/Los_Angeles",
            "status": {"code": "onsale"},
        },
        "classifications": [
            {"primary": True, "segment": {"name": "Music"}, "genre": {"name": "Rock"}},
        ],
        "priceRanges": [{"type": "standard", "currency": "USD", "min": 25.0, "max": 45.0}],
        "promoter": {"name": "Mississippi Studios"},
        "_embedded": {
            "venues": [
                {
                    "name": "Wonder Ballroom",
                    "address": {"line1": "128 NE Russell St"},
                    "city": {"name": "Portland"},
                    "location": {"latitude": "45.5432", "longitude": "-122.6635"},
                }
            ]
        },
    }
    base.update(overrides)
    return base


class TestNormalize:
    def test_happy_path(self):
        events, counters = normalize([raw_event()], now=NOW)
        assert len(events) == 1
        event = events[0]
        assert event.id == "ticketmaster:vv1AaBbCc"
        assert event.venue.name == "Wonder Ballroom"
        assert event.organizer == "Mississippi Studios"
        assert not any(counters.as_dict().values())

    def test_start_time_converts_to_the_events_local_zone(self):
        # 03:00 UTC is the previous evening in Portland. Rendering the UTC hour would
        # show a 3am show that is really an 8pm one.
        events, _ = normalize([raw_event()], now=NOW)
        assert events[0].start_at.isoformat() == "2026-09-14T20:00:00-07:00"

    def test_missing_timezone_still_resolves_to_pacific(self):
        # `dates.timezone` is absent on ~37% of live Portland results. Leaving those
        # in UTC keeps the instant right but serializes an evening show onto the next
        # calendar day, which misfiles it for anything grouping by date string.
        raw = raw_event(dates={"start": {"dateTime": "2026-09-15T03:00:00Z"}, "status": {"code": "onsale"}})
        events, _ = normalize([raw], now=NOW)
        assert events[0].start_at.isoformat() == "2026-09-14T20:00:00-07:00"
        assert events[0].start_at.date().isoformat() == "2026-09-14"

    def test_events_declaring_a_non_pacific_timezone_are_dropped(self):
        # Live data has "Life Surge Tampa" and friends tagged to the Oregon Convention
        # Center with Eastern timezones. Either the venue or the time is wrong upstream
        # and there is no telling which, so the event cannot be trusted.
        raw = raw_event(
            name="Life Surge Tampa",
            dates={
                "start": {"dateTime": "2026-12-05T13:30:00Z"},
                "timezone": "America/New_York",
                "status": {"code": "onsale"},
            },
        )
        events, counters = normalize([raw], now=NOW)
        assert events == []
        assert counters.wrong_region == 1

    def test_a_bogus_timezone_string_is_also_treated_as_foreign(self):
        raw = raw_event(
            dates={"start": {"dateTime": "2026-09-15T03:00:00Z"}, "timezone": "Mars/Olympus", "status": {"code": "onsale"}}
        )
        events, counters = normalize([raw], now=NOW)
        assert events == []
        assert counters.wrong_region == 1

    def test_cancelled_events_are_dropped(self):
        raw = raw_event(dates={"start": {"dateTime": "2026-09-15T03:00:00Z"}, "status": {"code": "cancelled"}})
        events, counters = normalize([raw], now=NOW)
        assert events == []
        assert counters.cancelled == 1

    def test_offsale_events_are_kept(self):
        # Sold out is still worth showing; it is a real event that is happening.
        raw = raw_event(dates={"start": {"dateTime": "2026-09-15T03:00:00Z"}, "status": {"code": "offsale"}})
        events, _ = normalize([raw], now=NOW)
        assert len(events) == 1

    def test_test_events_are_dropped(self):
        events, counters = normalize([raw_event(test=True)], now=NOW)
        assert events == []
        assert counters.test_event == 1

    @pytest.mark.parametrize("flag", ["timeTBA", "noSpecificTime"])
    def test_placeholder_times_are_dropped(self, flag):
        raw = raw_event(
            dates={"start": {"dateTime": "2026-09-15T03:00:00Z", flag: True}, "status": {"code": "onsale"}}
        )
        events, counters = normalize([raw], now=NOW)
        assert events == []
        assert counters.time_tba == 1

    @pytest.mark.parametrize("flag", ["dateTBD", "dateTBA"])
    def test_placeholder_dates_are_dropped(self, flag):
        raw = raw_event(
            dates={"start": {"dateTime": "2026-09-15T03:00:00Z", flag: True}, "status": {"code": "onsale"}}
        )
        events, counters = normalize([raw], now=NOW)
        assert events == []
        assert counters.no_start_time == 1

    def test_coordinates_arrive_as_strings(self):
        events, _ = normalize([raw_event()], now=NOW)
        assert events[0].venue.latitude == pytest.approx(45.5432)

    def test_largest_sixteen_by_nine_image_wins_over_a_bigger_wrong_ratio(self):
        events, _ = normalize([raw_event()], now=NOW)
        assert events[0].image_url == "https://img/large.jpg"

    def test_missing_price_is_unknown_not_free(self):
        events, _ = normalize([raw_event(priceRanges=None)], now=NOW)
        assert events[0].price == Price.unknown()
        assert events[0].price.is_free is False

    def test_zero_price_range_is_free(self):
        raw = raw_event(priceRanges=[{"type": "standard", "currency": "USD", "min": 0, "max": 0}])
        events, _ = normalize([raw], now=NOW)
        assert events[0].price.is_free is True

    def test_price_range_is_carried_through(self):
        events, _ = normalize([raw_event()], now=NOW)
        assert (events[0].price.min, events[0].price.max) == (25.0, 45.0)

    def test_missing_venue_is_tolerated(self):
        events, _ = normalize([raw_event(_embedded={})], now=NOW)
        assert events[0].venue is None

    def test_output_validates_against_the_schema(self):
        events, _ = normalize([raw_event()], now=NOW)
        validate_per_source(build_per_source_feed("ticketmaster", events, generated_at=NOW))


class TestCategories:
    def setup_method(self):
        reset_unmapped()

    def test_segments_map(self):
        assert infer_categories("Music", "Rock") == (Category.MUSIC,)
        assert infer_categories("Sports", "Soccer") == (Category.SPORTS,)
        assert infer_categories("Arts & Theatre", "Theatre") == (Category.ARTS,)

    def test_undefined_segment_maps_to_music(self):
        # 7% of Portland's events, all independent music venues (Dante's, Holocene,
        # Wonder Ballroom) with no genre at all.
        assert infer_categories("Undefined", None) == (Category.MUSIC,)

    def test_genre_refines_its_segment_when_more_precise(self):
        assert infer_categories("Miscellaneous", "Community/Civic") == (Category.CIVIC,)
        assert infer_categories("Arts & Theatre", "Ice Shows") == (Category.FAMILY,)

    def test_family_genre_under_film_is_not_the_family_segment(self):
        # The genre "Family" under Film means family movies, not a family event.
        assert infer_categories("Film", "Family") == (Category.FILM,)

    def test_unknown_genre_falls_back_to_its_segment_without_flagging_a_gap(self):
        assert infer_categories("Music", "Throat Singing") == (Category.MUSIC,)
        assert unmapped_segments() == []

    def test_unknown_segment_falls_back_and_is_flagged(self):
        assert infer_categories("Holography", "Lasers") == (DEFAULT_CATEGORY,)
        assert unmapped_segments() == ["holography"]

    def test_missing_classification_falls_back(self):
        assert infer_categories(None, None) == (DEFAULT_CATEGORY,)


class TestDeepPagingGuard:
    """Truncation at the 1000th item is silent, so the guard is the only thing
    standing between a busy Portland and a quietly incomplete feed."""

    @responses.activate
    def test_aborts_when_results_exceed_the_guard(self):
        responses.add(
            responses.GET,
            config.EVENTS_URL,
            json={"page": {"totalElements": 1500, "totalPages": 8}, "_embedded": {"events": []}},
            status=200,
        )
        with pytest.raises(DeepPagingLimitExceeded, match="1500 events match"):
            fetch_raw("fake-key", now=NOW, session=requests.Session())

    @responses.activate
    def test_proceeds_when_below_the_guard(self):
        responses.add(
            responses.GET,
            config.EVENTS_URL,
            json={"page": {"totalElements": 2, "totalPages": 1}, "_embedded": {"events": [raw_event()]}},
            status=200,
        )
        collected, stats = fetch_raw("fake-key", now=NOW, session=requests.Session())
        assert len(collected) == 1
        assert stats["total_elements"] == 2

    @responses.activate
    def test_no_segment_filter_is_sent(self):
        # An exhaustive six-segment allow-list measurably returns fewer events than
        # none, because of the undocumented Undefined segment.
        responses.add(
            responses.GET,
            config.EVENTS_URL,
            json={"page": {"totalElements": 1, "totalPages": 1}, "_embedded": {"events": []}},
            status=200,
        )
        fetch_raw("fake-key", now=NOW, session=requests.Session())
        assert "segmentName" not in responses.calls[0].request.url
