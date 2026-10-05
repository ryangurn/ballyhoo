"""Fetch the Hillsboro Farmers' Markets events page. Its markup is in `common.squarespace`."""

from __future__ import annotations

import time
from typing import Any

import requests

from ...common.http import HTML_HEADERS
from ...common.log import get_logger
from ...common.squarespace import EventListItem, parse_event_list
from . import config

log = get_logger(__name__)


class HillsboroFetchError(Exception):
    """Upstream did not return usable data."""


def fetch_raw(session: requests.Session | None = None) -> tuple[list[EventListItem], dict[str, Any]]:
    client = session or requests.Session()
    last_error: Exception | None = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = client.get(config.EVENTS_URL, timeout=config.REQUEST_TIMEOUT_SECONDS, headers=HTML_HEADERS)
            response.raise_for_status()
            items = parse_event_list(response.text, base_url=config.BASE_URL)
            if not items:
                # The page always lists at least the recent past, so an empty parse
                # means the markup changed rather than the markets stopping.
                raise HillsboroFetchError("the events page contained no event items")
            log.info("Hillsboro Farmers' Markets events page listed %d item(s)", len(items))
            return items, {"collected": len(items)}
        except (requests.RequestException, HillsboroFetchError) as exc:
            last_error = exc
            if attempt < config.MAX_RETRIES:
                time.sleep(2**attempt)

    raise HillsboroFetchError(f"could not read the events page: {last_error}")
