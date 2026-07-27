"""Fetch Portland events from the Ticketmaster Discovery API.

Two behaviors here are load-bearing and easy to get wrong:

No `segmentName` parameter is sent. Passing an exhaustive list of all six segments
measurably returns fewer events (503) than passing none (548), so any allow-list —
even a complete one — silently drops events.

The API will not serve past the 1000th result and truncates without an error. The
first response carries `page.totalElements`, so the run aborts there rather than
quietly publishing a partial feed.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import requests

from ...common.log import get_logger, register_secret
from . import config

log = get_logger(__name__)


class TicketmasterFetchError(Exception):
    """Upstream did not return usable data."""


class DeepPagingLimitExceeded(TicketmasterFetchError):
    """More matching events exist than the API is willing to paginate through.

    Not retryable and not ignorable: continuing would publish a feed that looks
    complete but is missing events, with nothing anywhere to indicate it. The fix is
    to slice the query by date range — never by segment, which loses events of its own.
    """


def _request(session: requests.Session, params: dict[str, Any]) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = session.get(
                config.EVENTS_URL,
                params=params,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
                headers={"Accept": "application/json", "User-Agent": "sociallist-pipeline/0.1"},
            )
        except requests.RequestException as exc:
            last_error = exc
        else:
            if response.status_code == 429:
                # Their quota headers say when it resets, but a plain backoff is
                # sufficient at our request volume.
                wait = min(2**attempt, 30)
                log.warning("rate limited; backing off %ds (attempt %d/%d)", wait, attempt, config.MAX_RETRIES)
                time.sleep(wait)
                continue
            if response.status_code == 401:
                raise TicketmasterFetchError(
                    "Ticketmaster rejected the API key (401). Check TICKETMASTER_API_KEY."
                )
            try:
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc

        if attempt < config.MAX_RETRIES:
            wait = 2**attempt
            log.warning("request failed (%s); retrying in %ds", last_error, wait)
            time.sleep(wait)

    raise TicketmasterFetchError(f"Ticketmaster request failed after {config.MAX_RETRIES} attempts: {last_error}")


def fetch_raw(
    api_key: str,
    *,
    now: datetime | None = None,
    session: requests.Session | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return every matching event plus a small stats dict for the run report."""
    register_secret(api_key)
    now = now or datetime.now(UTC)
    end = now + config.FETCH_WINDOW

    base_params: dict[str, Any] = {
        "apikey": api_key,
        "latlong": f"{config.LATITUDE},{config.LONGITUDE}",
        "radius": config.RADIUS_MILES,
        "unit": "miles",
        "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "size": config.PAGE_SIZE,
        "sort": "date,asc",
    }
    if config.SEGMENT_NAMES:
        base_params["segmentName"] = ",".join(config.SEGMENT_NAMES)

    client = session or requests.Session()
    collected: list[dict[str, Any]] = []
    total_elements: int | None = None
    requests_made = 0
    page = 0

    while True:
        payload = _request(client, {**base_params, "page": page})
        requests_made += 1

        page_info = payload.get("page", {})
        if total_elements is None:
            total_elements = int(page_info.get("totalElements", 0))
            log.info("Ticketmaster reports %d matching events", total_elements)
            if total_elements > config.TOTAL_ELEMENTS_GUARD:
                raise DeepPagingLimitExceeded(
                    f"{total_elements} events match, above the {config.TOTAL_ELEMENTS_GUARD} guard. "
                    f"The API will not paginate past {config.DEEP_PAGING_LIMIT} results and truncates "
                    f"silently, so this run would publish an incomplete feed. Slice the query by date "
                    f"range in config.FETCH_WINDOW rather than by segment."
                )

        events = payload.get("_embedded", {}).get("events", [])
        collected.extend(events)

        total_pages = int(page_info.get("totalPages", 0))
        page += 1
        if page >= total_pages or not events:
            break
        if page * config.PAGE_SIZE >= config.DEEP_PAGING_LIMIT:
            log.warning("stopping at the API's deep-paging boundary after %d events", len(collected))
            break

        time.sleep(config.MIN_SECONDS_BETWEEN_REQUESTS)

    stats = {
        "total_elements": total_elements or 0,
        "collected": len(collected),
        "requests_made": requests_made,
    }
    log.info("Ticketmaster fetched %d events in %d requests", len(collected), requests_made)
    return collected, stats
