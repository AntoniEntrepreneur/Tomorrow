"""Pure Plan finalization seam.

Input: day bounds, any remaining Drafts, and candidate Anchors.
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

    @property
    def end(self) -> time:
        combined = datetime.combine(date(2000, 1, 1), self.start) + self.duration
        return combined.time()


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


Blocker = Union[DraftUnfinishedBlocker, AnchorOverlapBlocker, AnchorOutOfBoundsBlocker]


@dataclass(frozen=True)
class FinalizedPlan:
    """A consistent, renderable Plan: day bounds plus ordered Anchors."""

    bounds: DayBounds
    anchors: tuple[Anchor, ...]


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


def minutes_between(start: time, end: time) -> int:
    """Whole minutes from start to end. Raises if end is not after start."""

    duration = minutes_since_midnight(end) - minutes_since_midnight(start)
    if duration <= 0:
        raise ValueError("End time must be after start time.")
    return duration


def _bound_minutes(value: str) -> int:
    return minutes_since_midnight(parse_clock(value))


def _occupied_minutes(anchor: Anchor) -> int:
    return int(anchor.duration.total_seconds() // 60)


def finalize_plan(
    *,
    bounds: DayBounds,
    drafts: Sequence[Draft],
    anchors: Sequence[Anchor],
) -> FinalizeResult:
    """Day bounds and Anchor overlap checks are inclusive at the boundary: an
    Anchor may start exactly at wake and its occupied time may end exactly at
    sleep; two Anchors may be back-to-back (one ends exactly when the next
    starts) without counting as overlap or out-of-bounds.
    """
    blockers: list[Blocker] = [DraftUnfinishedBlocker(draft=draft) for draft in drafts]

    wake_minutes = _bound_minutes(bounds.wake)
    sleep_minutes = _bound_minutes(bounds.sleep)

    ordered = tuple(sorted(anchors, key=lambda anchor: minutes_since_midnight(anchor.start)))

    for anchor in ordered:
        start_minutes = minutes_since_midnight(anchor.start)
        end_minutes = start_minutes + _occupied_minutes(anchor)
        if start_minutes < wake_minutes or end_minutes > sleep_minutes:
            blockers.append(AnchorOutOfBoundsBlocker(anchor=anchor))

    for first, second in zip(ordered, ordered[1:]):
        first_end_minutes = minutes_since_midnight(first.start) + _occupied_minutes(first)
        second_start_minutes = minutes_since_midnight(second.start)
        if second_start_minutes < first_end_minutes:
            blockers.append(AnchorOverlapBlocker(first=first, second=second))

    if blockers:
        return FinalizeResult(plan=None, blockers=tuple(blockers))

    return FinalizeResult(plan=FinalizedPlan(bounds=bounds, anchors=ordered), blockers=())


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
    return (
        f"Anchor '{blocker.anchor.name}' "
        f"({blocker.anchor.start:%H:%M}\u2013{blocker.anchor.end:%H:%M}) "
        "sits outside day bounds."
    )
