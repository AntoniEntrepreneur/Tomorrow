from datetime import time, timedelta

import pytest

from tomorrow.defaults import DayBounds
from tomorrow.domain import (
    Anchor,
    AnchorOutOfBoundsBlocker,
    AnchorOverlapBlocker,
    DegenerateDayBoundsBlocker,
    Draft,
    DraftUnfinishedBlocker,
    Flex,
    FlexDoesNotFitBlocker,
    FlexUnplacedBlocker,
    Gap,
    compute_gaps,
    finalize_plan,
    minutes_between,
    minutes_since_wake,
    parse_clock,
    snap_flex_to_gap_start,
    validate_flex_placement,
)

BOUNDS = DayBounds(wake="06:30", sleep="23:00")
OVERNIGHT_BOUNDS = DayBounds(wake="07:00", sleep="01:00")


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


def test_compute_gaps_shows_free_stretches_between_bounds_and_anchors() -> None:
    standup = Anchor(name="Standup", start=time(7, 0), duration=timedelta(minutes=15))
    lunch = Anchor(name="Lunch", start=time(12, 0), duration=timedelta(minutes=60))

    gaps = compute_gaps(bounds=BOUNDS, anchors=[standup, lunch])

    assert gaps == (
        Gap(start=time(6, 30), end=time(7, 0)),
        Gap(start=time(7, 15), end=time(12, 0)),
        Gap(start=time(13, 0), end=time(23, 0)),
    )


def test_finalize_plan_blocks_on_unplaced_flex() -> None:
    sauna = Flex(name="Sauna", duration=timedelta(minutes=30))

    result = finalize_plan(bounds=BOUNDS, drafts=[], anchors=[], flexes=[sauna])

    assert not result.ok
    assert result.blockers == (FlexUnplacedBlocker(flex=sauna),)


def test_finalize_plan_happy_path_with_placed_flex_in_gap() -> None:
    standup = Anchor(name="Standup", start=time(7, 0), duration=timedelta(minutes=15))
    sauna = Flex(
        name="Sauna",
        duration=timedelta(minutes=30),
        start=time(7, 15),
    )

    result = finalize_plan(bounds=BOUNDS, drafts=[], anchors=[standup], flexes=[sauna])

    assert result.ok
    assert result.plan is not None
    assert result.plan.anchors == (standup,)
    assert result.plan.flexes == (sauna,)


def test_finalize_plan_blocks_when_flex_overruns_gap_end() -> None:
    standup = Anchor(name="Standup", start=time(7, 0), duration=timedelta(minutes=15))
    lunch = Anchor(name="Lunch", start=time(12, 0), duration=timedelta(minutes=60))
    too_long = Flex(
        name="Deep work",
        duration=timedelta(minutes=300),
        start=time(7, 15),
    )

    result = finalize_plan(
        bounds=BOUNDS,
        drafts=[],
        anchors=[standup, lunch],
        flexes=[too_long],
    )

    assert not result.ok
    assert result.blockers == (FlexDoesNotFitBlocker(flex=too_long),)


def test_snap_to_gap_start_produces_a_valid_placement() -> None:
    standup = Anchor(name="Standup", start=time(7, 0), duration=timedelta(minutes=15))
    gaps = compute_gaps(bounds=BOUNDS, anchors=[standup])
    sauna = Flex(name="Sauna", duration=timedelta(minutes=30))

    placed = snap_flex_to_gap_start(sauna, gaps[1])
    assert placed.start == time(7, 15)
    assert validate_flex_placement(
        placed, gaps=gaps, anchors=[standup], other_flexes=[], wake=time(6, 30)
    )


def test_change_duration_then_placed_flex_fits() -> None:
    standup = Anchor(name="Standup", start=time(7, 0), duration=timedelta(minutes=15))
    lunch = Anchor(name="Lunch", start=time(12, 0), duration=timedelta(minutes=60))
    resized = Flex(
        name="Deep work",
        duration=timedelta(minutes=60),
        start=time(7, 15),
    )

    result = finalize_plan(
        bounds=BOUNDS,
        drafts=[],
        anchors=[standup, lunch],
        flexes=[resized],
    )

    assert result.ok


def test_finalize_plan_with_no_flexes_is_trivially_finished() -> None:
    standup = Anchor(name="Standup", start=time(7, 0), duration=timedelta(minutes=15))

    result = finalize_plan(bounds=BOUNDS, drafts=[], anchors=[standup], flexes=[])

    assert result.ok
    assert result.plan is not None
    assert result.plan.flexes == ()


def test_minutes_since_wake_wraps_past_midnight() -> None:
    assert minutes_since_wake(time(0, 30), wake=time(7, 0)) == 17 * 60 + 30
    assert minutes_since_wake(time(7, 0), wake=time(7, 0)) == 0
    assert minutes_since_wake(time(6, 59), wake=time(7, 0)) == 1439


def test_compute_gaps_handles_sleep_past_midnight() -> None:
    dinner = Anchor(name="Dinner", start=time(19, 0), duration=timedelta(minutes=60))

    gaps = compute_gaps(bounds=OVERNIGHT_BOUNDS, anchors=[dinner])

    assert gaps == (
        Gap(start=time(7, 0), end=time(19, 0)),
        Gap(start=time(20, 0), end=time(1, 0)),
    )


def test_finalize_plan_places_flex_in_gap_after_midnight() -> None:
    dinner = Anchor(name="Dinner", start=time(19, 0), duration=timedelta(minutes=60))
    late_read = Flex(name="Read", duration=timedelta(minutes=30), start=time(0, 15))

    result = finalize_plan(
        bounds=OVERNIGHT_BOUNDS, drafts=[], anchors=[dinner], flexes=[late_read]
    )

    assert result.ok
    assert result.plan is not None
    assert result.plan.flexes == (late_read,)


def test_finalize_plan_accepts_anchor_after_midnight_within_bounds() -> None:
    late_snack = Anchor(name="Snack", start=time(0, 30), duration=timedelta(minutes=15))

    result = finalize_plan(bounds=OVERNIGHT_BOUNDS, drafts=[], anchors=[late_snack])

    assert result.ok


def test_finalize_plan_flags_anchor_that_looks_early_but_is_out_of_bounds() -> None:
    # 05:00 looks "early" by raw clock time, but with wake=07:00/sleep=01:00
    # it falls after sleep once expressed as a wake-relative offset.
    too_early = Anchor(name="Too early", start=time(5, 0), duration=timedelta(minutes=30))

    result = finalize_plan(bounds=OVERNIGHT_BOUNDS, drafts=[], anchors=[too_early])

    assert not result.ok
    assert result.blockers == (AnchorOutOfBoundsBlocker(anchor=too_early),)


def test_finalize_plan_catches_overlap_between_two_anchors_after_midnight() -> None:
    first = Anchor(name="First", start=time(0, 0), duration=timedelta(minutes=45))
    second = Anchor(name="Second", start=time(0, 30), duration=timedelta(minutes=30))

    result = finalize_plan(bounds=OVERNIGHT_BOUNDS, drafts=[], anchors=[first, second])

    assert not result.ok
    assert result.blockers == (AnchorOverlapBlocker(first=first, second=second),)


def test_finalize_plan_blocks_when_wake_equals_sleep() -> None:
    degenerate_bounds = DayBounds(wake="07:00", sleep="07:00")

    result = finalize_plan(bounds=degenerate_bounds, drafts=[], anchors=[])

    assert not result.ok
    assert result.blockers == (DegenerateDayBoundsBlocker(bounds=degenerate_bounds),)
