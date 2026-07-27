"""Fetch Eventbrite's free-events discovery pages and read the embedded results.

The page ships its own search results inline, ahead of hydration:

    window.__SERVER_DATA__ = {"app_name":"discover","search_data":{
      "event_search":{"dates":"current_future","places":["101715829"],"price":"free",...},
      "events":{"pagination":{"object_count":910,"page_count":46,"page_number":1,...},
                "results":[{"id":"1993877033882","name":"...", ...}]}}}

`event_search` is the query the server actually applied, echoed back. That is the
load-bearing detail for this source: it lets every run *verify* that the free filter
and the Portland place filter were in effect, instead of trusting that the URL we
asked for is the search we got. A page that does not echo both is dropped rather than
normalized, because its events would be labelled free on no evidence.

Results carry no `is_free` field of their own — free-ness is a property of the query,
not of the record — which is exactly why the echo matters.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import requests

from ...common.log import get_logger
from . import config

log = get_logger(__name__)


class EventbriteFetchError(Exception):
    """Upstream did not return usable data."""


@dataclass(frozen=True)
class RawEventbriteVenue:
    name: str | None
    address: str | None
    city: str | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class RawEventbriteEvent:
    event_id: str
    name: str
    summary: str | None
    start_date: str
    start_time: str | None
    end_date: str | None
    end_time: str | None
    timezone: str | None
    url: str | None
    tickets_url: str | None
    image_url: str | None
    category: str | None
    is_online: bool
    is_cancelled: bool
    venue: RawEventbriteVenue | None


@dataclass(frozen=True)
class PageMeta:
    """What the server said about the query it ran for this page."""

    price_filter: str | None
    place_ids: tuple[str, ...]
    page_number: int | None
    page_count: int | None
    object_count: int | None

    @property
    def free_filter_applied(self) -> bool:
        return self.price_filter == config.REQUIRED_PRICE_FILTER

    @property
    def place_filter_applied(self) -> bool:
        return config.EXPECTED_PLACE_ID in self.place_ids


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def extract_server_data(html: str) -> dict[str, Any]:
    """Pull the embedded JSON out of the page.

    The blob is followed by more JavaScript on the same line, so it cannot be read
    with a delimiter search; `raw_decode` stops at the end of the object.
    """
    index = html.find(config.SERVER_DATA_MARKER)
    if index < 0:
        raise EventbriteFetchError(
            "no __SERVER_DATA__ in the page; Eventbrite likely stopped embedding results server-side"
        )
    start = index + len(config.SERVER_DATA_MARKER)
    try:
        payload, _ = json.JSONDecoder().raw_decode(html[start:])
    except ValueError as exc:
        raise EventbriteFetchError(f"__SERVER_DATA__ was not decodable JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise EventbriteFetchError(f"__SERVER_DATA__ was {type(payload).__name__}, expected an object")
    return payload


def _parse_venue(payload: Any) -> RawEventbriteVenue | None:
    venue = _as_dict(payload)
    if not venue:
        return None
    address = _as_dict(venue.get("address"))
    name = _clean(venue.get("name"))
    display = _clean(address.get("localized_address_display"))
    if not (name or display):
        return None
    return RawEventbriteVenue(
        name=name,
        address=display,
        city=_clean(address.get("city")),
        latitude=_float_or_none(address.get("latitude")),
        longitude=_float_or_none(address.get("longitude")),
    )


def _primary_category(tags: Any) -> str | None:
    for tag in tags or []:
        if isinstance(tag, dict) and tag.get("prefix") == "EventbriteCategory":
            return _clean(tag.get("display_name"))
    return None


def parse_page(html: str) -> tuple[list[RawEventbriteEvent], PageMeta]:
    data = extract_server_data(html)
    search = _as_dict(data.get("search_data"))
    query = _as_dict(search.get("event_search"))
    events_block = _as_dict(search.get("events"))
    pagination = _as_dict(events_block.get("pagination"))

    meta = PageMeta(
        price_filter=_clean(query.get("price")),
        place_ids=tuple(str(p) for p in (query.get("places") or []) if p is not None),
        page_number=pagination.get("page_number"),
        page_count=pagination.get("page_count"),
        object_count=pagination.get("object_count"),
    )

    events: list[RawEventbriteEvent] = []
    for item in events_block.get("results") or []:
        if not isinstance(item, dict):
            continue
        event_id = _clean(item.get("id")) or _clean(item.get("eventbrite_event_id"))
        name = _clean(item.get("name"))
        start_date = _clean(item.get("start_date"))
        if not (event_id and name and start_date):
            continue

        events.append(
            RawEventbriteEvent(
                event_id=event_id,
                name=name,
                summary=_clean(item.get("summary")),
                start_date=start_date,
                start_time=_clean(item.get("start_time")),
                end_date=_clean(item.get("end_date")),
                end_time=_clean(item.get("end_time")),
                timezone=_clean(item.get("timezone")),
                url=_clean(item.get("url")),
                tickets_url=_clean(item.get("tickets_url")),
                image_url=_clean(_as_dict(item.get("image")).get("url")),
                category=_primary_category(item.get("tags")),
                is_online=bool(item.get("is_online_event")),
                is_cancelled=bool(item.get("is_cancelled")),
                venue=_parse_venue(item.get("primary_venue")),
            )
        )

    return events, meta


def fetch_raw(session: requests.Session | None = None) -> tuple[list[RawEventbriteEvent], dict[str, Any]]:
    client = session or requests.Session()
    collected: list[RawEventbriteEvent] = []
    seen_ids: set[str] = set()
    pages_read = 0
    pages_rejected = 0

    for page in range(1, config.MAX_PAGES + 1):
        last_error: Exception | None = None
        parsed: tuple[list[RawEventbriteEvent], PageMeta] | None = None

        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                response = client.get(
                    config.SEARCH_URL,
                    params={"page": page},
                    timeout=config.REQUEST_TIMEOUT_SECONDS,
                    headers={"User-Agent": config.USER_AGENT, "Accept": "text/html"},
                )
                response.raise_for_status()
                parsed = parse_page(response.text)
                break
            except (requests.RequestException, EventbriteFetchError) as exc:
                last_error = exc
                if attempt < config.MAX_RETRIES:
                    time.sleep(2**attempt)

        if parsed is None:
            if page == 1:
                raise EventbriteFetchError(f"could not read the first page: {last_error}")
            log.warning("stopping at page %d after repeated failures: %s", page, last_error)
            break

        batch, meta = parsed
        pages_read += 1

        # The filters are the only evidence these events are free and in Portland.
        # Without both echoed back, the page's events are unusable, not merely suspect.
        if not meta.free_filter_applied or not meta.place_filter_applied:
            pages_rejected += 1
            message = (
                f"page {page} did not echo the expected filters "
                f"(price={meta.price_filter!r}, places={list(meta.place_ids)}); discarding it"
            )
            if page == 1:
                raise EventbriteFetchError(message)
            log.warning("%s", message)
            continue

        # An empty result list is the only reliable end-of-results signal. A *short*
        # page is not: Eventbrite applies its series dedup after slicing the page, so
        # a mid-run page routinely comes back with 17 or 19 of the nominal 20 while
        # plenty of pages follow. Stopping on a short page truncated the crawl at 97
        # events instead of the ~600 that are actually there.
        if not batch:
            break

        fresh = [e for e in batch if e.event_id not in seen_ids]
        if not fresh:
            break
        seen_ids.update(e.event_id for e in fresh)
        collected.extend(fresh)

        time.sleep(config.SECONDS_BETWEEN_PAGES)

    stats = {"pages_read": pages_read, "pages_rejected": pages_rejected, "collected": len(collected)}
    log.info("Eventbrite read %d page(s), %d events (%d page(s) discarded)", pages_read, len(collected), pages_rejected)
    return collected, stats
