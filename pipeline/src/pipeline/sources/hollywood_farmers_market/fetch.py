"""Fetch Hollywood Farmers Market's Squarespace collection pages and homepage.

Each listing item is a server-rendered `article.eventlist-event`:

    <article class="eventlist-event eventlist-event--upcoming eventlist-event--hasimg">
      <a class="eventlist-column-thumbnail" href="/music-schedule/tyler-waltner-quartet-2026">
        <img data-src="https://images.squarespace-cdn.com/.../photo.png" />
      </a>
      <h1 class="eventlist-title">
        <a class="eventlist-title-link" href="/music-schedule/tyler-waltner-quartet-2026">
          Tyler Waltner Quartet</a>
      </h1>
      <ul class="eventlist-meta">
        <li><time class="event-date" datetime="2026-08-01">Saturday, August 1, 2026</time></li>
        <li><time class="event-time-localized-start" datetime="2026-08-01">10:00 AM</time>
            <time class="event-time-localized-end" datetime="2026-08-01">12:30 PM</time></li>
      </ul>
      <div class="eventlist-excerpt"><p>4-piece jazz ensemble…</p></div>
    </article>

Two details in there will quietly ruin a parse. The clock text separates the time from
the meridiem with U+202F, a narrow no-break space, not an ordinary one — `"10:00 AM"`
is really `"10:00\u202fAM"`, and any `%I:%M %p` parse of it fails. And a multiday item
carries *two* `time.event-date` elements rather than one, which is how the run of
National Farmers Market Week is expressed; taking the last match rather than the first
would date every ordinary event correctly and every multiday one to its final day.

The `--past` / `--upcoming` class on each article is ignored deliberately. It reflects
Squarespace's clock at render time, and staleness is decided against our own `now`.
"""

from __future__ import annotations

import re
import time as timing
import unicodedata
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ...common.log import get_logger
from . import config

log = get_logger(__name__)


class HollywoodFetchError(Exception):
    """Upstream did not return usable data."""


@dataclass(frozen=True)
class RawListingEvent:
    collection: str
    slug: str
    title: str
    start_date: str
    end_date: str | None
    start_clock: str | None
    end_clock: str | None
    summary: str | None
    image_url: str | None
    url: str


def normalize_spaces(value: str) -> str:
    """Collapse whitespace, including the Unicode spaces Squarespace emits.

    NFKC folds U+202F (narrow no-break space) and U+00A0 into ordinary spaces, which
    is what makes the clock text parseable at all.
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def _text(node: Any) -> str | None:
    if node is None:
        return None
    value = normalize_spaces(node.get_text(" ", strip=True))
    return value or None


def parse_market_hours(html: str) -> str | None:
    """Pull the homepage's stated market hours, normalized for comparison.

    Returns the sentence following "MARKET HOURS", which is the rule the encoded
    `MARKET_RULES` were derived from.
    """
    text = normalize_spaces(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    match = re.search(r"MARKET HOURS\s*(.+?)\s*MARKET MAP", text, re.IGNORECASE)
    if not match:
        # Fall back to a bounded slice so a changed trailing heading still surfaces
        # something for the caller to compare and warn about.
        loose = re.search(r"MARKET HOURS\s*(.{0,160})", text, re.IGNORECASE)
        return normalize_spaces(loose.group(1)).casefold() if loose else None
    return normalize_spaces(match.group(1)).casefold()


def parse_event_list(html: str, *, collection: str, base_url: str) -> list[RawListingEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[RawListingEvent] = []

    for article in soup.select("article.eventlist-event"):
        link = article.select_one("a.eventlist-title-link")
        if link is None:
            continue
        href = link.get("href") or ""
        title = _text(link)
        if not (href and title):
            continue

        dates = [t.get("datetime") for t in article.select("time.event-date") if t.get("datetime")]
        if not dates:
            continue
        # A multiday item lists its start and end as two elements.
        start_date = dates[0]
        end_date = dates[-1] if len(dates) > 1 and dates[-1] != dates[0] else None

        image = article.select_one("img")
        image_url = None
        if image is not None:
            image_url = image.get("data-src") or image.get("src")
            if image_url:
                # Strip Squarespace's rendition query so the stored URL is the original.
                image_url = image_url.split("?")[0]

        events.append(
            RawListingEvent(
                collection=collection,
                slug=href.rstrip("/").split("/")[-1],
                title=title,
                start_date=start_date,
                end_date=end_date,
                start_clock=_text(article.select_one(".event-time-localized-start")),
                end_clock=_text(article.select_one(".event-time-localized-end")),
                summary=_text(article.select_one(".eventlist-excerpt")),
                image_url=image_url,
                url=urljoin(base_url, href),
            )
        )

    return events


def _get(client: requests.Session, url: str) -> str | None:
    last_error: Exception | None = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = client.get(
                url,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": config.USER_AGENT, "Accept": "text/html"},
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < config.MAX_RETRIES:
                timing.sleep(2**attempt)
    log.warning("could not read %s: %s", url, last_error)
    return None


def fetch_raw(session: requests.Session | None = None) -> tuple[list[RawListingEvent], str | None, dict[str, Any]]:
    """Read the homepage and both collections.

    Returns the dated listings, the homepage's stated market hours, and stats. The
    hours string is what `normalize` checks the encoded recurrence rules against.
    """
    client = session or requests.Session()

    home = _get(client, config.HOME_URL)
    if home is None:
        raise HollywoodFetchError("could not read the homepage")
    hours_text = parse_market_hours(home)
    if hours_text is None:
        log.warning("no market hours sentence found on the homepage")

    collected: list[RawListingEvent] = []
    pages_read = 0
    for collection, url in config.LISTING_URLS.items():
        timing.sleep(config.SECONDS_BETWEEN_PAGES)
        html = _get(client, url)
        if html is None:
            # One collection failing costs its listings, not the market days.
            continue
        batch = parse_event_list(html, collection=collection, base_url=config.HOME_URL)
        pages_read += 1
        collected.extend(batch)
        log.info("read %d item(s) from %s", len(batch), collection)

    stats = {"pages_read": pages_read, "collected": len(collected), "hours_text": hours_text}
    return collected, hours_text, stats
