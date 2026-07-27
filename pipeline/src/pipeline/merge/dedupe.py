"""Cross-source deduplication.

Two upstreams can list the same real-world event. The merged feed should carry one
entry for it, without any source appearing to lose data — per-source files stay
untouched, and every contributing origin is recorded on the survivor.

Matching is deliberately conservative. A false merge hides a real event the user could
have attended; a missed merge shows a duplicate, which is merely untidy. When in doubt,
don't merge.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import timedelta

from ..common.log import get_logger
from ..common.models import Event

log = get_logger(__name__)

# Two listings of the same show rarely agree on start time to the minute — one may
# use doors, the other the set time.
TIME_TOLERANCE = timedelta(minutes=30)

# Ticketmaster wins for ticketed events because it carries canonical ticket URLs and
# price data. Calagator wins otherwise, being closer to the organizer. Sources absent
# from this list rank last and are ordered by id for determinism.
_SOURCE_PRIORITY = ["ticketmaster", "calagator"]

_NOISE_WORDS = frozenset({"the", "at", "in", "on", "a", "an", "portland", "or", "oregon"})


def _normalize_venue(name: str | None) -> str:
    """Collapse venue naming differences: 'The Wonder Ballroom' vs 'Wonder Ballroom'."""
    if not name:
        return ""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    tokens = re.findall(r"[a-z0-9]+", folded.lower())
    return " ".join(t for t in tokens if t not in _NOISE_WORDS)


def _time_bucket(event: Event) -> int:
    """Bucket index at tolerance granularity, in UTC so offsets can't split a pair."""
    return int(event.start_at.timestamp() // TIME_TOLERANCE.total_seconds())


def _priority(event: Event) -> tuple[int, str]:
    try:
        rank = _SOURCE_PRIORITY.index(event.source.id)
    except ValueError:
        rank = len(_SOURCE_PRIORITY)
    return (rank, event.source.id)


def _looks_like_same_event(a: Event, b: Event) -> bool:
    if a.source.id == b.source.id:
        # Recurring events legitimately repeat within one source; never collapse those.
        return False
    if abs((a.start_at - b.start_at).total_seconds()) > TIME_TOLERANCE.total_seconds():
        return False
    venue_a, venue_b = _normalize_venue(a.venue.name if a.venue else None), _normalize_venue(b.venue.name if b.venue else None)
    # An unknown venue on either side is not evidence of sameness.
    return bool(venue_a) and venue_a == venue_b


def _merge_pair(winner: Event, loser: Event) -> Event:
    """Keep the higher-priority event, backfilling fields it lacks and both origins."""
    origins = {winner.source.id, loser.source.id, *winner.merged_sources, *loser.merged_sources}
    return Event(
        id=winner.id,
        title=winner.title,
        start_at=winner.start_at,
        price=winner.price if (winner.price.is_free or winner.price.min is not None) else loser.price,
        source=winner.source,
        summary=winner.summary or loser.summary,
        end_at=winner.end_at or loser.end_at,
        is_all_day=winner.is_all_day,
        venue=winner.venue or loser.venue,
        categories=winner.categories or loser.categories,
        image_url=winner.image_url or loser.image_url,
        listing_url=winner.listing_url or loser.listing_url,
        ticket_url=winner.ticket_url or loser.ticket_url,
        organizer=winner.organizer or loser.organizer,
        merged_sources=tuple(sorted(origins)),
    )


def deduplicate(events: list[Event]) -> tuple[list[Event], list[dict[str, str]]]:
    """Collapse cross-source duplicates. Returns the survivors and an audit log."""
    # Bucket by time so comparison stays local rather than quadratic over the feed.
    buckets: dict[int, list[Event]] = defaultdict(list)
    for event in events:
        buckets[_time_bucket(event)].append(event)

    merged_away: set[str] = set()
    replacements: dict[str, Event] = {}
    audit: list[dict[str, str]] = []

    for bucket_index, bucket in buckets.items():
        # An event near a boundary belongs to a neighbouring bucket's window too.
        candidates = bucket + buckets.get(bucket_index + 1, [])
        for i, first in enumerate(candidates):
            if first.id in merged_away:
                continue
            for second in candidates[i + 1 :]:
                if second.id in merged_away:
                    continue
                left = replacements.get(first.id, first)
                right = replacements.get(second.id, second)
                if not _looks_like_same_event(left, right):
                    continue

                winner, loser = (left, right) if _priority(left) <= _priority(right) else (right, left)
                replacements[winner.id] = _merge_pair(winner, loser)
                replacements.pop(loser.id, None)
                merged_away.add(loser.id)
                audit.append(
                    {
                        "kept": winner.id,
                        "dropped": loser.id,
                        "title_kept": winner.title,
                        "title_dropped": loser.title,
                        "venue": (winner.venue.name if winner.venue else ""),
                        "start_at": winner.start_at.isoformat(),
                    }
                )

    survivors = [replacements.get(e.id, e) for e in events if e.id not in merged_away]
    survivors.sort(key=lambda e: e.start_at)

    if audit:
        log.info("merged %d cross-source duplicate(s)", len(audit))
        for entry in audit[:10]:
            log.info("  kept %s over %s — %r @ %s", entry["kept"], entry["dropped"], entry["title_kept"], entry["venue"])
    else:
        log.info("no cross-source duplicates found")

    return survivors, audit
