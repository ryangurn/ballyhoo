"""Map Ticketmaster's classification taxonomy onto the app's Category enum.

Ticketmaster classifies hierarchically: segment (Music, Sports, Arts & Theatre,
Family, Film, Miscellaneous), then genre, then sub-genre. The segment alone is a
usable signal, so it is the backstop; genres refine it where they are more precise
than their parent.

Two things to be careful about:

`Family` and `Miscellaneous` exist as both segment names and genre names. The genre
`Family` sits under the Film segment and means family *movies*, not a family event.
So matching happens per level, never on a bare name.

Genres are an open vocabulary. Live Portland data includes `Other` (23 of 200
sampled) and `Ice Shows`, neither of which maps cleanly. An unmapped genre must never
drop an event or leave it uncategorized — it falls back to the segment's category and
gets logged so the table can grow.
"""

from __future__ import annotations

from ...common.log import get_logger
from ...common.models import Category

log = get_logger(__name__)

SEGMENT_CATEGORIES: dict[str, Category] = {
    "music": Category.MUSIC,
    "sports": Category.SPORTS,
    "arts & theatre": Category.ARTS,
    "arts & theater": Category.ARTS,
    "family": Category.FAMILY,
    "film": Category.FILM,
    "miscellaneous": Category.COMMUNITY,
    # `Undefined` is a seventh segment absent from Ticketmaster's documented six, and
    # it is 7% of Portland's events. Inspecting it shows independent local music
    # venues almost exclusively — Dante's, Jack London Revue, Wonder Ballroom,
    # Holocene, White Eagle Saloon, Hawthorne Theatre — carrying live music, cabaret,
    # burlesque, and dance nights, with no genre set on any of them. Music is the
    # honest mapping for the bulk of it.
    #
    # This segment is also the reason no segmentName filter is sent: an allow-list of
    # the six documented names silently drops all of these, which are among the most
    # locally distinctive events in the feed.
    "undefined": Category.MUSIC,
}

# Only listed where the genre is genuinely more informative than its segment.
# Comedy under Arts & Theatre stays ARTS; Rock under Music stays MUSIC; neither
# earns an entry.
GENRE_CATEGORIES: dict[str, Category] = {
    "film": Category.FILM,
    "fairs & festivals": Category.COMMUNITY,
    "community/civic": Category.CIVIC,
    "food & drink": Category.FOOD,
    "health/wellness": Category.WELLNESS,
    "lecture/seminar": Category.LITERARY,
    "family fun": Category.FAMILY,
    "children's theatre": Category.FAMILY,
    "childrens theatre": Category.FAMILY,
    "ice shows": Category.FAMILY,
    "circus & specialty acts": Category.FAMILY,
}

# Genres that legitimately carry no extra signal. Kept explicit so they are not
# repeatedly reported as gaps in the mapping table.
_UNINFORMATIVE_GENRES = frozenset({"other", "undefined", "miscellaneous", ""})

DEFAULT_CATEGORY = Category.COMMUNITY

# Only segments are tracked as gaps. A genre without its own entry is the normal case
# — Rock resolving through the Music segment is correct and needs no table row — so
# reporting those would bury the one signal that matters in dozens that don't.
_unmapped_segments_seen: set[str] = set()


def infer_categories(segment_name: str | None, genre_name: str | None) -> tuple[Category, ...]:
    """Resolve one Category, preferring a genre match over its segment."""
    segment_key = (segment_name or "").strip().lower()
    genre_key = (genre_name or "").strip().lower()

    if genre_key in GENRE_CATEGORIES:
        return (GENRE_CATEGORIES[genre_key],)

    if segment_key in SEGMENT_CATEGORIES:
        return (SEGMENT_CATEGORIES[segment_key],)

    if segment_key and segment_key not in _unmapped_segments_seen:
        _unmapped_segments_seen.add(segment_key)
        log.warning(
            "segment %r is not in SEGMENT_CATEGORIES; events fall back to %s. "
            "Ticketmaster added a segment, so the table needs a row.",
            segment_name,
            DEFAULT_CATEGORY.value,
        )
    return (DEFAULT_CATEGORY,)


def unmapped_segments() -> list[str]:
    """Segments seen with no table entry — a real gap worth acting on."""
    return sorted(_unmapped_segments_seen)


def reset_unmapped() -> None:
    _unmapped_segments_seen.clear()
