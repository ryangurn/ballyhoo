"""Fetch and parse the Summer Free For All schedule table.

Each row looks like:

    <tr>
      <th>July 10<br>7:30pm</th>
      <td>Movie</td>
      <td><em><strong>Elio</strong></em> (2025) PG - English with Spanish subtitles</td>
      <td><a href="...">King School Park</a></td>
    </tr>

The date is a `<th>`, so the three `<td>` cells are type, event, and location.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup, Tag

from ...common.log import get_logger
from . import config

log = get_logger(__name__)


class ParksFetchError(Exception):
    """Upstream did not return usable data."""


class ScheduleLayoutChanged(ParksFetchError):
    """The table no longer matches the expected columns.

    Raised rather than guessing: reading the wrong column would put a venue name in
    the title or a category in the location, and the result would look plausible.
    """


@dataclass(frozen=True)
class RawParksEvent:
    date_text: str
    time_text: str
    event_type: str
    title: str
    detail: str
    venue: str | None
    venue_url: str | None
    year: int


def _find_year(soup: BeautifulSoup, fallback: int) -> int:
    match = re.search(config.YEAR_HEADING, soup.get_text(" ", strip=True))
    return int(match.group(1)) if match else fallback


def _verify_headers(table: Tag) -> None:
    header_row = table.find("tr")
    if header_row is None:
        raise ScheduleLayoutChanged("schedule table has no rows")

    headers = [c.get_text(strip=True).lower() for c in header_row.find_all(["th", "td"])]
    # Later rows use <th> for the date, so the header row is identified by content.
    if len(headers) < 4 or tuple(headers[:4]) != config.EXPECTED_HEADERS:
        raise ScheduleLayoutChanged(
            f"expected columns {config.EXPECTED_HEADERS}, found {tuple(headers[:4])}"
        )


def parse_schedule(html: str, *, fallback_year: int) -> list[RawParksEvent]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        # Out of season the page carries no schedule. Empty, not broken.
        log.info("no schedule table on the page; treating as no events")
        return []

    _verify_headers(table)
    year = _find_year(soup, fallback_year)

    events: list[RawParksEvent] = []
    for row in table.find_all("tr"):
        header_cell = row.find("th")
        cells = row.find_all("td")
        if header_cell is None or len(cells) < 3:
            continue

        # "July 10" and "7:30pm" are separated by a <br>.
        parts = [p.strip() for p in header_cell.get_text("\n").split("\n") if p.strip()]
        if len(parts) < 2:
            continue

        event_cell = cells[1]
        strong = event_cell.find("strong")
        title = (strong.get_text(strip=True) if strong else event_cell.get_text(strip=True)).strip()
        if not title:
            continue

        link = cells[2].find("a")
        events.append(
            RawParksEvent(
                date_text=parts[0],
                time_text=parts[1],
                event_type=cells[0].get_text(strip=True),
                title=title,
                detail=re.sub(r"\s+", " ", event_cell.get_text(" ", strip=True)),
                venue=cells[2].get_text(strip=True) or None,
                venue_url=link.get("href") if link else None,
                year=year,
            )
        )

    log.info("Portland Parks parsed %d rows for %d", len(events), year)
    return events


def fetch_raw(*, fallback_year: int, session: requests.Session | None = None) -> list[RawParksEvent]:
    client = session or requests.Session()
    last_error: Exception | None = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = client.get(
                config.EVENTS_URL,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": config.USER_AGENT, "Accept": "text/html"},
            )
            response.raise_for_status()
            return parse_schedule(response.text, fallback_year=fallback_year)
        except requests.RequestException as exc:
            last_error = exc
            if attempt < config.MAX_RETRIES:
                time.sleep(2**attempt)

    raise ParksFetchError(f"could not read the schedule after {config.MAX_RETRIES} attempts: {last_error}")
