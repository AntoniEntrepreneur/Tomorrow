"""Pure Plan finalization seam.

Input: day bounds, any remaining Drafts, candidate Anchors, and Flex with
optional placements.
Output: a finished Plan structure, or structured blockers explaining why the
Plan cannot finish yet. No CLI, filesystem, or network access happens here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Sequence, Union

from tomorrow.defaults import DayBounds


@dataclass(frozen=True)
class Draft:
    """Something captured this session that is not yet an Anchor or Flex."""

    name: str


@dataclass(frozen=True)
class Anchor:
    """A Plan item locked to a clock start that occupies real time."""

    name: str
    start: time
    duration: timedelta
    checklist: str | None = None

    @property
    def end(self) -> time:
        combined = datetime.combine(date(2000, 1, 1), self.start) + self.duration
        return combined.time()


@dataclass(frozen=True)
class Flex:
    """A Plan item with duration but no fixed start until placed in a Gap."""

    name: str
    duration: timedelta
    start: time | None = None
    checklist: str | None = None

    @property
    def end(self) -> time | None:
        if self.start is None:
            return None
        combined = datetime.combine(date(2000, 1, 1), self.start) + self.duration
        return combined.time()

    def with_duration(self, duration: timedelta) -> Flex:
        return Flex(
            name=self.name,
            duration=duration,
            start=self.start,
            checklist=self.checklist,
        )

    def with_start(self, start: time) -> Flex:
        return Flex(
            name=self.name,
            duration=self.duration,
            start=start,
            checklist=self.checklist,
        )


@dataclass(frozen=True)
class Gap:
    """Free time between day bounds and Anchors."""

    start: time
    end: time


@dataclass(frozen=True)
class DraftUnfinishedBlocker:
    """A Draft has not yet been promoted to an Anchor (or Flex)."""

    draft: Draft


@dataclass(frozen=True)
class AnchorOverlapBlocker:
    """Two Anchors occupy overlapping time."""

    first: Anchor
    second: Anchor


@dataclass(frozen=True)
class AnchorOutOfBoundsBlocker:
    """An Anchor starts before wake or occupies time past sleep."""

    anchor: Anchor


@dataclass(frozen=True)
class FlexUnplacedBlocker:
    """A Flex has no start time yet."""

    flex: Flex


@dataclass(frozen=True)
class FlexDoesNotFitBlocker:
    """A placed Flex overruns its Gap or overlaps another item."""

    flex: Flex


@dataclass(frozen=True)
class DegenerateDayBoundsBlocker:
    """Wake equals sleep, collapsing the day's envelope to zero minutes."""

    bounds: DayBounds


Blocker = Union[
    DraftUnfinishedBlocker,
    AnchorOverlapBlocker,
    AnchorOutOfBoundsBlocker,
    FlexUnplacedBlocker,
    FlexDoesNotFitBlocker,
    DegenerateDayBoundsBlocker,
]


@dataclass(frozen=True)
class FinalizedPlan:
    """A consistent, renderable Plan: day bounds plus ordered timeline items."""

    bounds: DayBounds
    anchors: tuple[Anchor, ...]
    flexes: tuple[Flex, ...]


@dataclass(frozen=True)
class FinalizeResult:
    plan: FinalizedPlan | None
    blockers: tuple[Blocker, ...]

    @property
    def ok(self) -> bool:
        return self.plan is not None


class PlanBlockedError(Exception):
    """Raised by adapters when finalization is blocked and cannot proceed."""

    def __init__(self, blockers: Sequence[Blocker]) -> None:
        super().__init__(f"Plan is blocked by {len(blockers)} issue(s).")
        self.blockers: tuple[Blocker, ...] = tuple(blockers)


def parse_clock(value: str) -> time:
    """Parse an "HH:MM" clock string, the one format used across the wizard."""

    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def minutes_since_midnight(value: time) -> int:
    return value.hour * 60 + value.minute


