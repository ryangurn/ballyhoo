"""Infer a Category for a Calagator event.

Calagator's JSON API exposes no tags, categories, or classification of any kind —
only free text. So category has to be inferred, which is inherently lossy.

Inference reads the **title only**. Matching descriptions was tried against live data
and was badly noisy: "Portland Drupal User Group" classified as food because its
venue is "Hawthorne Asylum food cart pod", and "Code & Coffee" likewise because its
description mentions grabbing lunch at nearby food carts. Descriptions run to
thousands of characters and mention venues, transit directions, and nearby
amenities — none of which describe what the event *is*. Titles are short and
deliberately descriptive, so they carry nearly all the usable signal and almost none
of the noise.

The default is `tech` because Calagator is Portland's community *tech* calendar, and
live data is overwhelmingly meetups (Code & Coffee, Python User Group, Drupal User
Group, HTML Day, Teardown). Defaulting to `community` would be less accurate for the
actual corpus.
"""

from __future__ import annotations

import re

from ...common.models import Category

# Ordered: first match wins, so the most specific signals come first. Keep these
# high-precision — a wrong category hides an event behind a filter chip the user
# never expected it under, which is worse than the honest default.
_KEYWORD_CATEGORIES: list[tuple[Category, tuple[str, ...]]] = [
    (Category.MARKET, ("farmers market", "flea market", "craft fair", "swap meet", "night market")),
    (Category.MUSIC, ("concert", "live music", "open mic", "album release", "jam session", "songwriter")),
    (Category.OUTDOORS, ("hike", "trail", "bike ride", "cleanup", "clean-up", "kayak", "birding", "gardening")),
    (Category.WELLNESS, ("yoga", "meditation", "mindfulness", "mental health", "wellness", "recovery")),
    (Category.LITERARY, ("book club", "poetry", "zine", "storytelling", "writers", "writing group")),
    (Category.CIVIC, ("city council", "town hall", "public hearing", "neighborhood association", "testimony")),
    (Category.ARTS, ("gallery", "art show", "theatre", "theater", "improv", "comedy", "craft night", "figure drawing")),
    (Category.FAMILY, ("storytime", "story time", "kids", "family friendly", "all ages")),
    (Category.NIGHTLIFE, ("bar crawl", "dance party", "karaoke", "trivia night")),
    (Category.FOOD, ("happy hour", "potluck", "brunch", "tasting", "cooking class", "food cart", "dinner")),
    (Category.COMMUNITY, ("volunteer", "mutual aid", "fundraiser", "community meeting", "open house")),
]

DEFAULT_CATEGORY = Category.TECH


def infer_categories(title: str, description: str | None = None) -> tuple[Category, ...]:
    """Return exactly one inferred category, derived from the title alone.

    One category rather than several: with no upstream signal, multiple guesses
    compound the error rate and scatter the event across filter chips.

    `description` is accepted so callers need not special-case it, but is
    deliberately ignored — see the module docstring.
    """
    haystack = re.sub(r"\s+", " ", title.lower())

    for category, keywords in _KEYWORD_CATEGORIES:
        if any(kw in haystack for kw in keywords):
            return (category,)

    return (DEFAULT_CATEGORY,)
