"""Tests for the Portland Parks Summer Free For All source.

The schedule is a hand-maintained HTML table, so the tests focus on the two things
most likely to go wrong: a column reorder upstream, and assembling a date from three
places (a month/day cell, a time cell, and a year in a heading).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category
from pipeline.common.validate import validate_per_source
from pipeline.sources.portland_parks.fetch import ScheduleLayoutChanged, parse_schedule
from pipeline.sources.portland_parks.normalize import infer_categories, normalize, parse_when

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

PAGE = """
<html><body>
<h2>2026 Schedule of Events</h2>
<table>
  <tr><th>Date/Time</th><th>Type of Event</th><th>Cultural Event</th><th>Location</th></tr>
  <tr>
    <th>July 24<br>7:30pm</th>
    <td>Movie</td>
    <td><em><strong>Kung Fu Panda 4</strong></em> (2024) PG</td>
    <td><a href="https://www.portland.gov/parks/brentwood-park">Brentwood Park</a></td>
  </tr>
  <tr>
    <th>August 1<br>6:30pm</th>
    <td>Concert</td>
    <td><strong>Iron Prophecy</strong> - Classic rock covers</td>
    <td><a href="https://www.portland.gov/parks/columbia-park">Columbia Park</a></td>
  </tr>
</table>
</body></html>
"""


class TestParsing:
    def test_reads_both_rows(self):
        assert len(parse_schedule(PAGE, fallback_year=2000)) == 2

    def test_pulls_each_column(self):
        first = parse_schedule(PAGE, fallback_year=2000)[0]
        assert first.date_text == "July 24"
        assert first.time_text == "7:30pm"
        assert first.event_type == "Movie"
        assert first.title == "Kung Fu Panda 4"
        assert first.venue == "Brentwood Park"

    def test_title_prefers_the_bold_name_over_the_whole_cell(self):
        # The cell also carries a year, rating and description.
        first = parse_schedule(PAGE, fallback_year=2000)[0]
        assert first.title == "Kung Fu Panda 4"
        assert "(2024) PG" in first.detail

    def test_year_comes_from_the_heading_not_the_fallback(self):
        assert parse_schedule(PAGE, fallback_year=2000)[0].year == 2026

    def test_year_falls_back_when_the_heading_is_missing(self):
        assert parse_schedule(PAGE.replace("2026 Schedule of Events", "Schedule"), fallback_year=2031)[0].year == 2031

    def test_a_reordered_table_raises_rather_than_guessing(self):
        # Reading the wrong column would put a venue in the title and still look
        # plausible, so this has to fail loudly.
        swapped = PAGE.replace(
            "<th>Date/Time</th><th>Type of Event</th>",
            "<th>Type of Event</th><th>Date/Time</th>",
        )
        with pytest.raises(ScheduleLayoutChanged):
            parse_schedule(swapped, fallback_year=2026)

    def test_a_missing_table_is_empty_not_an_error(self):
        # The programme is seasonal; out of season the page carries no schedule.
        assert parse_schedule("<html><body><p>See you next summer</p></body></html>", fallback_year=2026) == []


class TestDateAssembly:
    @pytest.mark.parametrize(
        "date_text,time_text,expected",
        [
            ("July 24", "7:30pm", "2026-07-24T19:30:00-07:00"),
            ("August 1", "6:30pm", "2026-08-01T18:30:00-07:00"),
            ("July 10", "10am", "2026-07-10T10:00:00-07:00"),
            ("July 10", "12pm", "2026-07-10T12:00:00-07:00"),
            ("July 10", "12am", "2026-07-10T00:00:00-07:00"),
        ],
    )
    def test_assembles_portland_local_time(self, date_text, time_text, expected):
        assert parse_when(date_text, time_text, 2026).isoformat() == expected

    def test_an_unreadable_time_raises(self):
        with pytest.raises(ValueError):
            parse_when("July 24", "sundown", 2026)


class TestNormalize:
    def test_everything_is_free(self):
        # Free is the entire premise of the programme, so this is the one source
        # that can assert it rather than leaving price unknown.
        events, _ = normalize(parse_schedule(PAGE, fallback_year=2026), now=NOW)
        assert all(e.price.is_free for e in events)

    def test_known_parks_get_coordinates(self):
        events, _ = normalize(parse_schedule(PAGE, fallback_year=2026), now=NOW)
        assert all(e.venue and e.venue.latitude is not None for e in events)

    def test_identifiers_are_stable_and_distinguish_occurrences(self):
        first = normalize(parse_schedule(PAGE, fallback_year=2026), now=NOW)[0]
        second = normalize(parse_schedule(PAGE, fallback_year=2026), now=NOW)[0]
        assert [e.id for e in first] == [e.id for e in second]
        assert len({e.id for e in first}) == len(first)
        assert all(e.id.startswith("portland_parks:") for e in first)

    def test_past_dates_are_dropped(self):
        _, counters = normalize(parse_schedule(PAGE, fallback_year=2026), now=datetime(2026, 12, 1, tzinfo=UTC))
        assert counters.stale == 2

    def test_output_validates(self):
        events, _ = normalize(parse_schedule(PAGE, fallback_year=2026), now=NOW)
        validate_per_source(build_per_source_feed("portland_parks", events, generated_at=NOW))


class TestCategories:
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Movie", Category.FILM),
            ("Concert", Category.MUSIC),
            ("Festival", Category.COMMUNITY),
            ("Special Event", Category.COMMUNITY),
        ],
    )
    def test_programme_types_map(self, label, expected):
        assert infer_categories(label) == (expected,)

    def test_an_unknown_type_falls_back(self):
        assert infer_categories("Puppet Slam") == (Category.COMMUNITY,)
        assert infer_categories(None) == (Category.COMMUNITY,)
