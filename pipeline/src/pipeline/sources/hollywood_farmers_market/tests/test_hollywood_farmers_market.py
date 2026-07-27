"""Tests for the Hollywood Farmers Market source.

The fixture is trimmed from the real Squarespace pages and keeps the two things that
would silently corrupt a parse: the narrow no-break space (U+202F) between the clock
and the meridiem, and a multiday item carrying two `time.event-date` elements.

The other half of these tests is the market-hours tripwire. This source invents dates
from a rule encoded off a sentence of prose, and the guard that stops it inventing
wrong ones is the check that the sentence has not changed.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.validate import validate_per_source
from pipeline.sources.hollywood_farmers_market import config
from pipeline.sources.hollywood_farmers_market.fetch import (
    normalize_spaces,
    parse_event_list,
    parse_market_hours,
)
from pipeline.sources.hollywood_farmers_market.normalize import (
    market_hours_are_unchanged,
    normalize,
    parse_clock,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)

# U+202F between the minutes and the meridiem, exactly as Squarespace emits it.
NNBSP = "\u202f"

MUSIC_HTML = f"""
<div class="eventlist">
  <article class="eventlist-event eventlist-event--upcoming eventlist-event--hasimg">
    <a class="eventlist-column-thumbnail" href="/music-schedule/tyler-waltner-quartet-2026">
      <img data-src="https://images.squarespace-cdn.com/content/v1/abc/photo.png?format=2500w" />
    </a>
    <h1 class="eventlist-title">
      <a class="eventlist-title-link" href="/music-schedule/tyler-waltner-quartet-2026">Tyler Waltner Quartet</a>
    </h1>
    <ul class="eventlist-meta">
      <li><time class="event-date" datetime="2026-08-01">Saturday, August 1, 2026</time></li>
      <li>
        <time class="event-time-localized-start" datetime="2026-08-01">10:00{NNBSP}AM</time>
        <time class="event-time-localized-end" datetime="2026-08-01">12:30{NNBSP}PM</time>
      </li>
    </ul>
    <div class="eventlist-excerpt"><p>4-piece jazz ensemble.</p></div>
  </article>
  <article class="eventlist-event eventlist-event--past">
    <h1 class="eventlist-title">
      <a class="eventlist-title-link" href="/music-schedule/dumpster-joe-oct25">Dumpster Joe</a>
    </h1>
    <ul class="eventlist-meta">
      <li><time class="event-date" datetime="2025-10-25">Saturday, October 25, 2025</time></li>
      <li><time class="event-time-localized-start" datetime="2025-10-25">10:00{NNBSP}AM</time></li>
    </ul>
  </article>
</div>
"""

EVENTS_HTML = f"""
<div class="eventlist">
  <article class="eventlist-event eventlist-event--upcoming eventlist-event--multiday">
    <h1 class="eventlist-title">
      <a class="eventlist-title-link" href="/event-schedule/national-farmers-market-week">National Farmers Market Week</a>
    </h1>
    <ul class="eventlist-meta">
      <li>
        <time class="event-date" datetime="2026-08-02">Sun, Aug 2, 2026</time>
        <time class="event-date" datetime="2026-08-08">Sat, Aug 8, 2026</time>
      </li>
    </ul>
  </article>
  <article class="eventlist-event eventlist-event--upcoming">
    <h1 class="eventlist-title">
      <a class="eventlist-title-link" href="/event-schedule/fundraiser-at-lucky-horseshoe-lounge-1">Fundraiser at Lucky Horseshoe Lounge!</a>
    </h1>
    <ul class="eventlist-meta">
      <li><time class="event-date" datetime="2026-08-09">Sun, Aug 9, 2026</time></li>
      <li>
        <time class="event-time-localized-start" datetime="2026-08-09">4:00{NNBSP}PM</time>
        <time class="event-time-localized-end" datetime="2026-08-09">10:00{NNBSP}PM</time>
      </li>
    </ul>
  </article>
</div>
"""

HOME_HTML = """
<html><body>
  <h3><em>MARKET HOURS</em></h3>
  <p>April-December 19th : Every Saturday 8am-1pm</p>
  <p>January-March: 2nd and 4th Saturdays 9am-1pm</p>
  <h3>MARKET MAP</h3>
  <p>To see who is at the Hollywood Farmers Market this week, click here.</p>
