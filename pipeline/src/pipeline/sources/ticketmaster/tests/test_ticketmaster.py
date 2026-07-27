"""Tests for the Ticketmaster source.

Cases come from quirks observed in live Portland responses: an undocumented
`Undefined` segment, cancelled events still present in results, placeholder times,
string coordinates, and price data missing on most events.
"""

from __future__ import annotations

import random
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

    def test_picks_the_smallest_image_that_is_still_big_enough(self):
        # Not the largest: a 2426px JPEG decodes to ~13 MB, and a feed of several
        # hundred of those gets the app killed for exceeding its memory limit.
        raw = raw_event(
            images=[
                {"url": "https://img/tiny.jpg", "ratio": "16_9", "width": 205},
                {"url": "https://img/right.jpg", "ratio": "16_9", "width": 1136},
                {"url": "https://img/huge.jpg", "ratio": "16_9", "width": 2426},
            ]
        )
        events, _ = normalize([raw], now=NOW)
        assert events[0].image_url == "https://img/right.jpg"

    def test_prefers_sixteen_by_nine_over_a_bigger_wrong_ratio(self):
        events, _ = normalize([raw_event()], now=NOW)
        assert events[0].image_url == "https://img/large.jpg"

    def test_falls_back_to_the_largest_when_none_are_big_enough(self):
        raw = raw_event(
            images=[
                {"url": "https://img/a.jpg", "ratio": "16_9", "width": 100},
                {"url": "https://img/b.jpg", "ratio": "16_9", "width": 640},
            ]
        )
        events, _ = normalize([raw], now=NOW)
        assert events[0].image_url == "https://img/b.jpg"

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


def ladder(asset: str = "abc_106541") -> list[dict]:
    """A real Ticketmaster rendition ladder, verbatim down to the arrival order.

    The order is the point: live responses do not list these by size, and they mix in
    ratio-less third-party URLs, so anything that tie-breaks on position is exposed.
    """
    base = f"https://s1.ticketm.net/dam/c/677/{asset}"
    return [
        {"url": f"{base}_RETINA_PORTRAIT_3_2.jpg", "ratio": "3_2", "width": 640},
        {"url": f"{base}_EVENT_DETAIL_PAGE_16_9.jpg", "ratio": "16_9", "width": 205},
        {"url": f"{base}_TABLET_LANDSCAPE_3_2.jpg", "ratio": "3_2", "width": 1024},
        {"url": "https://i.ticketweb.com/i/00/13/57/94/53_Edp.jpg?v=3", "width": 341},
        {"url": f"{base}_CUSTOM.jpg", "ratio": "4_3", "width": 305},
        {"url": f"{base}_RETINA_PORTRAIT_16_9.jpg", "ratio": "16_9", "width": 640},
        {"url": f"{base}_RECOMENDATION_16_9.jpg", "ratio": "16_9", "width": 100},
        {"url": f"{base}_RETINA_LANDSCAPE_16_9.jpg", "ratio": "16_9", "width": 1136},
        {"url": f"{base}_TABLET_LANDSCAPE_16_9.jpg", "ratio": "16_9", "width": 1024},
        {"url": f"{base}_ARTIST_PAGE_3_2.jpg", "ratio": "3_2", "width": 305},
        {"url": f"{base}_TABLET_LANDSCAPE_LARGE_16_9.jpg", "ratio": "16_9", "width": 2048},
    ]


CANONICAL = "https://s1.ticketm.net/dam/c/677/abc_106541_RETINA_LANDSCAPE_16_9.jpg"


