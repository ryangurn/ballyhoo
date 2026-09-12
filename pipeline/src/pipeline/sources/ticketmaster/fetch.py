"""Fetch Portland events from the Ticketmaster Discovery API.

Two behaviors here are load-bearing and easy to get wrong:

No `segmentName` parameter is sent. Passing an exhaustive list of all six segments
measurably returns fewer events (503) than passing none (548), so any allow-list —
even a complete one — silently drops events.

The API will not serve past the 1000th result of any one query and truncates without
an error. Every response carries `page.totalElements` for the range it was asked
about, so a range is only paginated once that number is known to be reachable, and a
range too large to page through is bisected rather than truncated.

Date is the only safe axis to slice on. Every event has exactly one start date, so
cutting the window at an instant partitions the results instead of resampling them —
the twelve 30-day slices of the 2026-09-12 window summed to exactly the 929 the
unsliced query reported, and agreed with it at every intermediate horizon.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from ...common.log import get_logger, register_secret
from . import config

log = get_logger(__name__)


class TicketmasterFetchError(Exception):
    """Upstream did not return usable data."""


class DeepPagingLimitExceeded(TicketmasterFetchError):
    """One date range holds more events than the API is willing to paginate through.

    Raised only once bisection has run out of room: a range already down to
    `config.MIN_SLICE` that is still over the guard cannot be cut any finer. Not
    retryable and not ignorable, because continuing would publish a feed that looks
    complete but is missing events, with nothing anywhere to indicate it. Slicing by
    segment is not the escape hatch — it loses events of its own.
    """


def _request(session: requests.Session, params: dict[str, Any]) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = session.get(
                config.EVENTS_URL,
                params=params,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
                headers={"Accept": "application/json", "User-Agent": "ballyhoo-pipeline/0.1"},
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


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _absorb(payload: dict[str, Any], seen: set[str], collected: list[dict[str, Any]]) -> int:
    """Take one page's events into the accumulator, skipping any already held.

    Returns how many events the page carried before deduplication, since that — not
    how many were new — is what says whether another page is worth asking for.
    """
    events = payload.get("_embedded", {}).get("events", [])
    for event in events:
        identifier = event.get("id")
        if identifier is not None:
            if identifier in seen:
                continue
            seen.add(identifier)
        collected.append(event)
    return len(events)


def _collect_slice(
    session: requests.Session,
    base_params: dict[str, Any],
    start: datetime,
    end: datetime,
    seen: set[str],
    collected: list[dict[str, Any]],
    stats: dict[str, int],
) -> None:
    """Page one date range to exhaustion, bisecting it first if it is too large.

    The range is asked about before it is trusted: the first response reports how many
    events it matches, which is what decides between paging it and splitting it.
    """
    window = {"startDateTime": _stamp(start), "endDateTime": _stamp(end)}
    payload = _request(session, {**base_params, **window, "page": 0})
    stats["requests_made"] += 1

    page_info = payload.get("page", {})
    total_elements = int(page_info.get("totalElements", 0))

    if total_elements > config.SLICE_ELEMENTS_GUARD:
        span = end - start
        if span <= config.MIN_SLICE:
            raise DeepPagingLimitExceeded(
                f"{_stamp(start)}..{_stamp(end)} matches {total_elements} events, above the "
                f"{config.SLICE_ELEMENTS_GUARD} guard, and is already down to "
                f"{config.MIN_SLICE.days} day(s), so it cannot be sliced any finer. The API "
                f"will not paginate past {config.DEEP_PAGING_LIMIT} results and truncates "
                f"silently, so this run would publish an incomplete feed."
            )

        midpoint = start + span / 2
        log.info(
            "%s..%s matches %d events, above the %d guard; splitting at %s",
            _stamp(start), _stamp(end), total_elements, config.SLICE_ELEMENTS_GUARD, _stamp(midpoint),
        )
        _collect_slice(session, base_params, start, midpoint, seen, collected, stats)
        # Upstream treats both endpoints as inclusive, so the halves start a second
        # apart to keep them disjoint. Timestamps are second-granular, so nothing
        # falls between them.
        _collect_slice(session, base_params, midpoint + timedelta(seconds=1), end, seen, collected, stats)
        return

    stats["slices"] += 1
    stats["total_elements"] += total_elements
    stats["largest_slice"] = max(stats["largest_slice"], total_elements)

    total_pages = int(page_info.get("totalPages", 0))
    page = 0
    while True:
        carried = _absorb(payload, seen, collected)
        page += 1
        if page >= total_pages or not carried:
            break
        if page * config.PAGE_SIZE >= config.DEEP_PAGING_LIMIT:
            # Unreachable while the guard sits below the ceiling, and kept for the day
            # someone raises it past: the alternative is truncating in silence.
            log.warning("stopping at the API's deep-paging boundary after %d events", len(collected))
            break

        time.sleep(config.MIN_SECONDS_BETWEEN_REQUESTS)
        payload = _request(session, {**base_params, **window, "page": page})
        stats["requests_made"] += 1


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
        "size": config.PAGE_SIZE,
        "sort": "date,asc",
    }
    if config.SEGMENT_NAMES:
        base_params["segmentName"] = ",".join(config.SEGMENT_NAMES)

    client = session or requests.Session()
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    stats = {"requests_made": 0, "slices": 0, "total_elements": 0, "largest_slice": 0}

    # The whole window is tried first, so a quiet Portland still costs one query and
    # slicing only appears when it is needed.
    _collect_slice(client, base_params, now, end, seen, collected, stats)

    stats["collected"] = len(collected)
    log.info(
        "Ticketmaster fetched %d events in %d requests across %d slice(s); largest slice matched %d",
        len(collected), stats["requests_made"], stats["slices"], stats["largest_slice"],
    )
    return collected, stats
