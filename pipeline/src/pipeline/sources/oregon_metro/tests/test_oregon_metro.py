"""Tests for the Oregon Metro source.

The fixture is trimmed from a real page. The timezone case is the important one:
Metro's `datetime` attribute carries no offset but is UTC, and reading it as local
time would shift every event by seven hours.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.validate import validate_per_source
from pipeline.sources.oregon_metro.fetch import parse_page
from pipeline.sources.oregon_metro.normalize import infer_category, normalize

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)

PAGE = """
<ul>
  <li><div class="eventinstance-list event-teaser">
    <div class="event-teaser__content">
      <div class="event-teaser__eyebrow eyebrow">Nature activity</div>
      <h3 class="event-teaser__title h5">
        <a href="/events/life-jacket-giveaway-2026-07-30">Life jacket giveaway</a>
      </h3>
    </div>
    <div class="event-teaser__datetime">
      <time datetime="2026-07-30T18:00:00">July 30, 2026</time>
      <time datetime="2026-07-30T21:00:00">11 a.m. to 2 p.m.</time>
    </div>
    <div class="event-teaser__meta">
      <div class="event-teaser__location">Oxbow Regional Park</div>
    </div>
  </div></li>
  <li><div class="eventinstance-list event-teaser">
    <div class="event-teaser__content">
      <div class="event-teaser__eyebrow eyebrow">Meetings</div>
      <h3 class="event-teaser__title h5">
        <a href="/events/metro-council-work-session-2026-07-28">Metro Council work session</a>
      </h3>
    </div>
    <div class="event-teaser__datetime">
      <time datetime="2026-07-28T17:00:00">July 28, 2026</time>
      <time datetime="2026-07-28T17:00:00">10 a.m. to 1 p.m.</time>
    </div>
    <div class="event-teaser__meta"></div>
  </div></li>
</ul>
"""


class TestParsing:
    def test_extracts_both_events(self):
        assert len(parse_page(PAGE)) == 2

    def test_pulls_every_field(self):
        first = parse_page(PAGE)[0]
        assert first.title == "Life jacket giveaway"
        assert first.slug == "life-jacket-giveaway-2026-07-30"
        assert first.category == "Nature activity"
        assert first.location == "Oxbow Regional Park"
        assert first.url == "https://www.oregonmetro.gov/events/life-jacket-giveaway-2026-07-30"

    def test_a_repeated_timestamp_is_not_an_end_time(self):
        # Metro renders the same instant twice when it has no distinct end.
        assert parse_page(PAGE)[1].end_raw is None

    def test_a_distinct_second_timestamp_is_an_end_time(self):
        assert parse_page(PAGE)[0].end_raw == "2026-07-30T21:00:00"

    def test_markup_without_events_yields_nothing(self):
        assert parse_page("<html><body><p>nothing here</p></body></html>") == []


class TestNormalize:
    def test_offsetless_timestamps_are_utc_not_local(self):
        # 18:00 in the attribute renders on the page as 11 a.m., so it is UTC.
        # Treating it as local would put this event at 6pm.
        events, _ = normalize(parse_page(PAGE), now=NOW)
        life_jacket = next(e for e in events if "Life jacket" in e.title)
        assert life_jacket.start_at.isoformat() == "2026-07-30T11:00:00-07:00"

    def test_id_is_prefixed_and_derived_from_the_dated_slug(self):
        # The slug carries the date, which keeps recurring meetings distinct.
        events, _ = normalize(parse_page(PAGE), now=NOW)
        assert events[0].id.startswith("oregon_metro:")
        assert "2026-07-28" in next(e.id for e in events if "Council" in e.title)

    def test_known_venues_get_coordinates(self):
        events, _ = normalize(parse_page(PAGE), now=NOW)
        oxbow = next(e for e in events if e.venue and e.venue.name == "Oxbow Regional Park")
        assert oxbow.venue.latitude == pytest.approx(45.495, abs=0.01)

    def test_a_missing_location_is_not_an_error(self):
        # Council meetings are frequently virtual and list no venue.
        events, _ = normalize(parse_page(PAGE), now=NOW)
        assert next(e for e in events if "Council" in e.title).venue is None

    def test_price_is_unknown_never_free(self):
        # Most Metro programming is free, but the listing does not say so.
        events, _ = normalize(parse_page(PAGE), now=NOW)
        assert all(e.price == Price.unknown() for e in events)

    def test_events_are_sorted(self):
        events, _ = normalize(parse_page(PAGE), now=NOW)
        assert [e.start_at for e in events] == sorted(e.start_at for e in events)

    def test_output_validates(self):
        events, _ = normalize(parse_page(PAGE), now=NOW)
        validate_per_source(build_per_source_feed("oregon_metro", events, generated_at=NOW))


class TestCategories:
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Meetings", Category.CIVIC),
            ("Nature activity", Category.OUTDOORS),
            ("Community events", Category.COMMUNITY),
            ("Opportunity", Category.COMMUNITY),
        ],
    )
    def test_metro_taxonomy_maps(self, label, expected):
        assert infer_category(label) == (expected,)

    def test_unknown_label_falls_back_rather_than_dropping(self):
        assert infer_category("Some New Programme") == (Category.CIVIC,)
        assert infer_category(None) == (Category.CIVIC,)
