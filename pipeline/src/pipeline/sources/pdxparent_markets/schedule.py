"""Parse a farmers market's schedule out of English prose.

The roundup states each market's schedule as a sentence, and the sentences vary a lot:

    Sundays, April 26-October 25, 2026, 10 am-2 pm
    Sundays, May-October, 9:30 am-2 pm
    Sundays, 10 am-2 pm, June-September
    1st and 3rd Mondays, June-October, 3-7 pm
    Second and fourth Thursdays, June 11-October 22, 2026, 4-8 pm
    Wednesdays, 2-7 pm (Winter hours 2-6 pm)
    Fridays, May 15-October 16, 2026, 2-7 pm. No market July 10
    Saturdays, February-March 2026, 10 am-1:30 pm; April-November 21, 2026, 8:30 am-1:30 pm.

The parser is built for precision over recall. Every field it cannot read with
confidence makes it return nothing for that clause rather than guess, because the
output here is not a description — it is a set of dates we will tell someone a market
is open. `ParsedSchedule.problems` records what was skipped so a run can report it.

Three rules keep it honest.

*Semicolons separate alternate schedules*, and each gets its own rule, so Beaverton's
winter and summer hours both survive. A clause with no weekday of its own inherits the
previous clause's, which is how "April-November 21, 2026, 8:30 am-1:30 pm" is
understood to still mean Saturdays.

*Within a clause only the first weekday and first time range count.* Troutdale's
"Sundays, 10 am-4 pm. Also open Fridays, 2-7 pm" would otherwise attach Friday's hours
to Sunday. Losing the extra days is the right trade against stating a wrong one.

*A bare number after a month is a day only if it is not part of a year.* "June-
September 2026" parses as June through September, not through September 20th — the
lookahead that prevents that is the difference between a correct season and one that
ends ten days early.
"""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import time

from ...common.recurrence import YEAR_ROUND, MonthDay, Season, WeeklyRule

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

ORDINAL_WORDS = {
    "1st": 1,
    "first": 1,
    "2nd": 2,
    "second": 2,
    "3rd": 3,
    "third": 3,
    "4th": 4,
    "fourth": 4,
    "5th": 5,
    "fifth": 5,
}

_ORDINAL_ALT = "|".join(ORDINAL_WORDS)
_WEEKDAY_ALT = "|".join(WEEKDAYS)
_MONTH_ALT = "|".join(MONTHS)
_DASH = r"(?:-|\u2010|\u2011|\u2012|\u2013|\u2014|through|thru|to)"

# The roundup runs each market's paragraph into the next section's heading, so cut
# there before parsing anything.
_SECTION_HEADING = re.compile(rf"\b(?:{_WEEKDAY_ALT})\s+farmers\s+markets\b|\bcourtesy of\b", re.IGNORECASE)

_WEEKDAY = re.compile(
    rf"(?P<ordinals>(?:(?:{_ORDINAL_ALT})\b[\s,]*(?:and|&)?\s*)+)?\b(?P<day>{_WEEKDAY_ALT})s?\b",
    re.IGNORECASE,
)

# Either both ends carry a meridiem ("10 am-2 pm") or only the last does ("4:30-8 pm").
_TIME_RANGE = re.compile(
    rf"\b(?P<h1>\d{{1,2}})(?::(?P<m1>\d{{2}}))?\s*(?P<mer1>[ap])\.?\s*m\.?\s*{_DASH}\s*"
    rf"(?P<h2>\d{{1,2}})(?::(?P<m2>\d{{2}}))?\s*(?P<mer2>[ap])\.?\s*m\.?"
    rf"|\b(?P<bare_h1>\d{{1,2}})(?::(?P<bare_m1>\d{{2}}))?\s*{_DASH}\s*"
    rf"(?P<bare_h2>\d{{1,2}})(?::(?P<bare_m2>\d{{2}}))?\s*(?P<bare_mer>[ap])\.?\s*m\.?",
    re.IGNORECASE,
)

# `(?!\d)` is what stops the 20 of "2026" being read as a day of the month.
_DAY = r"(?:(?P<{name}>\d{{1,2}})(?!\d))?"
_SEASON = re.compile(
    rf"\b(?P<m1>{_MONTH_ALT})\.?\s*{_DAY.format(name='d1')}\s*{_DASH}\s*"
    rf"(?P<m2>{_MONTH_ALT})\.?\s*{_DAY.format(name='d2')}",
    re.IGNORECASE,
)

_NO_MARKET = re.compile(rf"\bno market\b[^.;]*?\b(?P<month>{_MONTH_ALT})\.?\s*(?P<day>\d{{1,2}})(?!\d)", re.IGNORECASE)

# "every other Sunday" has no anchor date in the text, so it cannot be expanded.
_UNANCHORED = re.compile(r"\bevery other\b|\bselect (?:dates|Saturdays|Sundays)\b|\btwice monthly\b", re.IGNORECASE)

# A follow-on clause naming a venue is the market moving somewhere else for the
# season, not different hours at the same place — Woodlawn's winter market runs
# "December-May at Classic Foods, 817 NE Madrona St". Its address is the one thing
# the roundup gives us per market rather than per clause, so a relocated clause
# would be pinned to the wrong coordinates.
_RELOCATION = re.compile(r"\bat\s+[A-Z0-9]", re.UNICODE)


