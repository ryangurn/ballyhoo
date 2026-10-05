"""Parse Squarespace event-collection pages.

Squarespace sites' `robots.txt` disallows `?format=json` and `?format=ical`, the two
shortcuts you would normally reach for, but permits the ordinary collection page, which
is fully server-rendered. Each item is an `article.eventlist-event`:

    <article class="eventlist-event eventlist-event--upcoming">
      <h1 class="eventlist-title">
        <a class="eventlist-title-link" href="/events/orenco-station-sffap">Orenco Station</a>
      </h1>
      <ul class="eventlist-meta">
        <li><time class="event-date" datetime="2026-10-11">Sunday, October 11, 2026</time></li>
        <li><time class="event-time-localized-start" datetime="2026-10-11">10:00 AM</time>
            <time class="event-time-localized-end" datetime="2026-10-11">2:00 PM</time></li>
        <li class="eventlist-meta-address">Hillsboro Farmers' Markets <a>(map)</a></li>
      </ul>
    </article>

Two details will quietly ruin a parse. The clock text separates the time from the
meridiem with U+202F, a narrow no-break space — `"10:00 AM"` is really
`"10:00\\u202fAM"` and a `%I:%M %p` parse of it fails. And a multiday item carries two
`time.event-date` elements, so taking the last one dates the event to the end of its run.

The `--past` / `--upcoming` class on each article reflects Squarespace's clock at render
time and is ignored; staleness is decided against our own `now`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import time
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

_CLOCK = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?[Mm]\.?$")


@dataclass(frozen=True)
class EventListItem:
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

    NFKC folds U+202F and U+00A0 into ordinary spaces, which is what makes the clock
    text parseable at all.
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def _text(node: Any) -> str | None:
    if node is None:
        return None
    value = normalize_spaces(node.get_text(" ", strip=True))
    return value or None


def parse_event_list(html: str, *, base_url: str) -> list[EventListItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[EventListItem] = []

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

        image = article.select_one("img")
        image_url = None
        if image is not None:
            image_url = image.get("data-src") or image.get("src")
            if image_url:
                # Strip Squarespace's rendition query so the stored URL is the original.
                image_url = image_url.split("?")[0]

        items.append(
            EventListItem(
                slug=href.rstrip("/").split("/")[-1],
                title=title,
                start_date=dates[0],
                end_date=dates[-1] if len(dates) > 1 and dates[-1] != dates[0] else None,
                start_clock=_text(article.select_one(".event-time-localized-start")),
                end_clock=_text(article.select_one(".event-time-localized-end")),
                summary=_text(article.select_one(".eventlist-excerpt")),
                image_url=image_url,
                url=urljoin(base_url, href),
            )
        )

    return items


def parse_clock(value: str | None) -> time | None:
    """Read Squarespace's "10:00 AM", after `normalize_spaces` has folded U+202F."""
    if not value:
        return None
    match = _CLOCK.match(normalize_spaces(value))
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    if match.group(3).lower() == "a":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    return time(hour, minute)
