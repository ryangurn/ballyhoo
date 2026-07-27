"""Normalize Ticketmaster's Discovery API payloads into the shared Event model.

Shape notes from live data:
  - `dates.start.dateTime` is UTC; `dates.timezone` carries the real local zone. We
    convert to local so the app renders the time a Portlander would actually see.
  - `dateTBD` / `dateTBA` / `timeTBA` / `noSpecificTime` flags mark placeholder times.
  - `dates.status.code` includes `cancelled`, which must not reach the feed.
  - `priceRanges` is present on only about 27% of events.
  - Venue coordinates are strings under `_embedded.venues[0].location`.
  - `images` offers many named renditions, in arbitrary order and mixed ratios, with
    the occasional third-party URL carrying no `ratio` at all.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...common.io import parse_datetime
from ...common.log import get_logger
from ...common.models import Event, Price, Venue, make_event_id
from . import config
from .categories import infer_categories

log = get_logger(__name__)


class NormalizationCounters:
    def __init__(self) -> None:
        self.cancelled = 0
        self.test_event = 0
        self.no_start_time = 0
        self.time_tba = 0
        self.unparseable_time = 0
        self.stale = 0
        self.no_title = 0
        self.wrong_region = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "dropped_cancelled": self.cancelled,
            "dropped_test_event": self.test_event,
            "dropped_no_start_time": self.no_start_time,
            "dropped_time_tba": self.time_tba,
            "dropped_unparseable_time": self.unparseable_time,
            "dropped_stale": self.stale,
            "dropped_no_title": self.no_title,
            "dropped_wrong_region": self.wrong_region,
        }


def _coerce_coordinate(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


_CANONICAL_SUFFIX = f"_{config.CANONICAL_IMAGE_RENDITION}.jpg"


def _size_then_url(image: dict[str, Any]) -> tuple[int, str]:
    return (image.get("width") or 0, image["url"])


def _best_image(images: list[dict[str, Any]] | None) -> str | None:
    """The 1136 px 16:9 rendition, asked for by name so it is the same URL every run.

    Size discipline first: Ticketmaster serves up to 3200 px wide, which decodes to
    roughly 13 MB in memory, and across a feed of several hundred events that is
    enough to get the app killed for exceeding its memory limit. Anything at or above
    `MIN_IMAGE_WIDTH` looks identical at the sizes we render. 16:9 matches the card
    layout; other ratios crop badly.

    Stability second, and it is why the rendition is named rather than measured. The
    `images` array is not ordered by the documented ladder — a live response lists
    3_2 640, 16_9 205, 3_2 1024, then a ratio-less third-party image, and so on — so
    any comparison that can tie breaks on arrival order. Naming the rendition also
    fails safe if the ladder is ever incomplete: a width comparison would quietly
    promote a missing 1136 entry to the 2048 px one, or to _SOURCE, which is exactly
    the full-resolution artwork the bound above exists to keep out.

    A changed URL is not free on the client. `AsyncImage` and the shared `URLSession`
    cache both key on the URL, so re-picking a different rendition for unchanged
    artwork makes every client re-download every image it already holds.
    """
    if not images:
        return None
    usable = [i for i in images if isinstance(i.get("url"), str) and i["url"].strip()]
    if not usable:
        return None

    widescreen = [i for i in usable if i.get("ratio") == "16_9"]
    pool = widescreen or usable

    canonical = [i for i in pool if i["url"].endswith(_CANONICAL_SUFFIX)]
    if canonical:
        return min(canonical, key=lambda i: i["url"])["url"]

    # No canonical rendition on offer. Fall back to the old width rule, but sort on
    # `(width, url)` so an event without one still resolves the same way every run
    # rather than on whichever equal-width entry the response happened to list first.
    big_enough = [i for i in pool if (i.get("width") or 0) >= config.MIN_IMAGE_WIDTH]
    if big_enough:
        return min(big_enough, key=_size_then_url)["url"]

    # Nothing reaches the bar, so take the best on offer rather than nothing.
    return max(pool, key=_size_then_url)["url"]


def _build_venue(raw_event: dict[str, Any]) -> Venue | None:
    venues = raw_event.get("_embedded", {}).get("venues") or []
    if not venues:
        return None
    venue = venues[0]

    name = _clean(venue.get("name"))
    if not name:
        return None

    location = venue.get("location") or {}
    return Venue(
        name=name,
        address=_clean((venue.get("address") or {}).get("line1")),
        city=_clean((venue.get("city") or {}).get("name")),
        latitude=_coerce_coordinate(location.get("latitude")),
        longitude=_coerce_coordinate(location.get("longitude")),
    )


def _build_price(raw_event: dict[str, Any]) -> Price:
    ranges = raw_event.get("priceRanges") or []
    if not ranges:
        # Absent on ~73% of events. Unknown, not free — a wrong "Free" badge on a
        # ticketed show is the costlier direction to be wrong in.
        return Price.unknown()

    standard = next((r for r in ranges if r.get("type") == "standard"), ranges[0])
    minimum = standard.get("min")
    maximum = standard.get("max")
    if minimum == 0 and maximum == 0:
        return Price.free()
    return Price(
        is_free=False,
        min=minimum,
        max=maximum,
        currency=standard.get("currency") or "USD",
    )


def _declares_foreign_timezone(raw_event: dict[str, Any]) -> str | None:
    """Return a declared timezone that contradicts the query region, if any.

    The query is a 25-mile radius around downtown Portland, which is entirely Pacific.
    An event declaring Eastern time is internally inconsistent — either its venue or
    its time is wrong upstream, and there is no way to tell which.

    This is not hypothetical: live data returns "Life Surge Charlotte", "Life Surge
    Hartford", "Life Surge Fort Myers", and "Life Surge Tampa" all tagged to the
    Oregon Convention Center with Eastern timezones. Their titles name the real cities.
    Showing a Tampa event as happening downtown is worse than omitting it.
    """
    declared = (raw_event.get("dates") or {}).get("timezone")
    if declared and declared != config.DEFAULT_TIMEZONE:
        return declared
    return None


def _primary_classification(raw_event: dict[str, Any]) -> tuple[str | None, str | None]:
    classifications = raw_event.get("classifications") or []
    if not classifications:
        return None, None
    primary = next((c for c in classifications if c.get("primary")), classifications[0])
    return (
        (primary.get("segment") or {}).get("name"),
        (primary.get("genre") or {}).get("name"),
    )


def _start_datetime(raw_event: dict[str, Any]) -> datetime | None:
    """Resolve the start instant in the event's local time.

    `dateTime` is UTC and `timezone` carries the real zone, but the latter is missing
    on roughly 37% of Portland results. Leaving those in UTC keeps the instant correct
    yet serializes a 7pm show as the following day at 02:00Z, which files it under the
    wrong date for any consumer that buckets on the date portion of the string. The
    query is scoped to 25 miles around downtown Portland, so Pacific is the right
    default rather than a guess.
    """
    start = (raw_event.get("dates") or {}).get("start") or {}
    raw = start.get("dateTime")
    if not raw:
        return None

    moment = parse_datetime(raw)
    tz_name = (raw_event.get("dates") or {}).get("timezone") or config.DEFAULT_TIMEZONE
    try:
        return moment.astimezone(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("unknown timezone %r on event %s; falling back to %s", tz_name, raw_event.get("id"), config.DEFAULT_TIMEZONE)
        return moment.astimezone(ZoneInfo(config.DEFAULT_TIMEZONE))


def normalize(raw_events: list[dict[str, Any]], *, now: datetime) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    events: list[Event] = []

    for raw in raw_events:
        if raw.get("test") is True:
            counters.test_event += 1
            continue

        dates = raw.get("dates") or {}
        status = ((dates.get("status") or {}).get("code") or "").lower()
        if status in config.EXCLUDED_STATUS_CODES:
            counters.cancelled += 1
            continue

        title = _clean(raw.get("name"))
        if not title:
            counters.no_title += 1
            continue

        if foreign := _declares_foreign_timezone(raw):
            log.info("dropping %r: declares %s but the query region is Pacific", title, foreign)
            counters.wrong_region += 1
            continue

        start_block = dates.get("start") or {}
        if start_block.get("dateTBD") or start_block.get("dateTBA"):
            counters.no_start_time += 1
            continue
        if start_block.get("timeTBA") or start_block.get("noSpecificTime"):
            # A date without a real time would render as an arbitrary hour in the feed.
            counters.time_tba += 1
            continue

        try:
            start_at = _start_datetime(raw)
        except (ValueError, TypeError) as exc:
            log.warning("event %s has unparseable start time: %s", raw.get("id"), exc)
            counters.unparseable_time += 1
            continue

        if start_at is None:
            counters.no_start_time += 1
            continue

        segment_name, genre_name = _primary_classification(raw)
        promoter = (raw.get("promoter") or {}).get("name")

        event = Event(
            id=make_event_id(config.SOURCE.id, raw["id"]),
            title=title,
            start_at=start_at,
            summary=_clean(raw.get("info")) or _clean(raw.get("pleaseNote")),
            venue=_build_venue(raw),
            categories=infer_categories(segment_name, genre_name),
            price=_build_price(raw),
            image_url=_best_image(raw.get("images")),
            listing_url=_clean(raw.get("url")),
            ticket_url=_clean(raw.get("url")),
            organizer=_clean(promoter),
            source=config.SOURCE,
        )

        if event.is_stale(now):
            counters.stale += 1
            continue

        events.append(event)

    events.sort(key=lambda e: e.start_at)
    log.info("Ticketmaster normalized %d events (%s)", len(events), counters.as_dict())
    return events, counters