def minutes_since_wake(value: time, *, wake: time) -> int:
    """Offset in minutes from wake, wrapping past midnight into wake+24h.

    This is the basis for all ordering, overlap, and bounds-checking:
    a clock time earlier than wake is understood as "tomorrow, early
    morning" rather than "today, very early" — see docs/adr/0003.
    """

    return (minutes_since_midnight(value) - minutes_since_midnight(wake)) % 1440


def is_next_day(value: time, *, wake: time) -> bool:
    """Whether `value` falls on the calendar day after `wake`, wake-relative."""

    return minutes_since_midnight(value) < minutes_since_midnight(wake)


def minutes_between(start: time, end: time) -> int:
    """Whole minutes from start to end. Raises if end is not after start."""

    duration = minutes_since_midnight(end) - minutes_since_midnight(start)
    if duration <= 0:
        raise ValueError("End time must be after start time.")
    return duration


def _occupied_minutes(duration: timedelta) -> int:
    return int(duration.total_seconds() // 60)


def _anchor_occupied_minutes(anchor: Anchor) -> int:
    return _occupied_minutes(anchor.duration)


def compute_gaps(*, bounds: DayBounds, anchors: Sequence[Anchor]) -> tuple[Gap, ...]:
    """Return Gaps between wake/sleep and Anchors, in start order."""

    wake = parse_clock(bounds.wake)
    sleep = parse_clock(bounds.sleep)
    ordered = sorted(anchors, key=lambda anchor: minutes_since_wake(anchor.start, wake=wake))

    gaps: list[Gap] = []
    cursor = wake
    for anchor in ordered:
        if minutes_since_wake(anchor.start, wake=wake) > minutes_since_wake(cursor, wake=wake):
            gaps.append(Gap(start=cursor, end=anchor.start))
        cursor = anchor.end
    if minutes_since_wake(sleep, wake=wake) > minutes_since_wake(cursor, wake=wake):
        gaps.append(Gap(start=cursor, end=sleep))
    return tuple(gaps)


def _find_gap_for_start(gaps: Sequence[Gap], start: time, *, wake: time) -> Gap | None:
    start_minutes = minutes_since_wake(start, wake=wake)
    for gap in gaps:
        gap_start = minutes_since_wake(gap.start, wake=wake)
        gap_end = minutes_since_wake(gap.end, wake=wake)
        if gap_start <= start_minutes < gap_end:
            return gap
    return None


def snap_flex_to_gap_start(flex: Flex, gap: Gap) -> Flex:
    """Place Flex at the start of a Gap."""

    return flex.with_start(gap.start)


def validate_flex_placement(
    flex: Flex,
    *,
    gaps: Sequence[Gap],
    anchors: Sequence[Anchor],
    other_flexes: Sequence[Flex],
    wake: time,
) -> bool:
    """Return True when a placed Flex fits its Gap and does not overlap."""

    if flex.start is None or flex.end is None:
        return False

    gap = _find_gap_for_start(gaps, flex.start, wake=wake)
    if gap is None:
        return False

    start_minutes = minutes_since_wake(flex.start, wake=wake)
    end_minutes = start_minutes + _occupied_minutes(flex.duration)
    gap_end_minutes = minutes_since_wake(gap.end, wake=wake)
    if end_minutes > gap_end_minutes:
        return False

    for anchor in anchors:
        anchor_start = minutes_since_wake(anchor.start, wake=wake)
        anchor_end = anchor_start + _anchor_occupied_minutes(anchor)
        if start_minutes < anchor_end and end_minutes > anchor_start:
            return False

    for other in other_flexes:
        if other.start is None or other.end is None:
            continue
        other_start = minutes_since_wake(other.start, wake=wake)
        other_end = other_start + _occupied_minutes(other.duration)
        if start_minutes < other_end and end_minutes > other_start:
            return False

    return True


def finalize_plan(
    *,
    bounds: DayBounds,
    drafts: Sequence[Draft],
    anchors: Sequence[Anchor],
    flexes: Sequence[Flex] = (),
) -> FinalizeResult:
    """Day bounds and Anchor overlap checks are inclusive at the boundary: an
    Anchor may start exactly at wake and its occupied time may end exactly at
    sleep; two Anchors may be back-to-back (one ends exactly when the next
    starts) without counting as overlap or out-of-bounds.
    """
    blockers: list[Blocker] = [DraftUnfinishedBlocker(draft=draft) for draft in drafts]

    wake = parse_clock(bounds.wake)
    sleep = parse_clock(bounds.sleep)

    if wake == sleep:
        blockers.append(DegenerateDayBoundsBlocker(bounds=bounds))

    sleep_minutes = minutes_since_wake(sleep, wake=wake)

    ordered_anchors = tuple(
        sorted(anchors, key=lambda anchor: minutes_since_wake(anchor.start, wake=wake))
    )

    for anchor in ordered_anchors:
        start_minutes = minutes_since_wake(anchor.start, wake=wake)
        end_minutes = start_minutes + _anchor_occupied_minutes(anchor)
        if end_minutes > sleep_minutes:
            blockers.append(AnchorOutOfBoundsBlocker(anchor=anchor))

    for first, second in zip(ordered_anchors, ordered_anchors[1:]):
        first_end_minutes = minutes_since_wake(
            first.start, wake=wake
        ) + _anchor_occupied_minutes(first)
        second_start_minutes = minutes_since_wake(second.start, wake=wake)
        if second_start_minutes < first_end_minutes:
            blockers.append(AnchorOverlapBlocker(first=first, second=second))

    gaps = compute_gaps(bounds=bounds, anchors=ordered_anchors)

    placed_flexes: list[Flex] = []
    for flex in flexes:
        if flex.start is None:
            blockers.append(FlexUnplacedBlocker(flex=flex))
            continue
        if not validate_flex_placement(
            flex,
            gaps=gaps,
            anchors=ordered_anchors,
            other_flexes=placed_flexes,
            wake=wake,
        ):
            blockers.append(FlexDoesNotFitBlocker(flex=flex))
            continue
        placed_flexes.append(flex)

    if blockers:
        return FinalizeResult(plan=None, blockers=tuple(blockers))

    ordered_flexes = tuple(
        sorted(placed_flexes, key=lambda flex: minutes_since_wake(flex.start, wake=wake))
    )
    return FinalizeResult(
        plan=FinalizedPlan(bounds=bounds, anchors=ordered_anchors, flexes=ordered_flexes),
        blockers=(),
    )


def describe_blocker(blocker: Blocker) -> str:
    """Human-readable summary of a blocker, for CLI/adapter output only."""

    if isinstance(blocker, DraftUnfinishedBlocker):
        return f"Draft '{blocker.draft.name}' is not yet promoted to an Anchor or Flex."
    if isinstance(blocker, AnchorOverlapBlocker):
        return (
            f"Anchor '{blocker.first.name}' ({blocker.first.start:%H:%M}\u2013"
            f"{blocker.first.end:%H:%M}) overlaps Anchor '{blocker.second.name}' "
            f"({blocker.second.start:%H:%M}\u2013{blocker.second.end:%H:%M})."
        )
    if isinstance(blocker, AnchorOutOfBoundsBlocker):
        return (
            f"Anchor '{blocker.anchor.name}' "
            f"({blocker.anchor.start:%H:%M}\u2013{blocker.anchor.end:%H:%M}) "
            "sits outside day bounds."
        )
    if isinstance(blocker, FlexUnplacedBlocker):
        return f"Flex '{blocker.flex.name}' is not yet placed in a Gap."
    if isinstance(blocker, DegenerateDayBoundsBlocker):
        return (
            f"Wake and sleep are both {blocker.bounds.wake}, leaving a zero-length day."
        )
    return (
        f"Flex '{blocker.flex.name}' "
        f"({blocker.flex.start:%H:%M}\u2013{blocker.flex.end:%H:%M}) "
        "does not fit in its Gap."
    )
