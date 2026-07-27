"""Expansion of weekly recurring schedules into individual dated occurrences.

The `Event` model has no recurrence support and should not grow any: every event is
one dated occurrence with a stable `id`, which is what the client bookmarks against
and what dedupe and staleness both assume. But some sources — farmers markets above
all — publish a rule rather than a list of dates: "Saturdays 9am-2pm, May through
November". Those have to be turned into occurrences somewhere, and doing it here
rather than in each source keeps one set of edge cases in one tested place.

Two properties matter more than the arithmetic.

**Ids must not depend on when the pipeline ran.** An occurrence's identity is its
series plus its date, never its index in the expansion and never anything derived
from `now`. Two runs a week apart produce byte-identical ids for the same market day,
so a bookmark survives.

**Expansion must be bounded.** A weekly rule is unbounded by nature and it would be
easy to emit five years of Saturdays. Expansion always takes an explicit window and
clamps to it, so the cost of a rule is bounded by the horizon rather than by how far
the season runs.

Seasons are expressed as month/day pairs without a year, because that is how sources
state them ("April through December 19th"), and they are matched against each
candidate date's own year. That makes a rule valid indefinitely rather than needing a
yearly edit, and it handles a season that wraps the new year.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# A weekly rule expanded without limit is an infinite sequence. Every caller passes a
# window, but this is the backstop if one passes an absurd one.
MAX_OCCURRENCES_PER_RULE = 400


@dataclass(frozen=True, order=True)
class MonthDay:
    """A recurring calendar position, e.g. December 19th, with no year attached."""

    month: int
    day: int

    def __post_init__(self) -> None:
        if not 1 <= self.month <= 12:
            raise ValueError(f"month must be 1-12, got {self.month}")
        if not 1 <= self.day <= 31:
            raise ValueError(f"day must be 1-31, got {self.day}")

    @classmethod
    def first_of(cls, month: int) -> MonthDay:
        return cls(month, 1)

    @classmethod
    def last_of(cls, month: int) -> MonthDay:
        # 31 is safe as an upper bound because comparison is on the (month, day)
        # tuple rather than on a real date, so a short month simply never exceeds it.
        return cls(month, 31)

    def as_tuple(self) -> tuple[int, int]:
        return (self.month, self.day)


@dataclass(frozen=True)
class Season:
    """An inclusive window in the year, which may wrap through 31 December."""

    start: MonthDay
    end: MonthDay

    @property
    def wraps_year_end(self) -> bool:
        return self.start.as_tuple() > self.end.as_tuple()

    def contains(self, day: date) -> bool:
        position = (day.month, day.day)
        if self.wraps_year_end:
            # e.g. November through February: inside if past the start or before the end.
            return position >= self.start.as_tuple() or position <= self.end.as_tuple()
        return self.start.as_tuple() <= position <= self.end.as_tuple()


# The whole year, for sources that state a weekday but no season.
YEAR_ROUND = Season(MonthDay(1, 1), MonthDay(12, 31))


def ordinal_of_weekday(day: date) -> int:
    """Which occurrence of its weekday within the month this date is — 1 for the first."""
    return ((day.day - 1) // 7) + 1


@dataclass(frozen=True)
class WeeklyRule:
    """A weekly (or nth-weekly) recurring schedule within a season.

    `weekday` follows `date.weekday()`: Monday is 0, Sunday is 6.
    `ordinals` restricts to particular occurrences within the month — {2, 4} for
    "2nd and 4th Saturdays". An empty set means every week.
    """

    weekday: int
    start_time: time
    end_time: time | None = None
    season: Season = YEAR_ROUND
    ordinals: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if not 0 <= self.weekday <= 6:
            raise ValueError(f"weekday must be 0-6, got {self.weekday}")
        if any(o < 1 or o > 5 for o in self.ordinals):
            raise ValueError(f"ordinals must be 1-5, got {sorted(self.ordinals)}")

    def matches(self, day: date) -> bool:
        if day.weekday() != self.weekday:
            return False
        if not self.season.contains(day):
            return False
        if self.ordinals and ordinal_of_weekday(day) not in self.ordinals:
            return False
        return True


@dataclass(frozen=True)
class Occurrence:
    """One dated instance produced by a rule."""

    day: date
    start_at: datetime
    end_at: datetime | None

    @property
    def date_key(self) -> str:
        """The date component of a stable id. Never derived from the run time."""
        return self.day.isoformat()


def _localize(day: date, clock: time, zone: ZoneInfo) -> datetime:
    return datetime.combine(day, clock, tzinfo=zone)


def expand(
    rules: list[WeeklyRule],
    *,
    window_start: date,
    window_end: date,
    zone: ZoneInfo,
    max_occurrences: int = MAX_OCCURRENCES_PER_RULE,
) -> list[Occurrence]:
    """Produce every occurrence the rules generate inside an inclusive date window.

    Overlapping rules are resolved by keeping the first rule that claims a date, so a
    source can state a general rule and a more specific seasonal one without the two
    producing two events on the same day. Order the list accordingly: most specific
    first.
    """
    if window_end < window_start:
        return []

    occurrences: list[Occurrence] = []
    claimed: set[date] = set()

    day = window_start
    while day <= window_end and len(occurrences) < max_occurrences:
        for rule in rules:
            if day in claimed or not rule.matches(day):
                continue
            start_at = _localize(day, rule.start_time, zone)
            end_at = _localize(day, rule.end_time, zone) if rule.end_time else None
            # A close time earlier than the open time would mean the market runs
            # past midnight, which no market does; treat it as unstated instead.
            if end_at is not None and end_at <= start_at:
                end_at = None
            occurrences.append(Occurrence(day=day, start_at=start_at, end_at=end_at))
            claimed.add(day)
        day += timedelta(days=1)

    return occurrences
