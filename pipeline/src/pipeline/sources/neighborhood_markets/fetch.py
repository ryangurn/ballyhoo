"""Fetch each market's page and reduce it to comparable text.

A page is read once however many markets cite it, and one unreadable page costs only
the markets that cite it. Only if no page at all can be read does the run fail, so the
previously published file stays in place rather than being replaced by nothing.
"""

from __future__ import annotations

import re
import time
import unicodedata
from typing import Any

import requests
from bs4 import BeautifulSoup

from ...common.http import HTML_HEADERS
from ...common.log import get_logger
from . import config
from .markets import Market

log = get_logger(__name__)

# Site builders pad text with zero-width characters, which are not whitespace to `\s`.
_INVISIBLE = re.compile(r"[\s\u200b\u200c\u200d\u2060\ufeff]+")
_FOLDS = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"})


class NeighborhoodFetchError(Exception):
    """No market page could be read."""


def squash(text: str) -> str:
    """The form statements are compared in.

    Case, whitespace, zero-width characters, and curly-versus-straight quotes and dashes
    are all removed or folded. Those change when a site builder re-renders a page
    without the operator touching a word; this way the tripwire fires on a changed
    schedule rather than on changed markup. Whitespace goes entirely rather than being
    collapsed because Wix splits words across spans ("Apr il").
    """
    folded = unicodedata.normalize("NFKC", text).translate(_FOLDS).casefold()
    return _INVISIBLE.sub("", folded)


def page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "template"]):
        node.decompose()
    return squash(soup.get_text(" "))


def _get(client: requests.Session, url: str) -> str | None:
    last_error: Exception | None = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = client.get(url, timeout=config.REQUEST_TIMEOUT_SECONDS, headers=HTML_HEADERS)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < config.MAX_RETRIES:
                time.sleep(2**attempt)
    log.warning("could not read %s: %s", url, last_error)
    return None


def fetch_pages(
    markets: tuple[Market, ...], session: requests.Session | None = None
) -> tuple[dict[str, str | None], dict[str, Any]]:
    """Squashed text of every page the markets cite, or None where a page failed."""
    client = session or requests.Session()
    urls = list(dict.fromkeys(s.url for market in markets for s in market.statements))

    pages: dict[str, str | None] = {}
    for index, url in enumerate(urls):
        if index:
            time.sleep(config.SECONDS_BETWEEN_PAGES)
        html = _get(client, url)
        pages[url] = page_text(html) if html is not None else None

    readable = sum(1 for text in pages.values() if text is not None)
    if not readable:
        raise NeighborhoodFetchError(f"none of the {len(urls)} market pages could be read")
    log.info("read %d of %d market page(s)", readable, len(urls))
    return pages, {"pages": len(urls), "pages_read": readable}
