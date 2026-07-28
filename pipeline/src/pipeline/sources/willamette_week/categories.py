"""Map CitySpark's numeric `Tags` onto the app's Category enum.

`Tags` rather than `Labels`, and the difference matters. `Labels` looks like the
category field and is not one: 81% of events have none at all, and the vocabulary that
does appear is delivery mode (`csInPerson` 218, `csRemote` 104, `csHybrid` 40,
`csVirtual` 19, `csOutdoor` 11, `csIndoor` 1) plus publisher newsletter markers
(`FGnewsletter` 51, `csPickup` 45, `bpnewsletter` 6, `SummerGuideEW` 4,
`emailnewsletter` 2, `inlanderprint` 1) and one literal `Label:` string. None of that
describes what an event *is*.

`Tags` is the real taxonomy: 720 nodes under 23 roots, and 96% of live events carry at
least one. The vocabulary is not documented anywhere public — it is embedded in the
widget bundle at `portal.cityspark.com/PortalScripts/WillametteWeek` as a flat list of
`{"parent": ..., "id": ..., "name": ...}`, which is where the ids and names in this
file were read from.

Only ids appear in the payload, so the tree is not shipped here. It does not need to
be: measured across 1,950 tagged events, 98.9% carry the full ancestor chain, not just
the leaf — an event tagged `Ska` also carries `Rock`, `Music` and `Performing Arts`. So
matching a small set of well-chosen ancestors covers the corpus without a 720-entry
data file that would go stale silently. Live resolution is 96.1% by an explicit rule
and 3.9% by the default, with no unmapped root left over.

Two stages, ordered, first match wins:

`REFINEMENTS` are nodes below a root that say more than the root does — `Music` under
`Performing Arts`, `Government Meetings` under `Civic Benefit`. Their order encodes
priority between competing signals, since events routinely carry three or four roots.
The rule is that what an event *is* beats who it is *for*: a kids' concert is `music`,
not `family`.

`ROOTS` are the 23 top-level nodes, as a backstop.

`Special Audience` (root 15) is deliberately absent from both. It is an audience facet,
not a topic, and it is the second most common root in the corpus at 572 events — but
those break down as Kids 380, Teens 257, Family 251, Special Needs 204, LGBT 176,
Women 21, Singles 15. Mapping the root to `family` would file every LGBT and
disability-focused event under family; only the three child tags that really do mean
"for families" are mapped, and the rest fall through to the default.

The residual error here is upstream's, not ours, and it is visible in live data: a
mimosa brunch tagged `Health & Wellness`, a wine flight tagged `Film`. Nothing on our
side can distinguish those from correct tags.
"""

from __future__ import annotations

from ...common.log import get_logger
from ...common.models import Category

log = get_logger(__name__)

# Ordered. Comments give the taxonomy path each id sits at.
REFINEMENTS: tuple[tuple[int, Category], ...] = (
    (439, Category.CIVIC),      # Civic Benefit > Politics & Government > Government Meetings
    (385, Category.MARKET),     # Pursuits & Hobbies > Markets & Shopping > Farmers Markets
    (17, Category.MUSIC),       # Performing Arts > Music
    (26, Category.FILM),        # Visual Arts > Film
    (36, Category.SPORTS),      # Sports & Outdoors > Sports
    (37, Category.OUTDOORS),    # Sports & Outdoors > Outdoor Recreation
    (38, Category.WELLNESS),    # Sports & Outdoors > Fitness
    (60, Category.WELLNESS),    # Lifestyle > Health & Wellness
    (10017, Category.WELLNESS), # Lifestyle > Religion & Spirituality > Meditation
    (34, Category.OUTDOORS),    # Destinations > Parks & Gardens
    (35, Category.OUTDOORS),    # Destinations > Sightseeing
    (182, Category.OUTDOORS),   # Pursuits & Hobbies > Home & Garden > Gardening
    (934, Category.TECH),       # Topics > STEM
    (44, Category.TECH),        # Topics > STEM > Technology
    (50, Category.FOOD),        # Pursuits & Hobbies > Culinary Arts
    (31, Category.COMMUNITY),   # Destinations > Festivals & Fairs
    (32, Category.ARTS),        # Destinations > Museums & Exhibits
    (51, Category.ARTS),        # Pursuits & Hobbies > Crafts
    (33, Category.FAMILY),      # Destinations > Zoos & Animals
    (77, Category.NIGHTLIFE),   # Nightlife > Bars
    (78, Category.NIGHTLIFE),   # Nightlife > Dance Clubs
    # Below Farmers Markets on purpose: this node also carries garage sales and
    # concerts staged at a market, so it is a weaker signal than anything above it.
    (54, Category.MARKET),      # Pursuits & Hobbies > Markets & Shopping
    # Below Government Meetings on purpose: council hearings are tagged as talks too,
    # and `civic` is the more useful shelf for them.
    (40, Category.LITERARY),    # Learning > Talks & Lectures
    (80, Category.FAMILY),      # Special Audience > Kids
    (79, Category.FAMILY),      # Special Audience > Family
    (81, Category.FAMILY),      # Special Audience > Teens
    # Filed under Special Audience upstream, but unlike its siblings this one names an
    # event type rather than an audience, and it is the only tag some drag shows carry.
    (9363, Category.NIGHTLIFE), # Special Audience > LGBT > Drag Show
)