class TestImageSelectionIsStable:
    """A changed image URL costs every client a re-download of artwork it already has.

    `AsyncImage` and the shared `URLSession` cache both key on the URL, so re-picking
    a different rendition of identical artwork is a guaranteed cache miss across the
    whole feed. Selection therefore has to depend on the rendition's name and nothing
    else about how the response happened to arrive.
    """

    def test_takes_the_canonical_rendition_from_a_full_ladder(self):
        events, _ = normalize([raw_event(images=ladder())], now=NOW)
        assert events[0].image_url == CANONICAL

    def test_shuffling_the_array_cannot_change_the_choice(self):
        # Unseeded on purpose. The property is that order cannot matter at all, so a
        # fixed seed would only ever prove it for one arrangement.
        images = ladder()
        picked = set()
        for _ in range(200):
            shuffled = images[:]
            random.shuffle(shuffled)
            events, _ = normalize([raw_event(images=shuffled)], now=NOW)
            picked.add(events[0].image_url)
        assert picked == {CANONICAL}

    @pytest.mark.parametrize("dropped", [(2048,), (1024, 2048), (100, 205, 640, 1024, 2048), (305, 341, 640)])
    def test_a_partial_ladder_still_yields_the_canonical_rendition(self, dropped):
        # Indifference to the rest of the ladder is the property being pinned. A width
        # rule agrees on all of these by coincidence, since 1136 happens to be its
        # smallest qualifying entry either way; what it cannot survive is a size
        # appearing near the bar, which the next test covers.
        partial = [i for i in ladder() if i["width"] not in dropped]
        events, _ = normalize([raw_event(images=partial)], now=NOW)
        assert events[0].image_url == CANONICAL

    def test_only_the_canonical_entry_left_is_still_the_canonical_entry(self):
        single = [i for i in ladder() if i["url"] == CANONICAL]
        events, _ = normalize([raw_event(images=single)], now=NOW)
        assert events[0].image_url == CANONICAL

    def test_the_canonical_rendition_beats_a_smaller_qualifying_sibling(self):
        # The case that separates the two rules. A width rule takes this 1120 px
        # entry, so one new rendition landing between the bar and 1136 would change
        # every event's URL at once — the whole feed re-downloading for nothing.
        images = ladder() + [
            {"url": "https://s1.ticketm.net/dam/c/677/abc_106541_ODD_16_9.jpg", "ratio": "16_9", "width": 1120}
        ]
        events, _ = normalize([raw_event(images=images)], now=NOW)
        assert events[0].image_url == CANONICAL

    def test_never_falls_through_to_source_when_the_canonical_one_exists(self):
        # _SOURCE is the full-resolution original, up to 3200 px and ~13 MB decoded.
        # It is the single worst thing this function can return.
        images = ladder() + [
            {"url": "https://s1.ticketm.net/dam/a/75d/9663323b_SOURCE", "ratio": "16_9", "width": 3200}
        ]
        random.shuffle(images)
        events, _ = normalize([raw_event(images=images)], now=NOW)
        assert events[0].image_url == CANONICAL

    def test_without_a_canonical_rendition_equal_widths_still_break_deterministically(self):
        # The fallback path. Two entries at the same qualifying width used to resolve
        # to whichever the response listed first.
        images = [
            {"url": "https://img/zebra.jpg", "ratio": "16_9", "width": 1200},
            {"url": "https://img/aardvark.jpg", "ratio": "16_9", "width": 1200},
        ]
        picked = set()
        for _ in range(50):
            random.shuffle(images)
            events, _ = normalize([raw_event(images=images)], now=NOW)
            picked.add(events[0].image_url)
        assert picked == {"https://img/aardvark.jpg"}

    def test_the_undersized_fallback_is_deterministic_too(self):
        images = [
            {"url": "https://img/zebra.jpg", "ratio": "16_9", "width": 640},
            {"url": "https://img/aardvark.jpg", "ratio": "16_9", "width": 640},
        ]
        picked = set()
        for _ in range(50):
            random.shuffle(images)
            events, _ = normalize([raw_event(images=images)], now=NOW)
            picked.add(events[0].image_url)
        assert picked == {"https://img/zebra.jpg"}

    def test_a_ratio_less_third_party_image_is_not_mistaken_for_the_ladder(self):
        events, _ = normalize([raw_event(images=ladder())], now=NOW)
        assert "ticketweb" not in events[0].image_url

    def test_no_images_at_all_is_tolerated(self):
        events, _ = normalize([raw_event(images=[])], now=NOW)
        assert events[0].image_url is None


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
