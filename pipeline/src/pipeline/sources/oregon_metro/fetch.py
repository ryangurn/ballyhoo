"""Fetch and parse Oregon Metro's events listing.

The page is server-rendered Drupal. Each event is an `event-teaser` block:

    <div class="eventinstance-list event-teaser">
      <div class="event-teaser__eyebrow eyebrow">Nature activity</div>
      <h3 class="event-teaser__title h5">
        <a href="/events/paddle-the-slough-2026-08-01">Paddle the slough</a>
      </h3>
      <div class="event-teaser__datetime">
        <time datetime="2026-08-01T18:00:00">August 1, 2026</time>
        <time datetime="2026-08-01T18:00:00">11 a.m. to 2 p.m.</time>
      </div>
      <div class="event-teaser__meta">
        <div class="event-teaser__location">Oxbow Regional Park</div>
      </div>
    </div>
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests
from bs4 import BeautifulSoup

from ...common.log import get_logger
from . import config

log = get_logger(__name__)


class MetroFetchError(Exception):
    """Upstream did not return usable data."""


@dataclass(frozen=True)
class RawMetroEvent:
    slug: str
    title: str
    start_raw: str
    end_raw: str | None
    category: str | None
    location: str | None
    url: str


def _text(node: Any) -> str | None:
    if node is None:
        return None
    value = node.get_text(strip=True)
    return value or None


def parse_page(html: str) -> list[RawMetroEvent]:
    soup = BeautifulSoup(html, "html.parser")
    events: list[RawMetroEvent] = []

    for teaser in soup.select(".event-teaser"):
        link = teaser.select_one(".event-teaser__title a")
        if link is None:
            continue
        href = link.get("href") or ""
        title = _text(link)
        if not title or not href:
            continue

        times = teaser.select(".event-teaser__datetime time[datetime]")
        if not times:
            continue

        # Both <time> elements carry the same start instant; the second one's text
        # is the human range. Only the attribute is machine-readable, so an end
        # time is only available when a distinct second attribute appears.
        start_raw = times[0].get("datetime")
        end_raw = times[1].get("datetime") if len(times) > 1 else None
        if end_raw == start_raw:
            end_raw = None
        if not start_raw:
            continue

        events.append(
            RawMetroEvent(
                # The slug embeds the date, which makes it a stable per-occurrence
                # identifier for recurring meetings.
                slug=href.rstrip("/").split("/")[-1],
                title=title,
                start_raw=start_raw,
                end_raw=end_raw,
                category=_text(teaser.select_one(".event-teaser__eyebrow")),
                location=_text(teaser.select_one(".event-teaser__location")),
                url=f"https://www.oregonmetro.gov{href}" if href.startswith("/") else href,
            )
        )

    return events


def fetch_raw(session: requests.Session | None = None) -> tuple[list[RawMetroEvent], dict[str, Any]]:
    client = session or requests.Session()
    collected: list[RawMetroEvent] = []
    seen_slugs: set[str] = set()
    pages_read = 0

    for page in range(config.MAX_PAGES):
        last_error: Exception | None = None
        html: str | None = None

        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                response = client.get(
                    config.EVENTS_URL,
                    params={"page": page},
                    timeout=config.REQUEST_TIMEOUT_SECONDS,
                    headers={"User-Agent": config.USER_AGENT, "Accept": "text/html"},
                )
                response.raise_for_status()
                html = response.text
                break
            except requests.RequestException as exc:
                last_error = exc
                if attempt < config.MAX_RETRIES:
                    time.sleep(2**attempt)

        if html is None:
            if page == 0:
                raise MetroFetchError(f"could not read the first page: {last_error}")
            # A later page failing costs us its events but not the whole run.
            log.warning("stopping at page %d after repeated failures: %s", page, last_error)
            break

        batch = parse_page(html)
        pages_read += 1
        if not batch:
            break

        # Metro serves the last page repeatedly past the end rather than 404ing, so
        # stop when a page introduces nothing new.
        fresh = [e for e in batch if e.slug not in seen_slugs]
        if not fresh:
            break
        seen_slugs.update(e.slug for e in fresh)
        collected.extend(fresh)

        if len(batch) < config.PAGE_SIZE_HINT:
            break

        time.sleep(config.SECONDS_BETWEEN_PAGES)

    stats = {"pages_read": pages_read, "collected": len(collected)}
    log.info("Oregon Metro read %d page(s), %d events", pages_read, len(collected))
    return collected, stats
