"""Tests for the Eventbrite source.

The fixture is a trimmed copy of a real `/api/v3/destination/search/` result, keeping
the shapes that actually caused trouble: prices split into `major_value` (dollars) and
`value` (cents), coordinates as strings, a separate local date, local clock and IANA
zone with no offset anywhere, and signature-locked image renditions.

Every case here comes from something observed in live Portland data — the certification
resellers running on Eastern time at a Portland address, the "Portland" search reaching
Newport and Centralia, paid events with no published figure — rather than from
hypotheticals.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.validate import validate_per_source
from pipeline.sources.eventbrite import config
from pipeline.sources.eventbrite.fetch import date_windows, parse_result
from pipeline.sources.eventbrite.normalize import infer_categories, normalize

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)

IMAGE_BASE = "https://img.evbuc.com/https%3A%2F%2Fcdn.evbuc.com%2Fimages%2F1188792874%2F1%2Foriginal"


def result(**overrides):
    """One search hit, shaped like the live payload."""
    base = {
        "id": "1993877033882",
        "eventbrite_event_id": "1993877033882",
        "name": "Building Your Leadership Legacy",
        "summary": "A conversation with Senior Sales Director Michelle Wamser.",
        # No offset anywhere: a local date, a local clock, and a zone name.
        "start_date": "2026-08-06",
        "start_time": "15:00",
        "end_date": "2026-08-06",
        "end_time": "17:00",
        "timezone": "America/Los_Angeles",
        "url": "https://www.eventbrite.com/e/building-your-leadership-legacy-tickets-1993877033882",
        "tickets_url": "https://www.eventbrite.com/checkout-external?eid=1993877033882",
        "is_online_event": False,
        "is_cancelled": None,
        "image": {
            "url": f"{IMAGE_BASE}?s=full",
            "image_sizes": {
                "small": f"{IMAGE_BASE}?w=320&s=aaa",
                "medium": f"{IMAGE_BASE}?w=640&s=bbb",
                "large": f"{IMAGE_BASE}?w=1024&s=ccc",
            },
            "original": {"url": f"{IMAGE_BASE}?s=orig", "width": 2560, "height": 1810},
        },
        "tags": [
            {"prefix": "EventbriteSubCategory", "display_name": "Career"},
            {"prefix": "EventbriteCategory", "display_name": "Business & Professional"},
            {"prefix": "EventbriteFormat", "display_name": "Seminar or Talk"},
        ],
        "primary_organizer": {"name": "adidas North America Talent Acquisition"},
        "primary_venue": {
            "name": "adidas",
            "address": {
                "city": "Portland",
                "region": "OR",
                # Coordinates arrive as strings.
                "latitude": "45.5599584",
                "longitude": "-122.6948246",
                "localized_address_display": "5055 North Greeley Avenue, Portland, OR 97217",
            },
        },
        "ticket_availability": {
            "is_free": True,
            "minimum_ticket_price": {"currency": "USD", "major_value": "0.00", "value": 0},
            "maximum_ticket_price": {"currency": "USD", "major_value": "0.00", "value": 0},
            "is_sold_out": False,
        },
    }
    base.update(overrides)
    return base


def raw_one(*, matched_free_filter=False, **overrides):
    return parse_result(result(**overrides), matched_free_filter=matched_free_filter)


def one(*, now=NOW, matched_free_filter=False, **overrides):
    raw = raw_one(matched_free_filter=matched_free_filter, **overrides)
    events, counters = normalize([raw], now=now)
    return (events[0] if events else None), counters


class TestIdentity:
    def test_id_is_the_eventbrite_event_id(self):
        # Bookmarks key off this, so it must come from upstream identity only.
        event, _ = one()
        assert event.id == "eventbrite:1993877033882"

    def test_id_is_unchanged_by_a_retitled_or_rescheduled_event(self):
        renamed, _ = one(name="Completely Different Title", start_date="2026-09-01")
        assert renamed.id == "eventbrite:1993877033882"

    def test_both_urls_point_at_the_event_page_not_checkout(self):
        # `tickets_url` is a /checkout-external link, which robots.txt disallows.
        event, _ = one()
        assert event.listing_url == event.ticket_url
        assert "/e/" in event.listing_url
        assert "checkout-external" not in event.ticket_url


class TestTimestamps:
    """The zone is authoritative; the offset is resolved from it, never assumed."""

    def test_a_summer_event_resolves_to_pdt(self):
        event, _ = one()
        assert event.start_at.isoformat() == "2026-08-06T15:00:00-07:00"
        assert event.end_at.isoformat() == "2026-08-06T17:00:00-07:00"

    def test_a_winter_event_resolves_to_pst(self):
        # Same fields, six months later: the offset must move on its own.
        event, _ = one(start_date="2027-01-06", end_date="2027-01-06")
        assert event.start_at.isoformat() == "2027-01-06T15:00:00-08:00"

    def test_a_missing_clock_is_all_day_rather_than_midnight(self):
        event, _ = one(start_time=None)
        assert event.is_all_day is True

    def test_an_end_before_the_start_is_discarded(self):
        event, _ = one(end_date="2026-08-05")
        assert event.end_at is None
        assert event.start_at is not None

    def test_a_multi_day_event_keeps_its_end(self):
        event, _ = one(end_date="2026-08-09", end_time="22:00")
        assert event.end_at.isoformat() == "2026-08-09T22:00:00-07:00"

    def test_an_event_with_no_zone_is_dropped(self):
        # Without a zone there is no offset to resolve, and guessing is how a feed
        # ships every event hours off.
        event, counters = one(timezone=None)
        assert event is None
        assert counters.no_timezone == 1


class TestTimezoneConflicts:
    """National resellers list "PMP Training in Portland" on Eastern time. Eventbrite
    renders those in the declared zone, so 9am Eastern is 6am at a Portland venue.
    Either the clock or the address is wrong and there is no telling which."""

    @pytest.mark.parametrize(
        "zone", ["America/New_York", "America/Chicago", "America/Phoenix", "Asia/Calcutta"]
    )
    def test_a_portland_venue_on_another_clock_is_dropped(self, zone):
        event, counters = one(timezone=zone)
        assert event is None
        assert counters.timezone_conflict == 1

    def test_the_pacific_zone_is_kept(self):
        event, counters = one()
        assert event is not None
        assert counters.timezone_conflict == 0


class TestPricing:
    def test_the_free_flag_is_honoured(self):
        event, _ = one()
        assert event.price == Price.free()

    def test_a_paid_event_reads_dollars_not_cents(self):
        # major_value is dollars, value is minor units; reading `value` would put
        # $1,200 on a $12 event.
        event, _ = one(ticket_availability={
            "is_free": False,
            "minimum_ticket_price": {"currency": "USD", "major_value": "12.00", "value": 1200},
            "maximum_ticket_price": {"currency": "USD", "major_value": "12.00", "value": 1200},
        })
        assert (event.price.is_free, event.price.min, event.price.max) == (False, 12.0, 12.0)

    def test_a_price_range_keeps_both_bounds(self):
        event, _ = one(ticket_availability={
            "is_free": False,
            "minimum_ticket_price": {"currency": "USD", "major_value": "160.00", "value": 16000},
            "maximum_ticket_price": {"currency": "USD", "major_value": "210.00", "value": 21000},
        })
        assert (event.price.min, event.price.max) == (160.0, 210.0)

    def test_paid_with_no_published_figure_is_unknown_not_free(self):
        # 12 of 1,434 sampled events look exactly like this.
        event, _ = one(ticket_availability={
            "is_free": False,
            "minimum_ticket_price": None,
            "maximum_ticket_price": None,
        })
        assert event.price == Price.unknown()
        assert event.price.is_free is False

    def test_a_missing_availability_block_is_unknown_not_free(self):
        event, _ = one(ticket_availability=None)
        assert event.price == Price.unknown()

    def test_a_zero_range_on_a_not_free_event_is_unknown_rather_than_a_zero_badge(self):
        # ~2% of a run: donation and register-to-attend events where every ticket class
        # is $0.00 yet `is_free` is false. Claiming free contradicts upstream; showing
        # "$0" on an event the app treats as paid is worse than showing nothing.
        event, _ = one(ticket_availability={
            "is_free": False,
            "minimum_ticket_price": {"currency": "USD", "major_value": "0.00", "value": 0},
            "maximum_ticket_price": {"currency": "USD", "major_value": "0.00", "value": 0},
        })
        assert event.price == Price.unknown()
        assert event.price.is_free is False

    def test_a_free_tier_alongside_paid_ones_keeps_the_range(self):
        event, _ = one(ticket_availability={
            "is_free": False,
            "minimum_ticket_price": {"currency": "USD", "major_value": "0.00", "value": 0},
            "maximum_ticket_price": {"currency": "USD", "major_value": "449.00", "value": 44900},
        })
        assert (event.price.min, event.price.max) == (0.0, 449.0)

    def test_a_non_usd_amount_is_withheld_rather_than_shown_as_dollars(self):
        event, _ = one(ticket_availability={
            "is_free": False,
            "minimum_ticket_price": {"currency": "GBP", "major_value": "50.00", "value": 5000},
            "maximum_ticket_price": {"currency": "GBP", "major_value": "50.00", "value": 5000},
        })
        assert event.price == Price.unknown()

    def test_the_free_filter_does_not_by_itself_make_an_event_free(self):
        # The per-event flag is the evidence. Arriving under the `price=free` query
        # corroborates it but must never override it.
        event, _ = one(
            matched_free_filter=True,
            ticket_availability={
                "is_free": False,
                "minimum_ticket_price": {"currency": "USD", "major_value": "5.00", "value": 500},
                "maximum_ticket_price": {"currency": "USD", "major_value": "5.00", "value": 500},
            },
        )
        assert event.price.is_free is False
        assert event.price.min == 5.0


class TestImages:
    def test_the_card_sized_rendition_is_preferred(self):
        # Full-resolution artwork decoded to ~13 MB apiece and exhausted the app's
        # memory on Ticketmaster. `large` is 1024px; `original` here is 2560px.
        event, _ = one()
        assert "w=1024" in event.image_url
        assert "s=orig" not in event.image_url

    def test_it_falls_back_through_the_smaller_renditions(self):
        event, _ = one(image={"image_sizes": {"small": f"{IMAGE_BASE}?w=320&s=aaa"}})
        assert "w=320" in event.image_url

    def test_the_unsized_url_is_never_used(self):
        # `image.url` is sometimes the full-resolution original, and its signature
        # cannot be rewritten to a smaller width — that returns HTTP 403.
        event, _ = one(image={"url": f"{IMAGE_BASE}?s=full", "original": {"url": f"{IMAGE_BASE}?s=orig"}})
        assert event.image_url is None

    def test_a_missing_image_is_not_an_error(self):
        event, _ = one(image=None)
        assert event.image_url is None
        assert event.title


class TestMetroFilter:
    """Eventbrite's "Portland" place reaches well past the metro."""

    @pytest.mark.parametrize(
        "city,lat,lon",
        [
            ("Newport", 44.6368, -124.0535),      # 91 miles, observed
            ("Centralia", 46.7162, -122.9543),    # 84 miles, observed
            ("Salem", 44.9429, -123.0351),        # 46 miles, observed
        ],
    )
    def test_venues_beyond_the_metro_are_dropped(self, city, lat, lon):
        event, counters = one(primary_venue={
            "name": f"{city} Hall",
            "address": {"city": city, "latitude": str(lat), "longitude": str(lon)},
        })
        assert event is None
        assert counters.outside_metro == 1

    @pytest.mark.parametrize(
        "city,lat,lon",
        [
            ("Hillsboro", 45.5229, -122.9898),
            ("Oregon City", 45.3573, -122.6068),
            ("Vancouver", 45.6387, -122.6615),
            ("Troutdale", 45.5395, -122.3873),
        ],
    )
    def test_the_metro_edges_are_kept(self, city, lat, lon):
        event, _ = one(primary_venue={
            "name": f"{city} Hall",
            "address": {"city": city, "latitude": str(lat), "longitude": str(lon)},
        })
        assert event is not None

    def test_a_venue_without_coordinates_is_kept(self):
        event, _ = one(primary_venue={"name": "Somewhere", "address": {"city": "Portland"}})
        assert event is not None
        assert event.venue.name == "Somewhere"

    def test_coordinates_survive_as_numbers(self):
        event, _ = one()
        assert event.venue.latitude == pytest.approx(45.5599584)
        assert event.venue.longitude == pytest.approx(-122.6948246)
        assert event.venue.city == "Portland"


