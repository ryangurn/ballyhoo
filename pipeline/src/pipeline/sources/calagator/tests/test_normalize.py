"""Tests for the Calagator normalizer.

Cases are drawn from real quirks observed in live Calagator responses, not invented:
string coordinates, empty-string coordinates, `venue.title` rather than `venue.name`,
`duplicate_of_id` shadow rows, and descriptions long enough to poison keyword matching.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pipeline.common.io import build_per_source_feed, event_to_dict
from pipeline.common.models import Category, Price
from pipeline.common.validate import SchemaValidationError, validate_per_source
from pipeline.sources.calagator.categories import DEFAULT_CATEGORY, infer_categories
from pipeline.sources.calagator.normalize import normalize

NOW = datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)


def raw_event(**overrides):
    base = {
        "id": 1250482638,
        "title": "Portland Python User Group Meetup",
        "description": "Monthly meetup.",
        "start_time": "2026-08-15T18:30:00.000-07:00",
        "end_time": "2026-08-15T20:30:00.000-07:00",
        "url": "https://example.org/event",
        "duplicate_of_id": None,
        "venue_details": None,
        "venue": {
            "title": "Jupiter Hotel",
            "street_address": "800 E. Burnside",
            "locality": "Portland",
            "latitude": "45.5226",
            "longitude": "-122.657",
        },
    }
    base.update(overrides)
    return base


class TestNormalize:
    def test_happy_path(self):
        events, counters = normalize([raw_event()], now=NOW)
        assert len(events) == 1
        event = events[0]
        assert event.id == "calagator:1250482638"
        assert event.title == "Portland Python User Group Meetup"
        assert event.venue.name == "Jupiter Hotel"
        assert event.venue.city == "Portland"
        assert counters.as_dict() == {
            "dropped_duplicate": 0,
            "dropped_no_start_time": 0,
            "dropped_unparseable_time": 0,
            "dropped_stale": 0,
            "dropped_no_title": 0,
        }

    def test_id_is_prefixed_and_stable(self):
        first, _ = normalize([raw_event()], now=NOW)
        second, _ = normalize([raw_event()], now=NOW + timedelta(days=3))
        assert first[0].id == second[0].id == "calagator:1250482638"

    def test_coordinates_arrive_as_strings_and_become_floats(self):
        events, _ = normalize([raw_event()], now=NOW)
        assert events[0].venue.latitude == pytest.approx(45.5226)
        assert events[0].venue.longitude == pytest.approx(-122.657)

    @pytest.mark.parametrize("bad", ["", None, "not-a-number"])
    def test_unusable_coordinates_become_none_without_dropping_the_venue(self, bad):
        events, _ = normalize([raw_event(venue={"title": "Roseline Cafe", "latitude": bad, "longitude": bad})], now=NOW)
        assert events[0].venue.name == "Roseline Cafe"
        assert events[0].venue.latitude is None

    def test_duplicate_rows_are_dropped(self):
        events, counters = normalize([raw_event(duplicate_of_id=999)], now=NOW)
        assert events == []
        assert counters.duplicate == 1

    def test_missing_start_time_is_dropped(self):
        events, counters = normalize([raw_event(start_time=None)], now=NOW)
        assert events == []
        assert counters.no_start_time == 1

    def test_unparseable_start_time_is_dropped_not_defaulted(self):
        events, counters = normalize([raw_event(start_time="soon-ish")], now=NOW)
        assert events == []
        assert counters.unparseable_time == 1

    def test_long_past_events_are_dropped(self):
        events, counters = normalize([raw_event(start_time="2026-01-01T18:30:00.000-08:00")], now=NOW)
        assert events == []
        assert counters.stale == 1

    def test_recently_past_events_are_kept_within_the_grace_window(self):
        events, _ = normalize([raw_event(start_time="2026-07-25T18:30:00.000-07:00")], now=NOW)
        assert len(events) == 1

    def test_bad_end_time_does_not_discard_the_event(self):
        events, _ = normalize([raw_event(end_time="whenever")], now=NOW)
        assert len(events) == 1
        assert events[0].end_at is None

    def test_missing_venue_falls_back_to_venue_details(self):
        events, _ = normalize([raw_event(venue=None, venue_details="Somewhere on the eastside")], now=NOW)
        assert events[0].venue.address == "Somewhere on the eastside"

    def test_no_venue_at_all_is_allowed(self):
        events, _ = normalize([raw_event(venue=None, venue_details=None)], now=NOW)
        assert events[0].venue is None

    def test_price_is_unknown_never_free(self):
        # Calagator has no price field. Claiming free would be a fabrication, and
        # showing "Free" on a paid event is the costlier direction to be wrong in.
        events, _ = normalize([raw_event()], now=NOW)
        assert events[0].price == Price.unknown()
        assert events[0].price.is_free is False

    def test_events_are_sorted_chronologically(self):
        later = raw_event(id=2, start_time="2026-09-01T10:00:00.000-07:00")
        earlier = raw_event(id=1, start_time="2026-08-01T10:00:00.000-07:00")
        events, _ = normalize([later, earlier], now=NOW)
        assert [e.id for e in events] == ["calagator:1", "calagator:2"]


class TestCategoryInference:
    def test_defaults_to_tech_for_the_typical_meetup(self):
        assert infer_categories("Portland Drupal User Group") == (DEFAULT_CATEGORY,)

    def test_title_keywords_are_honored(self):
        assert infer_categories("Beginner Yoga in the Park") == (Category.WELLNESS,)
        assert infer_categories("Montavilla Farmers Market") == (Category.MARKET,)

    def test_description_noise_does_not_leak_into_the_category(self):
        # Both of these were real misclassifications when descriptions were matched:
        # the Drupal group meets at a food cart pod, and Code & Coffee mentions
        # grabbing lunch nearby. Neither is a food event.
        noisy = "Address: Hawthorne Asylum food cart pod, Portland. We usually grab lunch at nearby food carts."
        assert infer_categories("Portland Drupal User Group", noisy) == (DEFAULT_CATEGORY,)
        assert infer_categories("Code & Coffee @ Roseline Café", noisy) == (DEFAULT_CATEGORY,)

    def test_exactly_one_category_is_returned(self):
        # "Comedy" and "open mic" both match; scattering the event across chips is worse.
        assert len(infer_categories("Comedy Open Mic Night")) == 1


class TestSchemaConformance:
    def test_normalized_output_validates(self):
        events, _ = normalize([raw_event()], now=NOW)
        validate_per_source(build_per_source_feed("calagator", events, generated_at=NOW))

    def test_validation_actually_rejects_a_bad_payload(self):
        events, _ = normalize([raw_event()], now=NOW)
        feed = build_per_source_feed("calagator", events, generated_at=NOW)
        del feed["events"][0]["title"]
        with pytest.raises(SchemaValidationError):
            validate_per_source(feed)

    def test_serialized_timestamps_keep_an_explicit_offset(self):
        events, _ = normalize([raw_event()], now=NOW)
        payload = event_to_dict(events[0])
        assert payload["start_at"] == "2026-08-15T18:30:00-07:00"
