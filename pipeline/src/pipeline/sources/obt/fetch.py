"""Fetch OBT's season from Tessitura, plus the one thing Tessitura will not tell us.

The TNEW API in `tessitura.py` returns everything about a performance except where it
happens. There is no venue, facility, or address field anywhere in the response, and
the pages that do render one are behind the bot control described in that module.

OBT's marketing site fills the gap. Each production on the season page is an
`<article>` carrying its title and venue:

    <article class="card__card post-11376 ll_event ll_event_location-keller-auditorium">
      <a class="group"><div class="mt-4">
        <h2 class="card__card-title">Swan Lake</h2>
        <div class="card__card-meta">
          <p>October 10 - 17, 2026</p><span>&bull;</span>
          <span class="flex-initial">Keller Auditorium</span>
        </div>
      </div></a>
    </article>

Only the venue is taken from here. The dates on these cards are ranges covering a
whole run ("October 10 - 17, 2026"), never individual showings, which is why the
season page cannot be the primary source however much friendlier it is to read.

This lookup is best-effort throughout. A failure costs coordinates on a map, so it
degrades to events without venues rather than failing the run.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from ...common.log import get_logger
from . import config
from .tessitura import Production, TessituraError, fetch_listing

log = get_logger(__name__)

__all__ = ["OBTFetchError", "SeasonVenues", "fetch_raw", "match_key", "parse_season_venues"]


class OBTFetchError(Exception):
    """Tessitura did not return a usable listing; there is nothing to publish."""


# Venue names keyed by a normalized production title.
SeasonVenues = dict[str, str]


@dataclass(frozen=True)
class RawOBTSeason:
    productions: tuple[Production, ...]
    venues_by_title: SeasonVenues


def match_key(title: str) -> str:
    """Fold a production title down to something the two sites agree on.

    They do not spell productions identically. Tessitura sells "George Balanchine's
    The Nutcracker"; the season page bills it as "George Balanchine's The Nutcracker®"
    with a curly apostrophe and a registered mark. Stripping punctuation and symbols
    makes both sides land on `george balanchine s the nutcracker`.
    """
    folded = unicodedata.normalize("NFKC", title)
    folded = folded.replace("\u2019", "'").replace("\u2018", "'")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded.casefold()).split())


def find_season_page_url(html: str, *, base_url: str) -> str | None:
    """Pick the current season's page out of the season index.

    The index links to whichever season is live. Preferring the last match means that
    during the overlap when next season is announced alongside the current one, we
    follow the newer link, which is the one whose productions are on sale.
    """
    soup = BeautifulSoup(html, "html.parser")
    pattern = re.compile(r"/ballet-performances-in-portland/[^/]+-season/?$")
    found: list[str] = []
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "")
        if pattern.search(href):
            found.append(href if href.startswith("http") else f"{base_url.rstrip('/')}{href}")
    return found[-1] if found else None


def parse_season_venues(html: str) -> SeasonVenues:
    """Map each production on the season page to the venue it runs at."""
    soup = BeautifulSoup(html, "html.parser")
    venues: SeasonVenues = {}

    for heading in soup.select("h2.card__card-title"):
        title = heading.get_text(strip=True)
        if not title:
            continue
        container = heading.find_parent()
        meta = container.select_one(".card__card-meta") if container else None
        if meta is None:
            continue
        # The meta row is "<date range> • <venue>". The venue is the last span, but
        # only when the bullet is actually there — a card with no venue would
        # otherwise hand us its date range.
        spans = [s.get_text(strip=True) for s in meta.select("span")]
        candidates = [s for s in spans if s and s not in {"\u2022", "\u00b7", "-"}]
        if not candidates:
            continue
        venues[match_key(title)] = candidates[-1]

    return venues


def _get(session: requests.Session, url: str, *, accept: str) -> str | None:
    """GET with retries, returning None rather than raising."""
    last_error: Exception | None = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = session.get(
                url,
                headers={"User-Agent": config.USER_AGENT, "Accept": accept},
                timeout=config.REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < config.MAX_RETRIES:
                time.sleep(2**attempt)
    log.warning("could not read %s: %s", url, last_error)
    return None


def fetch_season_venues(session: requests.Session) -> SeasonVenues:
    """Read production venues off the marketing site. Never fatal."""
    index_html = _get(session, config.SEASON_INDEX_URL, accept="text/html")
    if index_html is None:
        return {}

    season_url = find_season_page_url(index_html, base_url=config.WWW_BASE_URL)
    if season_url is None:
        log.warning("no season page linked from %s; events will have no venue", config.SEASON_INDEX_URL)
        return {}

    time.sleep(config.WWW_CRAWL_DELAY_SECONDS)
    season_html = _get(session, season_url, accept="text/html")
    if season_html is None:
        return {}

    venues = parse_season_venues(season_html)
    log.info("read %d production venue(s) from %s", len(venues), season_url)
    return venues


def fetch_image_renditions(session: requests.Session, image_url: str) -> list[tuple[int, str]]:
    """List the downscaled renditions WordPress generated for an upload.

    Returned as `(width, url)` pairs, smallest first, empty on any failure.

    The API hands back the full-size upload, and full size is a liability: the
    Ticketmaster source had to stop using original artwork after 2846px images
    decoded to roughly 13 MB each and got the app killed on device. OBT's current
    uploads are a harmless 1000px, but that is luck rather than a guarantee, and
    WordPress rendition filenames cannot be derived without knowing the original's
    dimensions. The media API is the only way to ask.

    Looked up by slug, which WordPress derives from the filename, rather than by
    `search=`, which is a fuzzy full-text match that can return the wrong asset.
    """
    filename = image_url.rsplit("/", 1)[-1]
    slug = re.sub(r"[^a-z0-9]+", "-", filename.rsplit(".", 1)[0].casefold()).strip("-")
    if not slug:
        return []

    try:
        response = session.get(
            config.WP_MEDIA_ENDPOINT,
            params={"slug": slug},
            headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("could not look up renditions for %s: %s", filename, exc)
        return []

    return parse_image_renditions(payload)


def parse_image_renditions(payload: Any) -> list[tuple[int, str]]:
    if not isinstance(payload, list) or not payload:
        return []
    sizes = ((payload[0].get("media_details") or {}).get("sizes") or {}) if isinstance(payload[0], dict) else {}
    renditions = [
        (int(size["width"]), str(size["source_url"]))
        for size in sizes.values()
        if isinstance(size, dict) and isinstance(size.get("width"), int) and size.get("source_url")
    ]
    return sorted(set(renditions))


def fetch_raw(session: requests.Session | None = None) -> tuple[RawOBTSeason, dict[str, Any]]:
    client = session or requests.Session()
    # The window is expressed in the box office's own local time, which is how the
    # listing page asks for it.
    now = datetime.now(ZoneInfo(config.DISPLAY_TIMEZONE))

    try:
        productions = fetch_listing(
            client,
            base_url=config.TNEW_BASE_URL,
            start=now,
            end=now + config.FETCH_WINDOW,
            user_agent=config.USER_AGENT,
            timeout=config.REQUEST_TIMEOUT_SECONDS,
            max_retries=config.MAX_RETRIES,
        )
    except TessituraError as exc:
        raise OBTFetchError(str(exc)) from exc

    performance_count = sum(len(p.performances) for p in productions)
    log.info("Tessitura listed %d production(s), %d performance(s)", len(productions), performance_count)

    # Only worth the trip to the marketing site if there is something to place.
    venues_by_title = fetch_season_venues(client) if productions else {}

    stats = {
        "productions": len(productions),
        "performances": performance_count,
        "season_venues": len(venues_by_title),
    }
    return RawOBTSeason(tuple(productions), venues_by_title), stats