class TestExclusions:
    def test_a_cancelled_event_is_dropped(self):
        event, counters = one(is_cancelled=True)
        assert event is None
        assert counters.cancelled == 1

    def test_a_null_cancelled_flag_means_not_cancelled(self):
        # Live results carry null far more often than false.
        event, _ = one(is_cancelled=None)
        assert event is not None

    def test_an_online_event_is_dropped(self):
        event, counters = one(is_online_event=True)
        assert event is None
        assert counters.online == 1

    def test_a_long_past_event_is_dropped_as_stale(self):
        event, counters = one(now=NOW + timedelta(days=365))
        assert event is None
        assert counters.stale == 1

    def test_a_result_missing_its_identity_is_skipped_in_parsing(self):
        assert parse_result(result(id=None, eventbrite_event_id=None), matched_free_filter=False) is None
        assert parse_result(result(name=None), matched_free_filter=False) is None
        assert parse_result(result(start_date=None), matched_free_filter=False) is None


class TestCategories:
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Music", Category.MUSIC),
            ("Performing & Visual Arts", Category.ARTS),
            ("Film, Media & Entertainment", Category.FILM),
            ("Food & Drink", Category.FOOD),
            ("Health & Wellness", Category.WELLNESS),
            ("Science & Technology", Category.TECH),
            ("Travel & Outdoor", Category.OUTDOORS),
            ("Sports & Fitness", Category.SPORTS),
            ("Government & Politics", Category.CIVIC),
            ("Family & Education", Category.FAMILY),
            ("Business & Professional", Category.COMMUNITY),
        ],
    )
    def test_the_published_vocabulary_maps(self, label, expected):
        assert infer_categories(label) == (expected,)

    def test_an_unknown_category_falls_back_rather_than_dropping_the_event(self):
        assert infer_categories("Underwater Basketweaving") == (Category.COMMUNITY,)

    def test_format_is_consulted_only_when_the_category_says_nothing(self):
        assert infer_categories(None, "Party or Social Gathering") == (Category.NIGHTLIFE,)
        assert infer_categories("Other", "Concert or Performance") == (Category.MUSIC,)

    def test_format_never_overrides_a_real_category(self):
        # A board game night is tagged "Game or Competition" but is not a sport, and a
        # community potluck tagged "Party or Social Gathering" is not nightlife.
        assert infer_categories("Hobbies & Special Interest", "Game or Competition") == (Category.COMMUNITY,)
        assert infer_categories("Music", "Party or Social Gathering") == (Category.MUSIC,)


