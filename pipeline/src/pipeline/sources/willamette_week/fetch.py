"""Fetch events from the CitySpark endpoint behind Willamette Week's Get Busy calendar.

Two behaviors here are load-bearing.

**The query is sliced into date windows.** The endpoint will not serve past its 2,025th
result and answers the request after that with `Success: false` rather than an empty
page, so an unbounded query silently stops about sixteen days out. Bounded windows
exhaust cleanly. See `config.RESULT_CEILING`.

**A `Success: false` body is fatal, not empty.** The envelope is .NET-style — the
transport says 200 while the payload says the call failed — so the only way to tell a
genuinely empty window from a rejected query is to read `Success` and `ErrorMessage`.
Treating a rejection as "no events here" would publish a feed missing whole weeks with
nothing to indicate it.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import requests

from ...common.http import USER_AGENT
from ...common.log import get_logger
from . import config

log = get_logger(__name__)


class WillametteWeekFetchError(Exception):
    """Upstream did not return usable data."""


class ResultCeilingExceeded(WillametteWeekFetchError):
    """A single date window holds more events than the endpoint will paginate through.

    Not retryable and not ignorable: everything past the ceiling is unreachable, and
    continuing would publish the prefix as though it were the whole window. The fix is
    to shorten `config.WINDOW_DAYS` so each window stays under the ceiling.
    """


def _request(session: requests.Session, body: dict[str, Any]) -> dict[str, Any]:
    """POST one page, retrying transport failures. Raises when the body says it failed."""
    last_error: Exception | None = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = session.post(
                config.EVENTS_URL,
                json=body,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
                # No Origin and no Referer, and the project User-Agent rather than a
                # browser's. Measured: this returns a byte-identical response to the
                # browser's request, so the honest headers cost nothing.
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        except requests.RequestException as exc:
            last_error = exc
        else:
            if response.status_code == 429:
                wait = min(2**attempt, 30)
                log.warning("rate limited; backing off %ds (attempt %d/%d)", wait, attempt, config.MAX_RETRIES)
                time.sleep(wait)
                continue
            try:
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
            else:
                if not isinstance(payload, dict) or "Value" not in payload:
                    raise WillametteWeekFetchError(
                        f"unrecognised response shape; expected a .NET envelope with a "
                        f"Value list, got keys {sorted(payload)[:12] if isinstance(payload, dict) else type(payload)}"
                    )
                return payload

        if attempt < config.MAX_RETRIES:
            wait = 2**attempt
            log.warning("request failed (%s); retrying in %ds", last_error, wait)
            time.sleep(wait)

    raise WillametteWeekFetchError(f"request failed after {config.MAX_RETRIES} attempts: {last_error}")


def _body(window_start: date, window_end: date, skip: int) -> dict[str, Any]:
    """The request the Get Busy widget itself sends, scoped to our radius and window.

    `start` and `end` are sent without an offset because that is what the widget sends
    and what the endpoint expects: they are local Portland wall times, matching the
    `DateStart`/`DateEnd` fields it returns rather than the `*UTC` ones.
    """
    return {
        "ppid": config.PARTNER_ID,
        "start": f"{window_start.isoformat()}T00:00",
        "end": f"{window_end.isoformat()}T23:59",
        "labels": [],
        "pick": False,
        "tps": None,
        "sparks": False,
        "sort": "Time",
        "category": [],
        "distance": config.RADIUS_MILES,
        "lat": config.LATITUDE,
        "lng": config.LONGITUDE,
        "search": "",
        "skip": skip,
        "defFilter": "all",
    }


def _fetch_window(
    session: requests.Session,
    window_start: date,
    window_end: date,
    seen: set[str],
    collected: list[dict[str, Any]],
) -> int:
    """Page one date window to exhaustion. Returns the number of requests made."""
    skip = 0
    pages = 0

    while pages < config.MAX_PAGES_PER_WINDOW:
        payload = _request(session, _body(window_start, window_end, skip))
        pages += 1

        if not payload.get("Success"):
            message = payload.get("ErrorMessage") or "(no ErrorMessage)"
            if config.CEILING_ERROR_MESSAGE.lower() in str(message).lower():
                raise ResultCeilingExceeded(
                    f"{window_start}..{window_end} holds more than the ~{config.RESULT_CEILING} "
                    f"events the endpoint will paginate through (rejected at skip={skip} with "
                    f"{message!r}). Events past that point are unreachable, so this run would "
                    f"publish a truncated window. Shorten config.WINDOW_DAYS."
                )
            raise WillametteWeekFetchError(
                f"{window_start}..{window_end} at skip={skip}: Success=false, ErrorMessage={message!r}"
            )

        events = payload.get("Value") or []
        for event in events:
            # Windows overlap at their boundaries, and a run of a recurring series
            # appears once per occurrence. `Id` is per-occurrence, so it is the right
            # key for collapsing the overlap without collapsing the series.
            identifier = event.get("Id")
            if not identifier or identifier in seen:
                continue
            seen.add(identifier)
            collected.append(event)

        if not events:
            return pages
        skip += len(events)
        time.sleep(config.SECONDS_BETWEEN_REQUESTS)

    log.warning(
        "%s..%s hit the %d-page cap; the window is larger than expected",
        window_start, window_end, config.MAX_PAGES_PER_WINDOW,
    )
    return pages


def fetch_raw(
    *,
    now: datetime | None = None,
    session: requests.Session | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return every event in the fetch window plus a small stats dict for the run report."""
    now = now or datetime.now(UTC)
    start = now.date()
    end = start + config.FETCH_WINDOW

    client = session or requests.Session()
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    requests_made = 0
    windows = 0

    window_start = start
    while window_start <= end:
        window_end = min(window_start + timedelta(days=config.WINDOW_DAYS - 1), end)
        requests_made += _fetch_window(client, window_start, window_end, seen, collected)
        windows += 1
        window_start = window_end + timedelta(days=1)
        time.sleep(config.SECONDS_BETWEEN_REQUESTS)

    if not collected:
        raise WillametteWeekFetchError(
            f"no events across {config.FETCH_WINDOW.days} days and {requests_made} requests"
        )

    stats = {
        "collected": len(collected),
        "requests_made": requests_made,
        "windows": windows,
        "days_requested": config.FETCH_WINDOW.days,
    }
    log.info(
        "Willamette Week fetched %d events over %d days in %d requests across %d window(s)",
        len(collected), config.FETCH_WINDOW.days, requests_made, windows,
    )
    return collected, stats
