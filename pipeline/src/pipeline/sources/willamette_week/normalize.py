"""Normalize CitySpark event records into the shared model.

THE TIMESTAMP TRAP
------------------
`DateStart` and `DateEnd` are Portland *local* wall times carrying a `Z` suffix they
have no right to. `StartUTC` and `EndUTC` are the true instants. The same event
measured live:

    DateStart = "2026-07-27T07:30:00Z"      <- 7:30am Portland, mislabelled as UTC
    StartUTC  = "2026-07-27T14:30:00Z"      <- the actual instant

The gap was exactly 7 hours on all 2,025 events sampled, which is Pacific daylight
time. Parsing `DateStart` as the UTC it claims to be would move every event in the feed
seven hours (eight in winter) — a 7pm show would render as noon. **Only `StartUTC` and
`EndUTC` are parsed as timestamps here.** This is the same class of bug already found
in `oregon_metro` (an offset-free field that was really UTC) and `ticketmaster` (a
missing zone that had to be defaulted); the shape differs, the cost of getting it wrong
does not.

`DateStart` is still read, once, in `listing_url` — the calendar's own permalink keys
on the local hour. That is the only correct use of it.

OTHER SHAPE NOTES FROM LIVE DATA
--------------------------------
  - `Short` is generated boilerplate, not a summary: all 2,025 sampled events began
    "The event is held on <date> at <venue> in <city>." It is never used. `Description`
    is the real text, and it is Markdown, not HTML — the widget runs it through
    Showdown. 194 of 2,025 carried Markdown syntax; none carried a tag.
  - `latitude`/`longitude` are populated on every event, so no geocoding step is
    needed. `Distance` agrees with a haversine from downtown to within 0.05 miles.
  - `IsTicketed` was `false` on all 2,025 events including ones with a ticket URL and
    a price, so it carries no information and is ignored.
  - `LowFullPrice` and `HighFullPrice` were null on all 2,025. `Price`/`PriceHigh` are
    the live pair.
  - `Occurances`, `multipleTimes`, `StartLocal`, `EndLocal` and `tzAbbrev` were
    null or empty on all 2,025. Nothing reads them.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ...common.io import parse_datetime
from ...common.log import get_logger
from ...common.models import Event, Price, Venue, make_event_id
from . import config
from .categories import infer_categories

log = get_logger(__name__)

PORTLAND = ZoneInfo("America/Los_Angeles")

# Showdown-flavoured Markdown, applied conservatively: emphasis and link syntax get
# unwrapped, everything else is left as written. Over-cleaning a description is how
# real text loses its punctuation.
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_EMPHASIS = re.compile(r"(\*{1,3}|_{2,3})(?=\S)(.+?)(?<=\S)\1", re.S)
_WHITESPACE = re.compile(r"\s+")


class NormalizationCounters:
    def __init__(self) -> None:
        self.no_start = 0
        self.unparseable_time = 0
        self.no_title = 0
        self.virtual = 0
        self.outside_radius = 0
        self.stale = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "dropped_no_start": self.no_start,
            "dropped_unparseable_time": self.unparseable_time,
            "dropped_no_title": self.no_title,
            "dropped_virtual": self.virtual,
            "dropped_outside_radius": self.outside_radius,
            "dropped_stale": self.stale,
        }


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = _MARKDOWN_LINK.sub(r"\1", value)
    text = _MARKDOWN_EMPHASIS.sub(r"\2", text)
    return _WHITESPACE.sub(" ", text).strip() or None


def _local(raw: str) -> datetime:
    """Parse a true-UTC field and render it in Portland time.

    Only ever called with `StartUTC`/`EndUTC`. The conversion is what makes an all-day
    event land on midnight local rather than 07:00 or 08:00, and it stays correct
    across the daylight-saving boundary without a hard-coded offset.
    """
    return parse_datetime(raw).astimezone(PORTLAND)


def make_id(raw: dict[str, Any], start_at: datetime) -> str:
    """Compose the published event id from the series id and the occurrence instant.

    `Id` is the obvious candidate and the wrong one. It is unique per occurrence, but
    its first six characters are the event's last-modified date: across 2,025 live
    events, the `Id` prefix matched the `lm` date 2,025 times out of 2,025. Any upstream
    edit — a fixed typo, a new image — moves `lm`, moves the `Id`, and orphans every
    bookmark against it. Ids are what bookmarks key on, so that is disqualifying.

    `PId` is the stable series identifier: a plain integer, unchanged by edits, and the
    one CitySpark's own permalink route takes (`/details/:slug/:pid/:time?`). But it is
    shared by every occurrence of a series — 2,025 events came from 1,111 distinct PIds,
    one of them repeating 27 times — so it cannot stand alone.

    Series plus occurrence instant is therefore the identity, which is also the rule
    `common/recurrence.py` already states for expanded schedules: "An occurrence's
    identity is its series plus its date." The instant is formatted from Portland local
    time so the key is the same string on either side of a daylight-saving change.

    The trade this makes is deliberate. A rescheduled event gets a new id and loses its
    bookmark; an *edited* event keeps both. Edits are routine and reschedules are rare,
    so this is the direction with far fewer broken bookmarks — the opposite of what
    using `Id` would give.
    """
    return make_event_id(config.SOURCE.id, f"{raw['PId']}@{start_at.strftime('%Y-%m-%dT%H:%M')}")


def _build_venue(raw: dict[str, Any]) -> Venue | None:
    """Coordinates are always present, so a venue is emitted even when unnamed.

    135 of 2,025 events had no `Venue` string — mostly city meetings pinned to a city
    hall. Dropping the venue would also drop the coordinates and take the event off the
    map, so the city name stands in as the name. `CityState` is always `"City, ST"`.
    """
    city_state = (raw.get("CityState") or "").strip()
    city = city_state.rsplit(",", 1)[0].strip() if "," in city_state else (city_state or None)

    name = (raw.get("Venue") or "").strip() or city
    if not name:
        return None

    latitude, longitude = raw.get("latitude"), raw.get("longitude")
    return Venue(
        name=name,
        address=_clean(raw.get("Address")),
        city=city,
        latitude=float(latitude) if isinstance(latitude, (int, float)) and latitude else None,
        longitude=float(longitude) if isinstance(longitude, (int, float)) and longitude else None,
    )


def _build_price(raw: dict[str, Any]) -> Price:
    """`Free` is authoritative; `Price`/`PriceHigh` are the low and high of a range.

    Measured over 2,025 events: 326 free (every one of them with `Price` 0), 491 priced,
    and 1,208 with no price information at all. A further 32 carry `Price: 0` with
    `Free: false` and a non-zero `PriceHigh` — a free tier alongside paid ones — and
    those are a 0-to-high range, not free. No event had `PriceHigh` below `Price`.
    """
    if raw.get("Free") is True:
        return Price.free()

    low, high = raw.get("Price"), raw.get("PriceHigh")
    if not isinstance(low, (int, float)) or isinstance(low, bool):
        # Absent on 60% of events. `PriceText` exists on a few of those as free text
        # ("$5 advance/$6 doors", "Included with daily admission") but is not parsed:
        # a misread figure shown as fact is worse than an honest absence.
        return Price.unknown()

    if not isinstance(high, (int, float)) or isinstance(high, bool):
        high = low
    return Price(is_free=False, min=float(low), max=float(max(low, high)))


def _build_image(raw: dict[str, Any]) -> str | None:
    """The first rendition on offer, largest first. See `config.IMAGE_PREFERENCE`."""
    for key in config.IMAGE_PREFERENCE:
        url = raw.get(key)
        if isinstance(url, str) and url.strip():
            return url.strip()

    images = raw.get("Images") or []
    for image in images:
        url = (image or {}).get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _build_urls(raw: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return `(listing_url, ticket_url)`.

    The tempting choice is Get Busy's own permalink, which is reconstructible from the
    payload — the widget builds `/details/{slugify(Name)}/{PId}/{DateStart[:13]}`. It is
    not used, because it does not work: that path is a client-side Vue route inside the
    embedded widget, and requesting it directly returns Willamette Week's 404 page with
    the widget script absent. Sending a user there from the app would dead-end them.

    So the organizer's own `PrimaryUrl` is the listing (present on 91% of events),
    falling back to the ticket link. An event with neither gets no link rather than a
    link to the undifferentiated calendar index.
    """
    primary = _clean(raw.get("PrimaryUrl"))
    ticket = _clean(raw.get("TicketUrl"))
    return (primary or ticket), ticket