class TestFetchPlumbing:
    def test_windows_tile_the_range_without_gaps_or_overlap(self):
        from datetime import date

        windows = list(date_windows(date(2026, 7, 27), window=timedelta(days=30), stride=timedelta(days=7)))
        assert windows[0] == (date(2026, 7, 27), date(2026, 8, 2))
        assert all(b - a == timedelta(days=6) for a, b in windows[:-1])
        for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
            assert next_start - prev_end == timedelta(days=1)
        assert windows[-1][1] >= date(2026, 7, 27) + timedelta(days=29)

    def test_the_page_budget_matches_the_measured_result_ceiling(self):
        # page_size is clamped to 50 upstream and results stop at 1,000 per query.
        assert config.PAGE_SIZE * config.MAX_PAGES_PER_WINDOW == config.RESULT_CEILING

    def test_a_week_of_slack_is_left_under_the_ceiling(self):
        # The busiest sampled Portland week held 829 events against a 1,000 cap.
        assert config.WINDOW_STRIDE <= timedelta(days=7)

    def test_both_price_passes_are_configured(self):
        # Neither is a superset of the other; dropping one loses events.
        assert None in config.PRICE_FILTERS and "free" in config.PRICE_FILTERS

    def test_parse_reads_the_fields_normalize_depends_on(self):
        raw = raw_one()
        assert raw.event_id == "1993877033882"
        assert raw.category == "Business & Professional"
        assert raw.event_format == "Seminar or Talk"
        assert raw.organizer == "adidas North America Talent Acquisition"
        assert raw.price.is_free is True
        assert raw.venue.latitude == pytest.approx(45.5599584)


def test_output_validates():
    events, _ = normalize([raw_one()], now=NOW)
    validate_per_source(build_per_source_feed("eventbrite", events, generated_at=NOW))
