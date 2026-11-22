"""Fetch events from DoPDX's SvelteKit page data.

Two passes. The day listings walk the window a day at a time and give every event's
identity, times, category, image and venue name. Each event's own page then adds what
the listing lacks — description, price, free flag, organizer and venue coordinates —
but there are ~1,500 of them, so those details are cached between runs and only a
budgeted number are fetched per run.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from ...common.log import get_logger
from . import config
from .sveltekit import SvelteKitPayloadError, find_key

log = get_logger(__name__)

CACHE_VERSION = 1


class DoPDXFetchError(Exception):
    """Upstream did not return usable data."""


def _get(session: requests.Session, url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Return the parsed body, or None when the page is unavailable.

    A single bad day or event should cost that day or event, not the whole run.
    """
    last_error: Exception | None = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = session.get(
                url,
                params=params,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
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


def _day_url(day: date) -> str:
    return config.BASE_URL + config.DAY_PATH.format(year=day.year, month=day.month, day=day.day)


def _detail_url(permalink: str) -> str | None:
    if not permalink.startswith("/events/"):
        return None
    return config.BASE_URL + permalink.rstrip("/") + config.DETAIL_SUFFIX


def _browse(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """The events on one listing page, and whether another page follows."""
    browse = find_key(payload, "browse") or {}
    events = [
        event
        for group in browse.get("data") or []
        for event in (group or {}).get("events") or []
        if isinstance(event, dict)
    ]
    meta = browse.get("_meta") or {}
    return events, bool(meta.get("has_next"))


def fetch_listings(
    session: requests.Session, start: date
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    collected: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    requests_made = 0
    days_failed = 0

    for offset in range(config.FETCH_WINDOW.days):
        day = start + timedelta(days=offset)
        url = _day_url(day)

        for page in range(1, config.MAX_PAGES_PER_DAY + 1):
            params = {"page_size": config.PAGE_SIZE}
            if page > 1:
                params["page"] = page
            payload = _get(session, url, params)
            requests_made += 1
            try:
                events, has_next = _browse(payload) if payload is not None else ([], False)
            except SvelteKitPayloadError as exc:
                log.warning("unreadable listing %s page %d: %s", url, page, exc)
                payload = None
            if payload is None:
                days_failed += 1
                break

            for event in events:
                # A multi-day run appears on each of its days; keep the first.
                identifier = event.get("id")
                if identifier is None or identifier in seen_ids:
                    continue
                seen_ids.add(identifier)
                collected.append(event)

            time.sleep(config.SECONDS_BETWEEN_REQUESTS)
            if not events or not has_next:
                break

    return collected, {"listing_requests": requests_made, "days_failed": days_failed}


def _trim_detail(event: dict[str, Any]) -> dict[str, Any]:
    """Keep only what normalization reads, so the cache stays small."""
    seo_venue = (event.get("seo_source") or {}).get("venue") or {}
    return {
        "description": event.get("description"),
        "ticket_info": event.get("ticket_info"),
        "free_event": event.get("free_event"),
        "is_past": event.get("is_past"),
        "presented_by": event.get("presented_by"),
        "venue": {
            "name": seo_venue.get("name"),
            "address": seo_venue.get("address"),
            "city": seo_venue.get("city"),
            "latitude": seo_venue.get("latitude"),
            "longitude": seo_venue.get("longitude"),
        },
    }


def fetch_detail(session: requests.Session, permalink: str) -> dict[str, Any] | None:
    url = _detail_url(permalink)
    if url is None:
        return None
    payload = _get(session, url)
    if payload is None:
        return None
    try:
        event = find_key(payload, "event")
    except SvelteKitPayloadError as exc:
        log.warning("unreadable event page %s: %s", url, exc)
        return None
    return _trim_detail(event) if isinstance(event, dict) else None


def load_cache(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    try:
        body = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        log.warning("ignoring unreadable detail cache %s: %s", path, exc)
        return {}
    if not isinstance(body, dict) or body.get("version") != CACHE_VERSION:
        return {}
    entries = body.get("events")
    return entries if isinstance(entries, dict) else {}


def save_cache(path: Path | None, entries: dict[str, dict[str, Any]]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": CACHE_VERSION, "events": entries}, separators=(",", ":")))


def _fetched_at(entry: dict[str, Any]) -> datetime:
    try:
        return datetime.fromisoformat(entry["fetched_at"])
    except (KeyError, TypeError, ValueError):
        return datetime.min.replace(tzinfo=UTC)


def plan_detail_fetches(
    listings: list[dict[str, Any]],
    cache: dict[str, dict[str, Any]],
    *,
    now: datetime,
    budget: int,
) -> list[dict[str, Any]]:
    """Which events to fetch pages for: uncached first, then the stalest cached ones."""
    missing = []
    stale = []
    for event in listings:
        entry = cache.get(str(event.get("id")))
        if entry is None:
            missing.append(event)
        elif now - _fetched_at(entry) >= config.DETAIL_REFRESH_AFTER:
            stale.append(event)
    stale.sort(key=lambda event: _fetched_at(cache[str(event.get("id"))]))
    return (missing + stale)[: max(budget, 0)]


def fetch_raw(
    *,
    now: datetime | None = None,
    session: requests.Session | None = None,
    cache_path: Path | None = None,
    detail_budget: int = config.MAX_DETAIL_REQUESTS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    now = now or datetime.now(UTC)
    client = session or requests.Session()

    listings, listing_stats = fetch_listings(client, now.date())
    if not listings:
        raise DoPDXFetchError(
            f"no events across {config.FETCH_WINDOW.days} days and {listing_stats['listing_requests']} requests"
        )

    cache = load_cache(cache_path)
    planned = plan_detail_fetches(listings, cache, now=now, budget=detail_budget)
    details_failed = 0
    for event in planned:
        detail = fetch_detail(client, event.get("permalink") or "")
        if detail is None:
            details_failed += 1
        else:
            cache[str(event["id"])] = {"fetched_at": now.isoformat(), "detail": detail}
        time.sleep(config.SECONDS_BETWEEN_REQUESTS)

    # Drop events that have left the window so the cache does not grow without bound.
    current = {str(event["id"]) for event in listings}
    cache = {key: value for key, value in cache.items() if key in current}
    save_cache(cache_path, cache)

    collected = []
    with_detail = 0
    for event in listings:
        entry = cache.get(str(event["id"]))
        if entry is not None:
            with_detail += 1
            event = {**event, "detail": entry.get("detail") or {}}
        collected.append(event)

    stats = {
        "collected": len(collected),
        **listing_stats,
        "detail_requests": len(planned),
        "details_failed": details_failed,
        "with_detail": with_detail,
        "days_requested": config.FETCH_WINDOW.days,
    }
    log.info(
        "DoPDX fetched %d events over %d days (%d listing and %d event-page requests; "
        "%d with page details, %d day(s) and %d page(s) failed)",
        len(collected), config.FETCH_WINDOW.days, listing_stats["listing_requests"], len(planned),
        with_detail, listing_stats["days_failed"], details_failed,
    )
    return collected, stats