def _is_all_day(raw: dict[str, Any]) -> bool:
    """`AllDay` alone under-reports; `HasTime` false means the clock is meaningless.

    Measured: 86 events had `HasTime: false` while only 10 had `AllDay: true`, and every
    `AllDay` event also had `HasTime: false`. Those 86 all carry a `StartUTC` of 07:00Z,
    which is midnight in Portland — a placeholder, not a 7am start.
    """
    return bool(raw.get("AllDay")) or raw.get("HasTime") is False


def normalize(raw_events: list[dict[str, Any]], *, now: datetime) -> tuple[list[Event], NormalizationCounters]:
    counters = NormalizationCounters()
    events: list[Event] = []

    for raw in raw_events:
        title = _clean(raw.get("Name"))
        if not title:
            counters.no_title += 1
            continue

        if config.DROP_VIRTUAL and raw.get("isVirtual") is True:
            counters.virtual += 1
            continue

        # The request already asks for this radius; re-checking means a change to how
        # the parameter is honoured shows up as dropped events rather than as a feed
        # that quietly grew to cover Salem.
        distance = raw.get("Distance")
        if isinstance(distance, (int, float)) and distance > config.RADIUS_MILES:
            counters.outside_radius += 1
            continue

        start_raw = raw.get("StartUTC")
        if not start_raw:
            counters.no_start += 1
            continue

        try:
            start_at = _local(start_raw)
        except (ValueError, TypeError) as exc:
            log.warning("event %s has an unparseable StartUTC %r: %s", raw.get("PId"), start_raw, exc)
            counters.unparseable_time += 1
            continue

        end_at = None
        if raw.get("EndUTC"):
            try:
                end_at = _local(raw["EndUTC"])
            except (ValueError, TypeError):
                log.warning("event %s has an unparseable EndUTC %r", raw.get("PId"), raw.get("EndUTC"))

        if raw.get("PId") is None:
            # PId is the identity; without it there is nothing stable to bookmark.
            log.warning("event %r has no PId; skipping", title)
            counters.no_title += 1
            continue

        listing_url, ticket_url = _build_urls(raw)
        event = Event(
            id=make_id(raw, start_at),
            title=title,
            start_at=start_at,
            end_at=end_at,
            is_all_day=_is_all_day(raw),
            summary=_clean(raw.get("Description")),
            venue=_build_venue(raw),
            categories=infer_categories(raw.get("Tags")),
            price=_build_price(raw),
            image_url=_build_image(raw),
            listing_url=listing_url,
            ticket_url=ticket_url,
            source=config.SOURCE,
        )

        if event.is_stale(now):
            counters.stale += 1
            continue

        events.append(event)

    # A series can list two occurrences at the same instant under one PId, which would
    # collide on id. Keep the first and count the rest, rather than publishing
    # duplicate ids the client would decode over the top of each other.
    unique: dict[str, Event] = {}
    for event in events:
        unique.setdefault(event.id, event)
    collisions = len(events) - len(unique)
    if collisions:
        log.info("collapsed %d event(s) sharing a series id and start time", collisions)

    result = sorted(unique.values(), key=lambda e: e.start_at)
    log.info("Willamette Week normalized %d events (%s)", len(result), counters.as_dict())
    return result, counters
