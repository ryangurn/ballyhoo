"""Tests for the Oregon Ballet Theatre source.

Both fixtures are trimmed from real responses captured on 2026-07-27. The cases that
matter are the ones a ballet season actually produces: a single production running
eighteen nights needs eighteen distinct stable ids, and Tessitura publishes every
performance time twice, in local and UTC, which is a free correctness check nobody
gets to skip.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from pipeline.common.io import build_per_source_feed
from pipeline.common.models import Category, Price
from pipeline.common.validate import validate_per_source
from pipeline.sources.obt.fetch import (
    RawOBTSeason,
    find_season_page_url,
    match_key,
    parse_image_renditions,
    parse_season_venues,
)
from pipeline.sources.obt.normalize import best_image, build_summary, normalize, strip_html
from pipeline.sources.obt.tessitura import TimestampDisagreement, parse_listing

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _performance(pid: int, local: str, utc: str, **overrides) -> dict:
    payload = {
        "id": pid,
        "performanceDate": utc,
        "iso8601DateString": local,
        "performanceTitle": "George Balanchine's The Nutcracker",
        "actionUrl": f"https://my.obt.org/817/{pid}",
        "isPerformanceVisible": True,
        "isOnSale": True,
        "productTypeName": "w/OBT Orchestra",
        "performanceStatusMessage": "",
    }
    payload.update(overrides)
    return payload


# Trimmed from POST https://my.obt.org/api/products/productionseasons. Note the seven
# fractional digits on iso8601DateString and the December -08:00 offset.
LISTING = {
    "productions": [
        {
            "productionSeasonId": "817",
            "productionTitle": "George Balanchine's The Nutcracker",
            "listingImageUrl": "https://www.obt.org/wp-content/uploads/2026/03/Mock-ups-for-tessitura-1.png",
            "description": (
                "<p>A sparkling winter tale set to Tchaikovsky\u2019s festive score.</p>\n\n"
                "<p>Live music presented by Internetworks</p>\n\n"
                '<p><span style="font-size:8px;">photo: Hart Isaacoff by Jingzi Zhao</span></p>\n'
            ),
            "productionSeasonActionUrl": "https://my.obt.org/817",
            "startDate": "0001-01-01T00:00:00",
            "displayDate": None,
            "performances": [
                _performance(830, "2026-12-05T14:00:00.0000000-08:00", "2026-12-05T22:00:00+00:00"),
                _performance(854, "2026-12-05T19:30:00.0000000-08:00", "2026-12-06T03:30:00+00:00"),
                _performance(832, "2026-12-06T14:00:00.0000000-08:00", "2026-12-06T22:00:00+00:00"),
            ],
        },
        {
            "productionSeasonId": "871",
            "productionTitle": "Dominic Walsh's Storybook Nutcracker",
            "listingImageUrl": "https://www.obt.org/wp-content/uploads/2026/03/Mock-ups-for-tessitura-2.png",
            "description": "<p>A shorter telling for younger audiences.</p>",
            "productionSeasonActionUrl": "https://my.obt.org/871",
            "performances": [
                _performance(
                    872,
                    "2026-12-23T10:30:00.0000000-08:00",
                    "2026-12-23T18:30:00+00:00",
                    performanceTitle="Dominic Walsh's Storybook Nutcracker",
                    productTypeName="Sensory Friendly/Recorded Music",
                    actionUrl="https://my.obt.org/871/872",
                ),
            ],
        },
    ],
    "ga4DatalayerItems": [],
}

# Trimmed from https://www.obt.org/ballet-performances-in-portland/2026-27-season/.
# The registered mark and curly apostrophe are exactly as the page spells them, and
# are the reason titles need folding before they match Tessitura's.
SEASON_PAGE = """
<div class="col">
  <article class="card__card ll_event ll_event_location-keller-auditorium">
    <a class="group"><div class="mt-4">
      <h2 class="mb-2 hdg-6 card__card-title">Swan Lake</h2>
      <div class="flex card__card-meta">
        <p>October 10 - 17, 2026</p><span>&bull;</span>
        <span class="flex-initial">Keller Auditorium</span>
      </div>
    </div></a>
  </article>
  <article class="card__card ll_event ll_event_location-keller-auditorium">
    <a class="group"><div class="mt-4">
      <h2 class="mb-2 hdg-6 card__card-title">George Balanchine&#8217;s The Nutcracker&#174;</h2>
      <div class="flex card__card-meta">
        <p>December 5 - 24, 2026</p><span>&bull;</span>
        <span class="flex-initial">Keller Auditorium</span>
      </div>
    </div></a>
  </article>
  <article class="card__card ll_event ll_event_location-newmark-theatre">
    <a class="group"><div class="mt-4">
      <h2 class="mb-2 hdg-6 card__card-title">MADCAP</h2>
      <div class="flex card__card-meta">
        <p>April 2 - 10, 2027</p><span>&bull;</span>
        <span class="flex-initial">Newmark Theatre</span>
      </div>
    </div></a>
  </article>
  <article class="card__card ll_event">
    <a class="group"><div class="mt-4">
      <h2 class="mb-2 hdg-6 card__card-title">Gala To Be Announced</h2>
      <div class="flex card__card-meta">
        <p>Spring 2027</p>
      </div>
    </div></a>
  </article>
