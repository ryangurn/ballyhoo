"""Fetch Portland events from Eventbrite's destination search endpoint.

The request the discovery UI makes, replicated:

    POST /api/v3/destination/search/
    Referer: https://www.eventbrite.com/d/or--portland/events/
    X-CSRFToken: <the csrftoken cookie>
    {"event_search": {"places": ["101715829"],
                      "date_range": {"from": "2026-07-27", "to": "2026-08-02"},
                      "price": "free", "dedup": true, "page_size": 50, "page": 1},
     "expand.destination_event": ["ticket_availability", "primary_venue", ...]}

A run crosses two axes: the fetch window sliced into weeks, and two price filters
(unfiltered, then free-only). Every slice is paged to exhaustion and everything is
deduplicated by Eventbrite's event id, which is what makes the overlap between the two
passes harmless.

Slicing exists because results are capped at 1,000 per query and ordered by relevance
rather than date — a single month-wide query would quietly return its top 1,000 and
drop the rest. A week is small enough that the cap never binds.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import requests

from ...common.http import USER_AGENT
from ...common.log import get_logger
from . import config

log = get_logger(__name__)


class EventbriteFetchError(Exception):
    """Upstream did not return usable data."""


@dataclass(frozen=True, slots=True)
class RawVenue:
    name: str | None
    address: str | None
    city: str | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True, slots=True)
class RawPrice:
    """Eventbrite's own statement about cost, not our reading of it.

    `is_free` is absent rather than False when the expansion did not come back, so the
    three states — free, paid, unstated — stay distinguishable all the way to `Price`.
    """

    is_free: bool | None
    minimum: float | None
    maximum: float | None
    currency: str | None
    is_sold_out: bool


@dataclass(frozen=True, slots=True)
class RawEvent:
    event_id: str
    name: str
    summary: str | None
    start_date: str
    start_time: str | None
    end_date: str | None
    end_time: str | None
    timezone: str | None
    url: str | None
    image_url: str | None
    category: str | None
    event_format: str | None
    organizer: str | None
    is_online: bool
    is_cancelled: bool
    venue: RawVenue | None
    price: RawPrice
    # Whether this event came back under the `price=free` query. Corroborates
    # `price.is_free` rather than replacing it; the two are cross-checked per run.
    matched_free_filter: bool


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(payload: Any) -> float | None:
    """Read a `{"major_value": "12.00", "value": 1200, ...}` amount.

    `major_value` is the dollars form and is what we want; `value` is minor units and
    reading it by mistake would put $1,200 on a $12 event.
    """
    return _float_or_none(_as_dict(payload).get("major_value"))


def _tag(tags: Any, prefix: str) -> str | None:
    for tag in tags or []:
        if isinstance(tag, dict) and tag.get("prefix") == prefix:
            return _clean(tag.get("display_name"))
    return None


def _pick_image(payload: Any) -> str | None:
    """Choose the largest pre-signed rendition at or below card size.

    Never `original` and never the bare `url`: both can be 2,500px wide, which decodes
    to well over 10 MB and is what crashed the app on Ticketmaster artwork. The URLs are
    signature-locked, so rewriting `w=` to an arbitrary width is not an option — it 403s.
    """
    sizes = _as_dict(_as_dict(payload).get("image_sizes"))
    for rendition in config.IMAGE_RENDITIONS:
        if url := _clean(sizes.get(rendition)):
            return url
    return None


def _parse_venue(payload: Any) -> RawVenue | None:
    venue = _as_dict(payload)
    address = _as_dict(venue.get("address"))
    name = _clean(venue.get("name"))
    display = _clean(address.get("localized_address_display"))
    if not (name or display):
        return None
    return RawVenue(
        name=name,
        address=display,
        city=_clean(address.get("city")),
        # Coordinates arrive as strings, e.g. "45.5599584".
        latitude=_float_or_none(address.get("latitude")),
        longitude=_float_or_none(address.get("longitude")),
    )


def _parse_price(payload: Any) -> RawPrice:
    availability = _as_dict(payload)
    is_free = availability.get("is_free")
    return RawPrice(
        is_free=is_free if isinstance(is_free, bool) else None,
        minimum=_money(availability.get("minimum_ticket_price")),
        maximum=_money(availability.get("maximum_ticket_price")),
        currency=_clean(_as_dict(availability.get("minimum_ticket_price")).get("currency")),
        is_sold_out=bool(availability.get("is_sold_out")),
    )


def parse_result(item: Any, *, matched_free_filter: bool) -> RawEvent | None:
    """Turn one search hit into a raw record, or None if it is unusable."""
    result = _as_dict(item)
    event_id = _clean(result.get("id")) or _clean(result.get("eventbrite_event_id"))
    name = _clean(result.get("name"))
    start_date = _clean(result.get("start_date"))
    if not (event_id and name and start_date):
        return None

    return RawEvent(
        event_id=event_id,
        name=name,
        summary=_clean(result.get("summary")),
        start_date=start_date,
        start_time=_clean(result.get("start_time")),
        end_date=_clean(result.get("end_date")),
        end_time=_clean(result.get("end_time")),
        timezone=_clean(result.get("timezone")),
        url=_clean(result.get("url")),
        image_url=_pick_image(result.get("image")),
        category=_tag(result.get("tags"), "EventbriteCategory"),
        event_format=_tag(result.get("tags"), "EventbriteFormat"),
        organizer=_clean(_as_dict(result.get("primary_organizer")).get("name")),
        is_online=bool(result.get("is_online_event")),
        is_cancelled=bool(result.get("is_cancelled")),
        venue=_parse_venue(result.get("primary_venue")),
        price=_parse_price(result.get("ticket_availability")),
        matched_free_filter=matched_free_filter,
    )


def _bootstrap(session: requests.Session) -> str:
    """Load a discovery page for its `csrftoken` cookie.

    The search endpoint is CSRF-guarded rather than authenticated: any anonymous page
    load hands out a usable token. No account or API key is involved.
    """
    try:
        response = session.get(
            config.DISCOVERY_URL,
            timeout=config.REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise EventbriteFetchError(f"could not load {config.DISCOVERY_URL} to obtain a CSRF token: {exc}") from exc

    token = session.cookies.get("csrftoken")
    if not token:
        raise EventbriteFetchError(
            "no csrftoken cookie on the discovery page; Eventbrite's CSRF scheme has changed "
            "and the search endpoint will reject every request"
        )
    return token


def date_windows(start: date, *, window: timedelta, stride: timedelta) -> Iterator[tuple[date, date]]:
    """Slice the fetch window into inclusive [from, to] ranges."""
    end = start + window
    cursor = start
    while cursor < end:
        last = min(cursor + stride - timedelta(days=1), end)
        yield cursor, last
        cursor = last + timedelta(days=1)


class _Client:
    """Holds the session and the CSRF token, re-bootstrapping if the token goes stale."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.token = _bootstrap(self.session)
        self.requests_made = 0

    def search(self, event_search: dict[str, Any]) -> dict[str, Any] | None:
        """Return one page of results, or None when the page is unavailable.

        A single bad page costs that page, not the run.
        """
        body = {
            "event_search": event_search,
            "expand.destination_event": list(config.EXPAND_FIELDS),
        }
        last_error: Exception | None = None

        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                self.requests_made += 1
                response = self.session.post(
                    config.SEARCH_URL,
                    json=body,
                    timeout=config.REQUEST_TIMEOUT_SECONDS,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        # Both are load-bearing: the endpoint rejects the POST without
                        # a same-origin Referer *and* the cookie echoed as a header.
                        "Referer": config.DISCOVERY_URL,
                        "X-CSRFToken": self.token,
                    },
                )
                if response.status_code == 429:
                    wait = min(2**attempt, 20)
                    log.warning("rate limited; waiting %ds", wait)
                    time.sleep(wait)
                    continue
                if response.status_code in (401, 403):
                    # Tokens rotate. Get a fresh one and let the retry use it.
                    log.warning("search returned %d; refreshing the CSRF token", response.status_code)
                    self.token = _bootstrap(self.session)
                    last_error = EventbriteFetchError(f"HTTP {response.status_code}")
                    continue
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < config.MAX_RETRIES:
                    time.sleep(2**attempt)

        log.warning("giving up on a search page: %s", last_error)
        return None


