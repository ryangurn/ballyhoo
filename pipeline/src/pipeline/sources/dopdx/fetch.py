"""Fetch events from the DoPDX site.

DoPDX moved to DoStuff Media's SvelteKit platform ("doxyz"); the old
`/events/Y/M/D.json` API is gone. The site's own frontend hydrates from
`<path>/__data.json`, which is what this fetcher uses:

1. The day listing — `/events/Y/M/D/__data.json?view=list&page_size=N&page=P` —
   returns one calendar day per request, paged. `browse._meta.total_pages` bounds
   the inner loop. Listing events are thin: no description, price, or venue geo.
2. Each event's detail page — `<permalink>/__data.json` — carries the fields the
   listing omits: `description`, `free_event`, `ticket_info`, `is_past`, and venue
   city/coordinates under `seo_source.venue`.

Every payload arrives in SvelteKit's "devalue" wire format: a flat array where the
first element is the root and each non-negative integer elsewhere is an index into
that same array. Negative integers are devalue's sentinels (undefined, etc.) and
are read as None.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import requests

from ...common.log import get_logger
from . import config

log = get_logger(__name__)


class DoPDXFetchError(Exception):
    """Upstream did not return usable data."""


def _unflatten(values: list[Any]) -> Any:
    """Decode SvelteKit's devalue payload: object/list values are index references."""
    cache: dict[int, Any] = {}

    def resolve(ref: Any) -> Any:
        # Dicts and arrays hold indices, not literals — but guard anyway: a stray
        # literal (bool, str, float, None) must not be read as an index. bool is a
        # subclass of int, so it is excluded explicitly.
        if not isinstance(ref, int) or isinstance(ref, bool):
            return ref
        if ref < 0:
            return None
        return hydrate(ref)

    def hydrate(index: int) -> Any:
        if index in cache:
            return cache[index]
        value = values[index]
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            cache[index] = out
            for key, ref in value.items():
                out[key] = resolve(ref)
            return out
        if isinstance(value, list):
            out_list: list[Any] = []
            cache[index] = out_list
            out_list.extend(resolve(ref) for ref in value)
            return out_list
        return value

    return hydrate(0)


