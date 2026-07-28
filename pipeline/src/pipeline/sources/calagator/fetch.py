"""Fetch raw events from Calagator.

The endpoint returns a bare JSON array — no envelope, no pagination, no total count.
A date range is supported via `date[start]` / `date[end]` and roughly doubles the
result set versus the unfiltered default.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import requests

from ...common.log import get_logger
from . import config

log = get_logger(__name__)


class CalagatorFetchError(Exception):
    """Upstream did not return usable data."""


def fetch_raw(*, now: datetime | None = None, session: requests.Session | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(UTC)
    end = now + config.FETCH_WINDOW
    params = {
        "date[start]": now.date().isoformat(),
        "date[end]": end.date().isoformat(),
    }

    client = session or requests.Session()
    last_error: Exception | None = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = client.get(
                config.EVENTS_URL,
                params=params,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
                headers={"Accept": "application/json", "User-Agent": "ballyhoo-pipeline/0.1"},
            )
            response.raise_for_status()
            payload = response.json()
            break
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt == config.MAX_RETRIES:
                raise CalagatorFetchError(f"Calagator fetch failed after {attempt} attempts: {exc}") from exc
            backoff = 2**attempt
            log.warning("Calagator attempt %d/%d failed (%s); retrying in %ds", attempt, config.MAX_RETRIES, exc, backoff)
            time.sleep(backoff)
    else:  # pragma: no cover - loop always breaks or raises
        raise CalagatorFetchError(f"Calagator fetch failed: {last_error}")

    if not isinstance(payload, list):
        raise CalagatorFetchError(f"expected a JSON array from Calagator, got {type(payload).__name__}")

    log.info("Calagator returned %d raw events for %s..%s", len(payload), params["date[start]"], params["date[end]"])
    return payload
