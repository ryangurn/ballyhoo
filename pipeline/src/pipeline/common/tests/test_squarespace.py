"""Tests for the shared Squarespace event-list parser.

The two details that silently corrupt a parse: U+202F between the clock and the
meridiem, and a multiday item carrying two `time.event-date` elements.
"""

from __future__ import annotations

from datetime import time

import pytest

from pipeline.common.squarespace import normalize_spaces, parse_clock, parse_event_list

NNBSP = "\u202f"

HTML = f"""
<div class="eventlist">
  <article class="eventlist-event eventlist-event--upcoming">
    <img data-src="https://images.squarespace-cdn.com/content/v1/abc/logo.png?format=500w" />
    <h1 class="eventlist-title">
      <a class="eventlist-title-link" href="/events/orenco-station-sffap-3p8ad">Orenco Station</a>
    </h1>
    <ul class="eventlist-meta">
      <li><time class="event-date" datetime="2026-10-11">Sunday, October 11, 2026</time></li>
      <li>
        <time class="event-time-localized-start" datetime="2026-10-11">10:00{NNBSP}AM</time>
        <time class="event-time-localized-end" datetime="2026-10-11">2:00{NNBSP}PM</time>
      </li>
    </ul>
  </article>
  <article class="eventlist-event eventlist-event--multiday">
    <h1 class="eventlist-title">
      <a class="eventlist-title-link" href="/events/market-week">Market Week</a>
    </h1>
    <ul class="eventlist-meta">
      <li>
        <time class="event-date" datetime="2026-08-02">Sun, Aug 2, 2026</time>
        <time class="event-date" datetime="2026-08-08">Sat, Aug 8, 2026</time>
      </li>
    </ul>
  </article>
  <article class="eventlist-event"><h1 class="eventlist-title">No link, so no item</h1></article>
</div>
"""


def items():
    return parse_event_list(HTML, base_url="https://hillsboromarkets.org/")


class TestParsing:
    def test_reads_items_with_a_link_and_a_date(self):
        assert [i.title for i in items()] == ["Orenco Station", "Market Week"]

    def test_pulls_the_fields(self):
        item = items()[0]
        assert item.slug == "orenco-station-sffap-3p8ad"
        assert item.start_date == "2026-10-11"
        assert item.end_date is None
        assert item.url == "https://hillsboromarkets.org/events/orenco-station-sffap-3p8ad"
        assert item.image_url == "https://images.squarespace-cdn.com/content/v1/abc/logo.png"

    def test_a_multiday_item_starts_on_its_first_date(self):
        week = items()[1]
        assert (week.start_date, week.end_date) == ("2026-08-02", "2026-08-08")


class TestClock:
    def test_reads_a_time_written_with_a_narrow_no_break_space(self):
        assert parse_clock(items()[0].start_clock) == time(10, 0)
        assert parse_clock(normalize_spaces(f"2:00{NNBSP}PM")) == time(14, 0)

    @pytest.mark.parametrize(
        "text,expected",
        [("12:00 PM", time(12, 0)), ("12:00 AM", time(0, 0)), ("4:30 pm", time(16, 30)), ("9 AM", time(9, 0))],
    )
    def test_parses_the_meridiem_forms(self, text, expected):
        assert parse_clock(text) == expected

    @pytest.mark.parametrize("text", [None, "", "noon", "13:00 PM", "9:75 AM"])
    def test_rejects_what_it_cannot_read(self, text):
        assert parse_clock(text) is None