def _node_data(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    """Unflatten a `__data.json` response and return the node holding `key`.

    Layout and page data ship as separate nodes whose order is not contractual,
    so the node is found by the key only its level carries — "browse" on listings,
    "event" on detail pages.
    """
    for node in payload.get("nodes") or []:
        flat = node.get("data")
        if not isinstance(flat, list) or not flat:
            continue
        # Cheap presence check before paying for the full decode.
        if not any(key in value for value in flat if isinstance(value, dict)):
            continue
        data = _unflatten(flat)
        if isinstance(data, dict) and key in data:
            return data
    return None


def _get(session: requests.Session, url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Return the parsed `__data.json` body, or None when the request fails."""
    last_error: Exception | None = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = session.get(
                url,
                params=params,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
                headers={
                    "User-Agent": config.USER_AGENT,
                    "Accept": "application/json",
                },
            )
            if response.status_code == 429:
                wait = min(2**attempt, 20)
                log.warning("rate limited; waiting %ds", wait)
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < config.MAX_RETRIES:
                time.sleep(2**attempt)

    log.warning("giving up on %s: %s", url, last_error)
    return None


def _fetch_day(
    session: requests.Session, day: date, seen_ids: set[Any]
) -> tuple[list[dict[str, Any]], int, bool]:
    """Fetch every listing page for one day. Returns (new events, requests, failed)."""
    url = config.BASE_URL + config.LISTING_PATH.format(year=day.year, month=day.month, day=day.day)
    collected: list[dict[str, Any]] = []
    requests_made = 0

    page = 1
    total_pages = 1
    while page <= min(total_pages, config.MAX_PAGES_PER_DAY):
        params: dict[str, Any] = {"view": "list", "page_size": config.PAGE_SIZE}
        if page > 1:
            params["page"] = page
        payload = _get(session, url, params)
        requests_made += 1
        if payload is None:
            return collected, requests_made, True

        browse = (_node_data(payload, "browse") or {}).get("browse") or {}
        meta = browse.get("_meta") or {}
        total_pages = int(meta.get("total_pages") or 1)

        events: list[dict[str, Any]] = []
        for group in browse.get("data") or []:
            events.extend(group.get("events") or [])

        for event in events:
            identifier = event.get("id")
            if identifier is None or identifier in seen_ids:
                continue
            seen_ids.add(identifier)
            collected.append(event)

        if not events:
            break
        page += 1
        time.sleep(config.SECONDS_BETWEEN_REQUESTS)

    return collected, requests_made, False


def _merge_venue(detail: dict[str, Any], listing_venue: dict[str, Any] | None) -> dict[str, Any]:
    """Combine the detail page's two venue objects into the shape normalize expects.

    `event.venue` has name/address/neighbourhood; `event.seo_source.venue` is the
    only place city and coordinates still appear.
    """
    venue = detail.get("venue") or listing_venue or {}
    seo = (detail.get("seo_source") or {}).get("venue") or {}
    return {
        "title": venue.get("title") or seo.get("name"),
        "address": venue.get("address") or seo.get("address"),
        "city": seo.get("city"),
        "latitude": seo.get("latitude"),
        "longitude": seo.get("longitude"),
    }


def _fetch_detail(session: requests.Session, event: dict[str, Any]) -> dict[str, Any]:
    """Overlay the detail page's fields onto the listing record.

    The listing is intentionally the base: its `category` is a name where the
    detail's is an id, and its `permalink` is what made the request possible. A
    detail that fails to load degrades to listing-only fields — the event survives
    without a summary, price, or venue geo rather than disappearing.
    """
    permalink = event.get("permalink") or ""
    if not permalink.startswith("/"):
        return event

    payload = _get(session, config.BASE_URL + permalink + config.DETAIL_SUFFIX)
    detail = (_node_data(payload, "event") or {}).get("event") if payload else None
    if not isinstance(detail, dict):
        event["venue"] = {"title": (event.get("venue") or {}).get("title")}
        return event

    listing_venue = event.get("venue")
    event.update(detail)
    # Fields the detail page lacks or degrades: the listing's values stay.
    event["permalink"] = permalink
    event["category"] = detail.get("category_name") or event.get("category")
    event["image_url"] = detail.get("poster_url") or detail.get("cover_url") or event.get("image_url")
    event["venue"] = _merge_venue(detail, listing_venue if isinstance(listing_venue, dict) else None)
    return event


def fetch_raw(
    *,
    now: datetime | None = None,
    session: requests.Session | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    now = now or datetime.now(UTC)
    start: date = now.date()
    client = session or requests.Session()

    listed: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    requests_made = 0
    days_failed = 0

    for offset in range(config.FETCH_WINDOW.days):
        day = start + timedelta(days=offset)
        events, made, failed = _fetch_day(client, day, seen_ids)
        requests_made += made
        days_failed += failed
        listed.extend(events)
        time.sleep(config.SECONDS_BETWEEN_REQUESTS)

    if not listed:
        raise DoPDXFetchError(f"no events across {config.FETCH_WINDOW.days} days and {requests_made} requests")

    collected: list[dict[str, Any]] = []
    details_failed = 0
    for event in listed:
        merged = _fetch_detail(client, event)
        if "is_past" not in merged:
            details_failed += 1
        collected.append(merged)
        requests_made += 1
        time.sleep(config.SECONDS_BETWEEN_REQUESTS)

    stats = {
        "collected": len(collected),
        "requests_made": requests_made,
        "days_failed": days_failed,
        "details_failed": details_failed,
        "days_requested": config.FETCH_WINDOW.days,
    }
    log.info(
        "DoPDX fetched %d events over %d days in %d requests (%d day(s), %d detail(s) failed)",
        len(collected), config.FETCH_WINDOW.days, requests_made, days_failed, details_failed,
    )
    return collected, stats
