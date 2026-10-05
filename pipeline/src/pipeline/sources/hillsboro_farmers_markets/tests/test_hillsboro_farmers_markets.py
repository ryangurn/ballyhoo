"""Tests for the Hillsboro Farmers' Markets source.

The fixture is trimmed from the real events page and keeps each kind of title it
publishes: a bare market name, the operator's prefixed name, a harvest festival, a
cancellation naming its market, a closure naming none, and the copy-suffix slugs that
make the Squarespace item slug unfit to key a bookmark on.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.squarespace import parse_event_list
from pipeline.common.validate import validate_per_source
from pipeline.sources.hillsboro_farmers_markets import config
from pipeline.sources.hillsboro_farmers_markets.normalize import (
    is_closure,
    is_harvest_festival,
    market_for,
    normalize,
)

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
NNBSP = "\u202f"


def article(href, title, day, start, end):
    return f"""
  <article class="eventlist-event eventlist-event--upcoming">
    <h1 class="eventlist-title"><a class="eventlist-title-link" href="{href}">{title}</a></h1>
    <ul class="eventlist-meta">
      <li><time class="event-date" datetime="{day}">{day}</time></li>
      <li>
        <time class="event-time-localized-start" datetime="{day}">{start.replace(" ", NNBSP)}</time>
        <time class="event-time-localized-end" datetime="{day}">{end.replace(" ", NNBSP)}</time>
      </li>
      <li class="eventlist-meta-address">Hillsboro Farmers' Markets
        <a href="http://maps.google.com?q=1415 Northeast 61st Avenue Hillsboro">(map)</a></li>
    </ul>
  </article>"""


HTML = "<div class='eventlist'>" + "".join(
    [
        article("/events/orenco-station-sffap-3p8ad-2mjxj", "Orenco Station", "2026-10-11", "10:00 AM", "2:00 PM"),
        article(
            "/events/cjhxxmdhvuea4ky3x1rjuqvqy0nslu-3lcek",
            "Hillsboro Farmers Markets - Saturday Downtown",
            "2026-10-10",
            "9:00 AM",
            "1:00 PM",
        ),
        article(
            "/events/reeds-crossing-at-tamarack-park-xxgfj",
            "Harvest Festival - Reed's Crossing at Tamarack Park",
            "2026-10-07",
            "4:30 PM",
            "8:00 PM",
        ),
        article(
            "/events/streets-at-tanasbourne-gdrn8", "The Streets at Tanasbourne", "2026-10-08", "4:00 PM", "8:00 PM"
        ),
        # A cancellation naming its market, published alongside the original item.
        article(
            "/events/reeds-crossing-at-tamarack-park-x",
            "**CANCELLED Oct 14th, 2026 **Reed's Crossing at Tamarack Park",
            "2026-10-14",
            "4:30 PM",
            "8:00 PM",
        ),
        article("/events/reeds-crossing-y", "Reed's Crossing at Tamarack Park", "2026-10-14", "4:30 PM", "8:00 PM"),
        # A closure naming no market closes every market that day.
        article("/events/hwokr7ugiokj7yd4qnk3j6g0fc33ef", "HFM Closed - Storm", "2026-10-17", "9:00 AM", "5:00 PM"),
        article(
            "/events/cjhxxmdhvuea4ky3x1rjuqvqy0nslu-3lcek-c885m",
            "Hillsboro Farmers Markets - Saturday Downtown",
            "2026-10-17",
            "9:00 AM",
            "1:00 PM",
        ),
        article("/events/vendor-meeting", "Vendor Meeting", "2026-10-20", "6:00 PM", "7:00 PM"),
        article("/events/orenco-station-old", "Orenco Station", "2026-08-02", "10:00 AM", "2:00 PM"),
    ]
) + "</div>"


def items():
    return parse_event_list(HTML, base_url=config.BASE_URL)


def normalized(now=NOW):
    return normalize(items(), now=now)


def by_id(suffix):
    events, _ = normalized()
    return next(e for e in events if e.id == f"hillsboro_farmers_markets:{suffix}")


class TestTitles:
    @pytest.mark.parametrize(
        "title,key",
        [
            ("Orenco Station", "orenco"),
            ("Hillsboro Farmers Markets - Saturday Downtown", "downtown"),
            ("Harvest Festival - Hillsboro Farmers Markets - Saturday Downtown", "downtown"),
            ("Reed\u2019s Crossing at Tamarack Park", "reeds-crossing"),
            ("The Streets at Tanasbourne", "tanasbourne"),
            ("Streets at Tanasbourne", "tanasbourne"),
        ],
    )
    def test_each_title_form_finds_its_market(self, title, key):
        assert market_for(title).key == key

    def test_an_unrelated_title_finds_no_market(self):
        assert market_for("Vendor Meeting") is None

    def test_closures_and_festivals_are_recognised(self):
        assert is_closure("**CANCELLED Aug 5th, 2026 **Reed's Crossing at Tamarack Park")
        assert is_closure("HFM Closed - Labor Day")
        assert not is_closure("Orenco Station")
        assert is_harvest_festival("Harvest Festival - Orenco Station")
        assert not is_harvest_festival("Orenco Station")


class TestNormalize:
    def test_published_under_the_markets_own_name(self):
        assert by_id("orenco@2026-10-11").title == "Orenco Station Farmers' Market"
        assert by_id("downtown@2026-10-10").title == "Downtown Hillsboro Saturday Farmers' Market"

    def test_a_festival_day_says_so(self):
        assert by_id("reeds-crossing@2026-10-07").title == (
            "Harvest Festival at South Hillsboro Farmers' Market at Reed's Crossing"
        )

    def test_id_is_market_plus_date_not_the_copy_suffixed_slug(self):
        event = by_id("orenco@2026-10-11")
        assert "sffap" not in event.id
        assert event.listing_url == "https://hillsboromarkets.org/events/orenco-station-sffap-3p8ad-2mjxj"

    def test_ids_do_not_move_with_the_run_time(self):
        first, _ = normalized()
        later, _ = normalized(now=NOW + timedelta(days=2))
        assert {e.id for e in later} <= {e.id for e in first}

    def test_times_are_portland_local(self):
        event = by_id("reeds-crossing@2026-10-07")
        assert event.start_at.isoformat() == "2026-10-07T16:30:00-07:00"
        assert event.end_at.isoformat() == "2026-10-07T20:00:00-07:00"

    def test_location_comes_from_the_market_not_the_items_office_address(self):
        venue = by_id("orenco@2026-10-11").venue
        assert venue.name == "Orenco Station Farmers' Market"
        assert venue.address == "6125 NE Cornell Rd, Hillsboro, OR 97124"
        assert venue.latitude == pytest.approx(45.534, abs=0.01)

    def test_free_market_and_food(self):
        event = by_id("tanasbourne@2026-10-08")
        assert event.price == Price.free()
        assert event.categories == (Category.MARKET, Category.FOOD)

    def test_output_validates(self):
        events, _ = normalized()
        validate_per_source(build_per_source_feed("hillsboro_farmers_markets", events, generated_at=NOW))


class TestClosures:
    def test_a_cancellation_suppresses_its_markets_day_even_alongside_the_original(self):
        events, _ = normalized()
        assert not [e for e in events if e.id.endswith("reeds-crossing@2026-10-14")]

    def test_a_closure_naming_no_market_closes_every_market_that_day(self):
        events, _ = normalized()
        assert not [e for e in events if e.id.endswith("@2026-10-17")]

    def test_closures_are_counted(self):
        _, counters = normalized()
        # Two closure items, plus the two market days they took away.
        assert counters.closed == 4


class TestDrops:
    def test_an_unrecognised_title_is_dropped_and_counted(self):
        events, counters = normalized()
        assert counters.unrecognised == 1
        assert not [e for e in events if "Vendor" in e.title]

    def test_past_market_days_are_dropped(self):
        _, counters = normalized()
        assert counters.stale == 1
