"""Guard against publishing a suspiciously empty feed.

A source can fail in a way that returns HTTP 200 with few or no events. Without a
check, that quietly replaces a healthy feed with a gutted one for every user at once.
The floor compares each run against the recent baseline and refuses to publish an
unexplained collapse, requiring a human to override.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from ..common.log import get_logger

log = get_logger(__name__)

# Feeds move by tens of events day to day. Below 40% of the recent median, something
# broke upstream rather than Portland going quiet.
FLOOR_RATIO = 0.4

# With too little history the median is meaningless, so the floor stays disabled
# rather than firing on noise during the pipeline's first days.
MIN_HISTORY_RUNS = 3

MAX_HISTORY_RUNS = 30


@dataclass(frozen=True)
class FloorCheck:
    passed: bool
    reason: str
    current_count: int
    baseline: int | None


def evaluate(current_count: int, history: list[int], *, override: bool = False) -> FloorCheck:
    if override:
        return FloorCheck(True, "floor check overridden by operator", current_count, None)

    recent = [n for n in history[-MAX_HISTORY_RUNS:] if n > 0]
    if len(recent) < MIN_HISTORY_RUNS:
        return FloorCheck(
            True,
            f"insufficient history ({len(recent)} run(s), need {MIN_HISTORY_RUNS})",
            current_count,
            None,
        )

    baseline = int(statistics.median(recent))
    threshold = int(baseline * FLOOR_RATIO)

    if current_count < threshold:
        return FloorCheck(
            False,
            f"{current_count} events is below the floor of {threshold} "
            f"({int(FLOOR_RATIO * 100)}% of a {baseline}-event baseline). "
            f"A source most likely failed while still returning success. "
            f"Re-run with --override-floor if the drop is genuine.",
            current_count,
            baseline,
        )

    return FloorCheck(True, f"{current_count} events against a {baseline}-event baseline", current_count, baseline)


def append_history(history: list[int], count: int) -> list[int]:
    return [*history, count][-MAX_HISTORY_RUNS:]
