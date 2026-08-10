from datetime import time, timedelta

import pytest

from tomorrow.defaults import DayBounds
from tomorrow.domain import (
    Anchor,
    AnchorOutOfBoundsBlocker,
    AnchorOverlapBlocker,
    Draft,
    DraftUnfinishedBlocker,
    finalize_plan,
    minutes_between,
    parse_clock,
)

BOUNDS = DayBounds(wake="06:30", sleep="23:00")


def test_parse_clock_reads_hh_mm() -> None:
    assert parse_clock("07:15") == time(7, 15)


def test_minutes_between_returns_whole_minutes() -> None:
    assert minutes_between(time(7, 0), time(7, 45)) == 45


def test_minutes_between_rejects_end_not_after_start() -> None:
    with pytest.raises(ValueError):
        minutes_between(time(8, 0), time(8, 0))


def test_finalize_plan_happy_path_returns_anchors_in_order() -> None:
    breakfast = Anchor(name="Breakfast", start=time(8, 0), duration=timedelta(minutes=30))
    standup = Anchor(name="Standup", start=time(7, 0), duration=timedelta(minutes=15))

    result = finalize_plan(bounds=BOUNDS, drafts=[], anchors=[breakfast, standup])

    assert result.ok
    assert result.blockers == ()
    assert result.plan is not None
    assert result.plan.bounds == BOUNDS
    assert result.plan.anchors == (standup, breakfast)


def test_finalize_plan_blocks_while_a_draft_remains_unpromoted() -> None:
    result = finalize_plan(bounds=BOUNDS, drafts=[Draft(name="Call mom")], anchors=[])

    assert not result.ok
    assert result.plan is None
    assert result.blockers == (DraftUnfinishedBlocker(draft=Draft(name="Call mom")),)


def test_finalize_plan_blocks_on_overlapping_anchors() -> None:
    gym = Anchor(name="Gym", start=time(7, 0), duration=timedelta(minutes=60))
    call = Anchor(name="Call", start=time(7, 30), duration=timedelta(minutes=30))

    result = finalize_plan(bounds=BOUNDS, drafts=[], anchors=[gym, call])

    assert not result.ok
    assert result.plan is None
    assert result.blockers == (AnchorOverlapBlocker(first=gym, second=call),)


def test_finalize_plan_blocks_on_anchor_before_wake() -> None:
    early = Anchor(name="Early flight", start=time(5, 0), duration=timedelta(minutes=30))

    result = finalize_plan(bounds=BOUNDS, drafts=[], anchors=[early])

    assert not result.ok
    assert result.blockers == (AnchorOutOfBoundsBlocker(anchor=early),)


def test_finalize_plan_blocks_on_anchor_past_sleep() -> None:
    late = Anchor(name="Late film", start=time(22, 30), duration=timedelta(minutes=90))

    result = finalize_plan(bounds=BOUNDS, drafts=[], anchors=[late])

    assert not result.ok
    assert result.blockers == (AnchorOutOfBoundsBlocker(anchor=late),)


def test_finalize_plan_with_no_anchors_or_drafts_is_a_trivially_finished_plan() -> None:
    result = finalize_plan(bounds=BOUNDS, drafts=[], anchors=[])

    assert result.ok
    assert result.plan is not None
    assert result.plan.anchors == ()


def test_anchor_touching_boundaries_does_not_overlap_or_go_out_of_bounds() -> None:
    wake_up = Anchor(name="Wake routine", start=time(6, 30), duration=timedelta(minutes=30))
    wind_down = Anchor(name="Wind down", start=time(22, 0), duration=timedelta(minutes=60))

    result = finalize_plan(bounds=BOUNDS, drafts=[], anchors=[wake_up, wind_down])

    assert result.ok