</div>
"""

VENUES = parse_season_venues(SEASON_PAGE)


def _raw(listing: dict | None = None, venues: dict | None = None) -> RawOBTSeason:
    productions = parse_listing(listing if listing is not None else LISTING)
    return RawOBTSeason(tuple(productions), VENUES if venues is None else venues)


class TestListingParsing:
    def test_reads_both_productions_and_every_performance(self):
        productions = parse_listing(LISTING)
        assert [p.id for p in productions] == ["817", "871"]
        assert sum(len(p.performances) for p in productions) == 4

    def test_carries_the_per_performance_fields(self):
        first = parse_listing(LISTING)[0].performances[0]
        assert first.id == 830
        assert first.product_type == "w/OBT Orchestra"
        assert first.ticket_url == "https://my.obt.org/817/830"
        assert first.is_visible

    def test_a_production_with_no_performances_is_skipped(self):
        # A production season can exist with nothing on sale; there is no occurrence
        # to publish, so it is not half-represented as a dateless event.
        payload = {"productions": [{"productionSeasonId": "900", "productionTitle": "TBA", "performances": []}]}
        assert parse_listing(payload) == []

    def test_an_empty_response_is_not_an_error(self):
        assert parse_listing({"productions": []}) == []
        assert parse_listing({}) == []


class TestTimestamps:
    def test_seven_fractional_digits_with_an_offset_parse(self):
        # Tessitura emits .0000000, which is more precision than the stdlib parser
        # historically accepted.
        performance = parse_listing(LISTING)[0].performances[0]
        assert performance.instant.isoformat() == "2026-12-05T14:00:00-08:00"

    def test_the_utc_twin_describes_the_same_instant(self):
        performance = parse_listing(LISTING)[0].performances[0]
        assert performance.instant == datetime.fromisoformat("2026-12-05T22:00:00+00:00")

    def test_disagreeing_timestamps_raise_rather_than_pick_one(self):
        # The failure this guards against: an offset-free or mislabeled field shipping
        # every event some whole number of hours off. If the two disagree we do not
        # know which is right, so we refuse rather than guess.
        payload = {
            "productions": [
                {
                    "productionSeasonId": "817",
                    "productionTitle": "Nutcracker",
                    "performances": [
                        _performance(999, "2026-12-05T14:00:00.0000000-08:00", "2026-12-05T15:00:00+00:00")
                    ],
                }
            ]
        }
        with pytest.raises(TimestampDisagreement):
            parse_listing(payload)[0].performances[0].instant

    def test_a_disagreeing_performance_is_dropped_not_fatal(self):
        payload = json.loads(json.dumps(LISTING))
        payload["productions"][0]["performances"][1]["performanceDate"] = "2026-12-06T09:30:00+00:00"
        events, counters = normalize(_raw(payload), now=NOW)
        assert counters.timestamp_disagreement == 1
        assert len(events) == 3
        assert "obt:854" not in {e.id for e in events}

    def test_output_is_portland_local_time(self):
        events, _ = normalize(_raw(), now=NOW)
        assert all(e.start_at.utcoffset().total_seconds() == -8 * 3600 for e in events)


class TestIdentity:
    def test_every_performance_in_a_run_gets_its_own_id(self):
        # The whole point of one-event-per-performance: three showings of the same
        # production must not collapse onto one bookmark.
        events, _ = normalize(_raw(), now=NOW)
        nutcrackers = [e for e in events if e.title == "George Balanchine's The Nutcracker"]
        assert len(nutcrackers) == 3
        assert len({e.id for e in nutcrackers}) == 3

    def test_id_is_the_tessitura_performance_key(self):
        events, _ = normalize(_raw(), now=NOW)
        assert {e.id for e in events} == {"obt:830", "obt:854", "obt:832", "obt:872"}

    def test_id_survives_a_production_being_retitled(self):
        # Tessitura's key is immutable; the title is not. Renaming upstream must not
        # orphan a bookmark.
        renamed = json.loads(json.dumps(LISTING))
        renamed["productions"][0]["productionTitle"] = "The Nutcracker (2026)"
        for performance in renamed["productions"][0]["performances"]:
            performance["performanceTitle"] = "The Nutcracker (2026)"
        before = {e.id for e in normalize(_raw(), now=NOW)[0]}
        after = {e.id for e in normalize(_raw(renamed), now=NOW)[0]}
        assert before == after

    def test_ids_are_stable_across_repeated_normalization(self):
        first, _ = normalize(_raw(), now=NOW)
        second, _ = normalize(_raw(), now=NOW)
        assert [e.id for e in first] == [e.id for e in second]


class TestSeasonPage:
    def test_extracts_a_venue_per_production(self):
        assert VENUES[match_key("Swan Lake")] == "Keller Auditorium"
        assert VENUES[match_key("MADCAP")] == "Newmark Theatre"

    def test_a_card_with_no_venue_yields_no_venue(self):
        # "Spring 2027" with no bullet and no second span must not be read as a place.
        assert match_key("Gala To Be Announced") not in VENUES

    def test_title_folding_bridges_the_two_spellings(self):
        # Season page: "George Balanchine’s The Nutcracker®". Tessitura: no mark,
        # straight apostrophe. Both must land on the same key.
        assert match_key("George Balanchine\u2019s The Nutcracker\u00ae") == match_key(
            "George Balanchine's The Nutcracker"
        )

    def test_season_url_discovery_prefers_the_newest(self):
        html = """
        <a href="/ballet-performances-in-portland/2025-26-season/">Last season</a>
        <a href="/ballet-performances-in-portland/2026-27-season/">This season</a>
        <a href="/ballet-performances-in-portland/2026-27-season/subscription-packages/">Subscribe</a>
        """
        assert (
            find_season_page_url(html, base_url="https://www.obt.org")
            == "https://www.obt.org/ballet-performances-in-portland/2026-27-season/"
        )

    def test_no_season_link_is_not_an_error(self):
        assert find_season_page_url("<p>nothing</p>", base_url="https://www.obt.org") is None


class TestVenues:
    def test_known_venues_get_baked_coordinates(self):
        events, _ = normalize(_raw(), now=NOW)
        venue = events[0].venue
        assert venue.name == "Keller Auditorium"
        assert venue.city == "Portland"
        assert venue.latitude == pytest.approx(45.512, abs=0.01)
        assert venue.longitude == pytest.approx(-122.678, abs=0.01)

    def test_an_unmapped_venue_still_publishes_the_event(self):
        events, counters = normalize(_raw(venues={match_key("George Balanchine's The Nutcracker"): "Some New Hall"}), now=NOW)
        nutcracker = next(e for e in events if e.id == "obt:830")
        assert nutcracker.venue.name == "Some New Hall"
        assert nutcracker.venue.latitude is None
        assert counters.no_venue_coordinates == 3

    def test_a_missing_season_page_costs_venues_not_events(self):
        events, counters = normalize(_raw(venues={}), now=NOW)
        assert len(events) == 4
        assert all(e.venue is None for e in events)
        assert counters.no_venue_name == 4


class TestNormalization:
    def test_price_is_unknown_never_free(self):
        # Tessitura publishes no price on any surface we can reach, and ballet
        # tickets are emphatically not free.
        events, _ = normalize(_raw(), now=NOW)
        assert all(e.price == Price.unknown() for e in events)
        assert not any(e.price.is_free for e in events)

    def test_no_end_time_is_invented(self):
        events, _ = normalize(_raw(), now=NOW)
        assert all(e.end_at is None for e in events)

    def test_categorized_as_arts(self):
        events, _ = normalize(_raw(), now=NOW)
        assert all(e.categories == (Category.ARTS,) for e in events)

    def test_hidden_performances_are_dropped(self):
        payload = json.loads(json.dumps(LISTING))
        payload["productions"][0]["performances"][0]["isPerformanceVisible"] = False
        events, counters = normalize(_raw(payload), now=NOW)
        assert counters.hidden == 1
        assert "obt:830" not in {e.id for e in events}

    def test_past_performances_are_dropped(self):
        events, counters = normalize(_raw(), now=datetime(2027, 6, 1, tzinfo=UTC))
        assert events == []
        assert counters.stale == 4

    def test_events_are_sorted(self):
        events, _ = normalize(_raw(), now=NOW)
        assert [e.start_at for e in events] == sorted(e.start_at for e in events)

    def test_ticket_and_listing_urls_are_carried(self):
        events, _ = normalize(_raw(), now=NOW)
        first = next(e for e in events if e.id == "obt:830")
        assert first.ticket_url == "https://my.obt.org/817/830"
        assert first.listing_url == "https://my.obt.org/817"

    def test_output_validates(self):
        events, _ = normalize(_raw(), now=NOW)
        validate_per_source(build_per_source_feed("obt", events, generated_at=NOW))


class TestSummary:
    def test_photo_credit_is_stripped(self):
        text = strip_html(LISTING["productions"][0]["description"])
        assert "photo:" not in text
        assert "Jingzi Zhao" not in text
        assert text.startswith("A sparkling winter tale")

    def test_product_type_leads_because_it_distinguishes_the_showing(self):
        # "Sensory Friendly/Recorded Music" is the only per-performance descriptor
        # Tessitura gives, and it is a materially different event.
        assert build_summary("<p>Body.</p>", "Sensory Friendly/Recorded Music") == (
            "Sensory Friendly/Recorded Music \u2014 Body."
        )

    def test_summary_survives_a_missing_half(self):
        assert build_summary(None, "w/OBT Orchestra") == "w/OBT Orchestra"
        assert build_summary("<p>Body.</p>", None) == "Body."
        assert build_summary(None, None) is None

    def test_long_copy_is_truncated_on_a_word_boundary(self):
        text = strip_html("<p>" + "word " * 200 + "</p>")
        assert len(text) <= 301
        assert text.endswith("\u2026")


class TestImages:
    RENDITIONS = [
        {
            "media_details": {
                "sizes": {
                    "thumbnail": {"width": 150, "source_url": "https://x/a-150x150.png"},
                    "medium": {"width": 300, "source_url": "https://x/a-300x300.png"},
                    "large": {"width": 1024, "source_url": "https://x/a-1024x1024.png"},
                    "1536x1536": {"width": 1536, "source_url": "https://x/a-1536x1536.png"},
                    "full": {"width": 2400, "source_url": "https://x/a.png"},
                }
            }
        }
    ]

    def test_picks_the_smallest_rendition_over_the_threshold(self):
        # Not the largest: a 2400px PNG decodes to roughly 22 MB, which is how the
        # Ticketmaster source got the app killed on device.
        renditions = parse_image_renditions(self.RENDITIONS)
        assert best_image("https://x/a.png", renditions) == "https://x/a-1536x1536.png"

    def test_falls_back_to_the_original_when_nothing_is_big_enough(self):
        # OBT's actual uploads are 1000px square, so this is the live case today.
        renditions = [(150, "https://x/a-150x150.png"), (768, "https://x/a-768x768.png")]
        assert best_image("https://x/a.png", renditions) == "https://x/a.png"

    def test_a_failed_lookup_is_not_an_error(self):
        assert parse_image_renditions([]) == []
        assert parse_image_renditions({"code": "rest_no_route"}) == []
        assert best_image("https://x/a.png", []) == "https://x/a.png"
        assert best_image(None, []) is None