</body></html>
"""

HOURS = parse_market_hours(HOME_HTML)


def listings():
    return parse_event_list(MUSIC_HTML, collection="music-schedule", base_url=config.HOME_URL) + parse_event_list(
        EVENTS_HTML, collection="event-schedule", base_url=config.HOME_URL
    )


def normalized(hours_text=None):
    return normalize(listings(), hours_text=HOURS if hours_text is None else hours_text, now=NOW)


class TestClockParsing:
    def test_reads_a_time_written_with_a_narrow_no_break_space(self):
        # Squarespace emits U+202F, not a space. A %I:%M %p parse of the raw text
        # fails outright, so this is the difference between times and no times.
        assert parse_clock(normalize_spaces(f"10:00{NNBSP}AM")) == time(10, 0)

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("10:00 AM", time(10, 0)),
            ("12:30 PM", time(12, 30)),
            ("4:00 PM", time(16, 0)),
            ("12:00 AM", time(0, 0)),
            ("12:00 PM", time(12, 0)),
            ("8 AM", time(8, 0)),
        ],
    )
    def test_parses_the_meridiem_forms(self, text, expected):
        assert parse_clock(text) == expected

    @pytest.mark.parametrize("text", [None, "", "sometime", "25:00 AM", "10:75 AM"])
    def test_rejects_what_it_cannot_read(self, text):
        assert parse_clock(text) is None


class TestParsing:
    def test_reads_every_item(self):
        assert len(listings()) == 4

    def test_pulls_the_music_fields(self):
        item = listings()[0]
        assert item.title == "Tyler Waltner Quartet"
        assert item.slug == "tyler-waltner-quartet-2026"
        assert item.start_date == "2026-08-01"
        assert item.summary == "4-piece jazz ensemble."
        assert item.url == "https://www.hollywoodfarmersmarket.org/music-schedule/tyler-waltner-quartet-2026"

    def test_strips_the_squarespace_rendition_query_from_images(self):
        assert listings()[0].image_url == "https://images.squarespace-cdn.com/content/v1/abc/photo.png"

    def test_a_multiday_item_uses_its_first_date_as_the_start(self):
        # Two time.event-date elements. Taking the last would date the event to the
        # end of the run instead of its start.
        week = next(i for i in listings() if i.slug == "national-farmers-market-week")
        assert week.start_date == "2026-08-02"
        assert week.end_date == "2026-08-08"

    def test_a_single_day_item_has_no_end_date(self):
        assert listings()[0].end_date is None


class TestMarketHours:
    def test_reads_the_sentence_off_the_homepage(self):
        assert parse_market_hours(HOME_HTML) == config.EXPECTED_HOURS_TEXT

    def test_the_encoded_rules_match_what_the_site_says(self):
        assert market_hours_are_unchanged(parse_market_hours(HOME_HTML)) is True

    def test_changed_hours_are_detected(self):
        changed = parse_market_hours(HOME_HTML.replace("8am-1pm", "9am-2pm"))
        assert market_hours_are_unchanged(changed) is False

    def test_absent_hours_are_detected(self):
        assert market_hours_are_unchanged(None) is False
        assert parse_market_hours("<html><body>nothing here</body></html>") is None


class TestMarketDayExpansion:
    def test_market_days_are_generated(self):
        events, counters = normalized()
        assert counters.market_days_expanded > 0
        market_days = [e for e in events if e.title == config.MARKET_TITLE]
        assert market_days
        assert all(e.start_at.weekday() == config.SATURDAY for e in market_days)

    def test_expansion_is_bounded_by_the_window(self):
        events, _ = normalized()
        market_days = [e for e in events if e.title == config.MARKET_TITLE]
        latest = max(e.start_at for e in market_days)
        assert latest <= NOW + config.MARKET_EXPANSION_WINDOW + timedelta(days=1)
        # Seventeen-odd Saturdays, not five years of them.
        assert len(market_days) < 30

    def test_market_day_ids_are_slug_plus_date(self):
        events, _ = normalized()
        market_days = [e for e in events if e.title == config.MARKET_TITLE]
        assert all(e.id.startswith("hollywood_farmers_market:market@") for e in market_days)
        assert len({e.id for e in market_days}) == len(market_days)

    def test_market_day_ids_do_not_move_when_the_run_time_does(self):
        # The point of the whole scheme: a bookmark has to survive the next run.
        first, _ = normalize(listings(), hours_text=HOURS, now=NOW)
        later, _ = normalize(listings(), hours_text=HOURS, now=NOW + timedelta(days=14))
        shared_dates = {e.id for e in first} & {e.id for e in later}
        assert len(shared_dates) > 5
        by_id = {e.id: e.start_at for e in first}
        for event in later:
            if event.id in by_id:
                assert event.start_at == by_id[event.id]

    def test_summer_market_days_open_at_eight(self):
        events, _ = normalized()
        august = [
            e for e in events if e.title == config.MARKET_TITLE and e.start_at.month == 8 and e.start_at.year == 2026
        ]
        assert august
        assert all(e.start_at.hour == 8 for e in august)

    def test_expansion_is_skipped_when_the_hours_change(self):
        # Rather than publishing a market that may not be open.
        events, counters = normalized(hours_text="saturdays whenever we feel like it")
        assert counters.market_days_expanded == 0
        assert counters.market_rules_skipped == len(config.MARKET_RULES)
        assert not [e for e in events if e.title == config.MARKET_TITLE]

    def test_listings_still_publish_when_expansion_is_skipped(self):
        events, _ = normalized(hours_text=None)
        assert [e for e in events if e.title == "Tyler Waltner Quartet"]


class TestNormalize:
    def test_times_are_portland_local(self):
        events, _ = normalized()
        quartet = next(e for e in events if e.title == "Tyler Waltner Quartet")
        assert quartet.start_at.isoformat() == "2026-08-01T10:00:00-07:00"
        assert quartet.end_at.isoformat() == "2026-08-01T12:30:00-07:00"

    def test_a_multiday_event_keeps_its_end(self):
        events, _ = normalized()
        week = next(e for e in events if e.title == "National Farmers Market Week")
        assert week.start_at.date().isoformat() == "2026-08-02"
        assert week.end_at.date().isoformat() == "2026-08-08"

    def test_past_listings_are_dropped(self):
        events, counters = normalized()
        assert counters.stale == 1
        assert not [e for e in events if e.title == "Dumpster Joe"]

    def test_ids_are_namespaced_by_collection(self):
        events, _ = normalized()
        quartet = next(e for e in events if e.title == "Tyler Waltner Quartet")
        assert quartet.id == "hollywood_farmers_market:music-schedule/tyler-waltner-quartet-2026"

    def test_events_are_sorted(self):
        events, _ = normalized()
        assert [e.start_at for e in events] == sorted(e.start_at for e in events)

    def test_output_validates(self):
        events, _ = normalized()
        validate_per_source(build_per_source_feed("hollywood_farmers_market", events, generated_at=NOW))


class TestPriceAndVenue:
    def test_market_days_are_free_and_on_the_map(self):
        events, _ = normalized()
        day = next(e for e in events if e.title == config.MARKET_TITLE)
        assert day.price == Price.free()
        assert day.venue.latitude == pytest.approx(45.536, abs=0.01)
        assert day.categories == (Category.MARKET, Category.FOOD)

    def test_music_is_free_and_at_the_market(self):
        events, _ = normalized()
        quartet = next(e for e in events if e.title == "Tyler Waltner Quartet")
        assert quartet.price == Price.free()
        assert quartet.venue is not None
        assert quartet.categories == (Category.MUSIC, Category.MARKET)

    def test_special_events_claim_neither_price_nor_place(self):
        # Their own schema.org markup carries an empty location and a null offers,
        # and the collection mixes on-site days with off-site benefit nights. A
        # guess either way would be a wrong pin or a wrong price.
        events, _ = normalized()
        fundraiser = next(e for e in events if "Fundraiser" in e.title)
        assert fundraiser.price == Price.unknown()
        assert fundraiser.venue is None