@dataclass
class ParsedSchedule:
    rules: list[WeeklyRule] = field(default_factory=list)
    skipped_dates: frozenset[tuple[int, int]] = frozenset()
    problems: list[str] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        return bool(self.rules)


def _to_24_hour(hour: int, minute: int, meridiem: str) -> time | None:
    if not 1 <= hour <= 12 or not 0 <= minute <= 59:
        return None
    if meridiem == "a":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    return time(hour, minute)


def parse_time_range(text: str) -> tuple[time, time] | None:
    """Read the first time range in a clause, or nothing."""
    match = _TIME_RANGE.search(text)
    if not match:
        return None
    parts = match.groupdict()

    if parts["h1"]:
        start = _to_24_hour(int(parts["h1"]), int(parts["m1"] or 0), parts["mer1"].lower())
        end = _to_24_hour(int(parts["h2"]), int(parts["m2"] or 0), parts["mer2"].lower())
    else:
        # Only the end states a meridiem: "4:30-8 pm", "12-5 pm". The start shares it
        # unless that would put the start after the end, as in "10-2 pm".
        meridiem = parts["bare_mer"].lower()
        start_hour, start_minute = int(parts["bare_h1"]), int(parts["bare_m1"] or 0)
        end = _to_24_hour(int(parts["bare_h2"]), int(parts["bare_m2"] or 0), meridiem)
        start = _to_24_hour(start_hour, start_minute, meridiem)
        if start is not None and end is not None and start >= end:
            start = _to_24_hour(start_hour, start_minute, "a" if meridiem == "p" else "p")

    if start is None or end is None or start >= end:
        return None
    return start, end


def parse_season(text: str) -> Season | None:
    """Read the first month range in a clause. A month with no day means the whole month."""
    match = _SEASON.search(text)
    if not match:
        return None
    start_month = MONTHS[match.group("m1").lower()]
    end_month = MONTHS[match.group("m2").lower()]
    start_day = int(match.group("d1")) if match.group("d1") else 1
    # No closing day means the season runs to the end of that month.
    end_day = int(match.group("d2")) if match.group("d2") else monthrange(2024, end_month)[1]

    if not 1 <= start_day <= monthrange(2024, start_month)[1]:
        return None
    if not 1 <= end_day <= monthrange(2024, end_month)[1]:
        return None
    return Season(MonthDay(start_month, start_day), MonthDay(end_month, end_day))


def _parse_weekday(text: str) -> tuple[int, frozenset[int]] | None:
    match = _WEEKDAY.search(text)
    if not match:
        return None
    weekday = WEEKDAYS[match.group("day").lower()]
    raw_ordinals = match.group("ordinals") or ""
    ordinals = frozenset(
        ORDINAL_WORDS[token.lower()] for token in re.findall(_ORDINAL_ALT, raw_ordinals, re.IGNORECASE)
    )
    return weekday, ordinals


def parse(line: str) -> ParsedSchedule:
    """Turn one market's schedule sentence into recurrence rules."""
    parsed = ParsedSchedule()
    if not line:
        parsed.problems.append("empty schedule")
        return parsed

    text = _SECTION_HEADING.split(line)[0].strip()
    if not text:
        parsed.problems.append("nothing left after removing the section heading")
        return parsed

    parsed.skipped_dates = frozenset(
        (MONTHS[m.lower()], int(d)) for m, d in _NO_MARKET.findall(text)
    )

    inherited_weekday: int | None = None
    for index, clause in enumerate(c.strip() for c in text.split(";")):
        if not clause:
            continue

        weekday_match = _parse_weekday(clause)
        if weekday_match is None:
            if inherited_weekday is None:
                parsed.problems.append(f"no weekday in {clause[:60]!r}")
                continue
            weekday, ordinals = inherited_weekday, frozenset()
        else:
            weekday, ordinals = weekday_match
            inherited_weekday = weekday

        if index > 0 and _RELOCATION.search(clause):
            parsed.problems.append(f"clause moves the market elsewhere: {clause[:60]!r}")
            continue

        times = parse_time_range(clause)
        if times is None:
            parsed.problems.append(f"no time range in {clause[:60]!r}")
            continue

        unanchored = _UNANCHORED.search(clause)
        if unanchored and unanchored.start() < _TIME_RANGE.search(clause).start():
            # "every other Sunday, January-April" states no anchor date, so its dates
            # cannot be derived and guessing fortnightly would be fiction. Position
            # matters: the same phrase *after* the hours is describing some other,
            # additional schedule ("9 am-1 pm. Open select dates twice monthly in
            # winter"), and rejecting the clause over it would throw away a perfectly
            # good primary rule.
            parsed.problems.append(f"unanchored recurrence in {clause[:60]!r}")
            continue

        start_time, end_time = times
        season = parse_season(clause) or YEAR_ROUND
        parsed.rules.append(
            WeeklyRule(
                weekday=weekday,
                start_time=start_time,
                end_time=end_time,
                season=season,
                ordinals=ordinals,
            )
        )

    if not parsed.rules and not parsed.problems:
        parsed.problems.append("no usable clause")
    return parsed