ROOTS: tuple[tuple[int, Category], ...] = (
    (14, Category.NIGHTLIFE),   # Nightlife
    (12, Category.FOOD),        # Food & Drink
    (11, Category.CIVIC),       # Civic Benefit
    (4, Category.LITERARY),     # Literary Arts
    (2, Category.ARTS),         # Performing Arts
    (3, Category.ARTS),         # Visual Arts
    (16, Category.ARTS),        # Arts
    (6, Category.SPORTS),       # Sports & Outdoors
    (5, Category.OUTDOORS),     # Destinations
    (7, Category.COMMUNITY),    # Learning
    (8, Category.COMMUNITY),    # Professional
    (10, Category.COMMUNITY),   # Lifestyle
    (76, Category.COMMUNITY),   # Pursuits & Hobbies
    (931, Category.COMMUNITY),  # Topics
    (390, Category.COMMUNITY),  # Holidays
    (13, Category.COMMUNITY),   # Ongoing Activities & Attractions
    (9, Category.COMMUNITY),    # Uncategorized
)

# Tags that describe the audience, the offer, or the listing rather than the event.
# Excluded on purpose, and enumerated rather than resolved: with no taxonomy tree
# shipped there is no way to ask whether a tag descends from a facet root, and the
# whole subtree has to be listed for the gap report to stay meaningful. A live run
# otherwise reports LGBT, Singles and Special Needs as unmapped on every single run,
# forever, which is exactly how a real gap gets buried.
#
# These branches are small and stable — 20 nodes across six roots at the time of
# writing — so listing them is cheap. A new one appearing will show up as a gap, which
# is the correct outcome: someone should decide whether it is a facet or a topic.
# Kids, Family, Teens and Drag Show are absent because they are mapped above; they
# reach `_KNOWN` that way instead.
FACET_TAGS: frozenset[int] = frozenset(
    {
        # Special Audience, and the rest of what sits under it. See the module docstring.
        15, 82, 83, 84, 363, 429, 10019, 10139, 10288,
        420,            # Deals
        421, 441, 442,  # Engagement Level: Participant, Spectator
        422, 443, 444, 449, 450, 451, 452,  # Competitive Level
        423,            # Attendance
        917,            # Summary
    }
)

DEFAULT_CATEGORY = Category.COMMUNITY

_KNOWN: frozenset[int] = frozenset({t for t, _ in REFINEMENTS} | {t for t, _ in ROOTS} | FACET_TAGS)

_unmapped_seen: set[int] = set()


def infer_categories(tags: list[int] | None) -> tuple[Category, ...]:
    """Resolve exactly one Category from an event's tag ids.

    One rather than several, matching every other inference-based source: with several
    roots on most events, emitting all of them would scatter one event across four
    filter chips and make the chips mean less.
    """
    present = {t for t in (tags or []) if isinstance(t, int)}
    if not present:
        return (DEFAULT_CATEGORY,)

    for tag_id, category in REFINEMENTS:
        if tag_id in present:
            return (category,)

    for tag_id, category in ROOTS:
        if tag_id in present:
            return (category,)

    # Nothing matched. Record the tags so a taxonomy change shows up as a gap rather
    # than as a quiet drift of everything into `community`.
    for tag_id in sorted(present - _KNOWN):
        _unmapped_seen.add(tag_id)
    return (DEFAULT_CATEGORY,)


def unmapped_tags() -> list[int]:
    """Tag ids seen only on events that fell through to the default.

    Worth acting on when a *root* appears here — that means CitySpark grew a top-level
    branch. A deep leaf showing up is normal and needs no table row, since its
    ancestors would have matched had they been sent.
    """
    return sorted(_unmapped_seen)


def reset_unmapped() -> None:
    _unmapped_seen.clear()