def fetch_raw(
    *,
    now: datetime | None = None,
    session: requests.Session | None = None,
) -> tuple[list[RawEvent], dict[str, Any]]:
    now = now or datetime.now(UTC)
    client = _Client(session)

    collected: dict[str, RawEvent] = {}
    pages_failed = 0
    ceiling_hit = 0
    per_filter: dict[str, int] = {}

    windows = list(date_windows(now.date(), window=config.FETCH_WINDOW, stride=config.WINDOW_STRIDE))

    for price_filter in config.PRICE_FILTERS:
        label = price_filter or "any"
        before = len(collected)

        for window_start, window_end in windows:
            for page in range(1, config.MAX_PAGES_PER_WINDOW + 1):
                event_search: dict[str, Any] = {
                    "places": [config.PORTLAND_PLACE_ID],
                    "date_range": {"from": window_start.isoformat(), "to": window_end.isoformat()},
                    # Collapses a recurring series to its next occurrence instead of
                    # returning every instance separately.
                    "dedup": True,
                    "page_size": config.PAGE_SIZE,
                    "page": page,
                }
                if price_filter:
                    event_search["price"] = price_filter

                payload = client.search(event_search)
                if payload is None:
                    pages_failed += 1
                    break

                results = (_as_dict(payload.get("events")).get("results")) or []
                for item in results:
                    raw = parse_result(item, matched_free_filter=price_filter == "free")
                    if raw is None:
                        continue
                    existing = collected.get(raw.event_id)
                    if existing is None:
                        collected[raw.event_id] = raw
                    elif raw.matched_free_filter and not existing.matched_free_filter:
                        # Seen in both passes; remember that the free filter claimed it.
                        collected[raw.event_id] = replace(existing, matched_free_filter=True)

                # An empty page is the only reliable end-of-results marker. `page_count`
                # is an Elasticsearch estimate that disagrees with reality in both
                # directions — it claimed 19 pages for a window that served 20 full ones.
                if not results:
                    break
                if page == config.MAX_PAGES_PER_WINDOW:
                    # A window that fills the 1,000-result cap is being truncated, and
                    # the stride needs shortening. Worth knowing before it loses much.
                    ceiling_hit += 1
                    log.warning(
                        "window %s..%s filled the %d-result ceiling; some events were not reachable",
                        window_start, window_end, config.RESULT_CEILING,
                    )

                time.sleep(config.SECONDS_BETWEEN_REQUESTS)

        per_filter[label] = len(collected) - before

    if not collected:
        raise EventbriteFetchError(
            f"no events across {len(windows)} window(s) and {client.requests_made} requests"
        )

    stats = {
        "collected": len(collected),
        "new_by_filter": per_filter,
        "windows": len(windows),
        "requests_made": client.requests_made,
        "pages_failed": pages_failed,
        "windows_at_ceiling": ceiling_hit,
    }
    log.info(
        "Eventbrite fetched %d unique events over %d window(s) in %d requests (%d page(s) failed)",
        len(collected), len(windows), client.requests_made, pages_failed,
    )
    return list(collected.values()), stats
