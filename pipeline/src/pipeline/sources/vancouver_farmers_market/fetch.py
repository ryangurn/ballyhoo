"""Fetch Vancouver Farmers Market occurrences. The API's shape is in `common.tribe_events`."""

from __future__ import annotations

from typing import Any

import requests

from ...common.tribe_events import TribeEvent, fetch_events
from . import config


def fetch_raw(session: requests.Session | None = None) -> tuple[list[TribeEvent], dict[str, Any]]:
    return fetch_events(
        config.EVENTS_ENDPOINT,
        seconds_between_pages=config.SECONDS_BETWEEN_PAGES,
        session=session,
    )
