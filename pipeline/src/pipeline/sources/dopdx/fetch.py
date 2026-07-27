"""Fetch events from the DoPDX JSON API.

The API returns one calendar day per request, so a run walks the window day by day
and pages within each. `paging.total_pages` bounds the inner loop.
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


def _get(session: requests.Session, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """Return the parsed body, or None when the day is unavailable.

    A single bad day should cost that day's events, not the whole run.
    """
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
                    "X-Requested-With": "XMLHttpRequest",
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


def fetch_raw(
    *,
    now: datetime | None = None,
    session: requests.Session | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    now = now or datetime.now(UTC)
    start: date = now.date()
    client = session or requests.Session()

    collected: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    requests_made = 0
    days_failed = 0

    for offset in range(config.FETCH_WINDOW.days):
        day = start + timedelta(days=offset)
        url = config.BASE_URL + config.EVENTS_PATH.format(year=day.year, month=day.month, day=day.day)

        page = 1
        total_pages = 1
        while page <= min(total_pages, config.MAX_PAGES_PER_DAY):
            payload = _get(client, url, {"view": "list", "page": page} if page > 1 else {"view": "list"})
            requests_made += 1
            if payload is None:
                days_failed += 1
                break

            events = payload.get("events") or []
            paging = payload.get("paging") or {}
            total_pages = int(paging.get("total_pages") or 1)

            for event in events:
                # A multi-day run appears on each of its days; keep the first.
                identifier = event.get("id")
                if identifier is None or identifier in seen_ids:
                    continue
                seen_ids.add(identifier)
                collected.append(event)

            if not events:
                break
            page += 1
            time.sleep(config.SECONDS_BETWEEN_REQUESTS)

        time.sleep(config.SECONDS_BETWEEN_REQUESTS)

    if not collected:
        raise DoPDXFetchError(f"no events across {config.FETCH_WINDOW.days} days and {requests_made} requests")

    stats = {
        "collected": len(collected),
        "requests_made": requests_made,
        "days_failed": days_failed,
        "days_requested": config.FETCH_WINDOW.days,
    }
    log.info(
        "DoPDX fetched %d events over %d days in %d requests (%d day(s) failed)",
        len(collected), config.FETCH_WINDOW.days, requests_made, days_failed,
    )
    return collected, stats
