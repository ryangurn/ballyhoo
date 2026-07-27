"""Fetch and parse PDX Parent's farmers-market roundup.

Each market is one WordPress block paragraph with a rigidly regular shape:

    <p class="wp-block-paragraph"><a href="https://www.montavillamarket.org/">Montavilla
    Farmers Market</a>, SE Stark &amp; 76th<br>Every Sunday, May-December 20, 10 am-2 pm

Link text is the name, everything between the link and the `<br>` is the address, and
everything after it is the schedule.

The paragraphs are *not* closed — there is no `</p>` anywhere in the list — so a tree
parse nests forty markets inside one another and every paragraph appears to contain
all the ones after it. Splitting the raw HTML on the opening tag sidesteps that
entirely and is more robust here than choosing a lenient parser, because the shape we
depend on is one tag deep.
"""

from __future__ import annotations

import html as html_module
import re
import time as timing
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import requests

from ...common.log import get_logger
from . import config

log = get_logger(__name__)

_BLOCK = re.compile(r'<p class="wp-block-paragraph">')
_LINK = re.compile(r'<a\b[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<text>.*?)</a>', re.DOTALL | re.IGNORECASE)
_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")

# The roundup is a list of markets; the page also contains sponsor copy and a footer
# call to action built from the same block type.
_MARKET_NAME = re.compile(r"\bmarket(?:place)?s?\b", re.IGNORECASE)


class PdxParentFetchError(Exception):
    """Upstream did not return usable data."""


@dataclass(frozen=True)
class RawMarket:
    name: str
    address: str | None
    schedule_line: str
    url: str

    @property
    def link_domain(self) -> str:
        return (urlsplit(self.url).hostname or "").lower().removeprefix("www.")


def _clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_module.unescape(_TAG.sub(" ", fragment))).strip()


def parse_roundup(html: str) -> list[RawMarket]:
    markets: list[RawMarket] = []
    seen: set[tuple[str, str]] = set()

    for block in _BLOCK.split(html)[1:]:
        # Stop at whichever comes first: a close tag or the next unclosed paragraph.
        block = re.split(r"</p>|<p\b", block, maxsplit=1)[0]
        if not _BREAK.search(block):
            continue
        head, tail = _BREAK.split(block, maxsplit=1)

        link = _LINK.search(head)
        if link is None:
            continue
        name = _clean(link.group("text")).rstrip(",").strip()
        schedule_line = _clean(tail)
        if not name or not schedule_line:
            continue
        # Skips the intra-page day jump links and the sponsor and footer paragraphs.
        if not _MARKET_NAME.search(name):
            continue

        address = _clean(head[link.end() :]).lstrip(",").strip() or None
        key = (name.casefold(), schedule_line.casefold())
        if key in seen:
            continue
        seen.add(key)

        markets.append(
            RawMarket(name=name, address=address, schedule_line=schedule_line, url=link.group("href").strip())
        )

    return markets


def fetch_raw(session: requests.Session | None = None) -> tuple[list[RawMarket], dict[str, Any]]:
    client = session or requests.Session()
    last_error: Exception | None = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = client.get(
                config.ROUNDUP_URL,
                timeout=config.REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": config.USER_AGENT, "Accept": "text/html"},
            )
            response.raise_for_status()
            markets = parse_roundup(response.text)
            if not markets:
                raise PdxParentFetchError("the roundup page contained no market paragraphs")
            log.info("PDX Parent roundup listed %d market(s)", len(markets))
            return markets, {"collected": len(markets)}
        except (requests.RequestException, PdxParentFetchError) as exc:
            last_error = exc
            if attempt < config.MAX_RETRIES:
                timing.sleep(2**attempt)

    raise PdxParentFetchError(f"could not read the roundup: {last_error}")
