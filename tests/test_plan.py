from datetime import date, datetime, time, timedelta

from tomorrow.checklists import Checklist
from tomorrow.defaults import DayBounds
from tomorrow.domain import Anchor, Flex
from tomorrow.plan import (
    default_plan_date,
    format_plan_date,
    plan_filename,
    render_plan,
)


def test_plan_date_tuesday_evening_is_wednesday() -> None:
    assert default_plan_date(datetime(2026, 8, 11, 22, 0), wake="06:30") == date(2026, 8, 12)


def test_plan_date_wednesday_before_wake_is_wednesday() -> None:
    assert default_plan_date(datetime(2026, 8, 12, 0, 30), wake="06:30") == date(2026, 8, 12)


def test_plan_date_wednesday_after_wake_is_thursday() -> None:
    assert default_plan_date(datetime(2026, 8, 12, 8, 0), wake="06:30") == date(2026, 8, 13)


def test_format_plan_date_uses_english_long_form() -> None:
    assert format_plan_date(date(2026, 8, 11)) == "Tuesday, 11 August 2026"


def test_plan_filename_uses_iso_date() -> None:
    assert plan_filename(date(2026, 8, 11)) == "2026-08-11.html"


def test_render_plan_shows_date_and_day_bounds() -> None:
    html = render_plan(
        plan_date=date(2026, 8, 11),
        bounds=DayBounds(wake="06:30", sleep="23:00"),
    )

    assert "Tuesday, 11 August 2026" in html
    assert "Wake 06:30" in html
    assert "Sleep 23:00" in html
    assert "<!DOCTYPE html>" in html
    assert '<div class="plan-weather">' not in html


def test_render_plan_shows_weather_one_liner_when_provided() -> None:
    html = render_plan(
        plan_date=date(2026, 8, 11),
        bounds=DayBounds(wake="06:30", sleep="23:00"),
        weather="18° / 24° · partly cloudy",
    )

    assert '<div class="plan-weather">18° / 24° · partly cloudy</div>' in html


def test_render_plan_uses_tl_accordion_chrome() -> None:
    html = render_plan(
        plan_date=date(2026, 8, 11),
        bounds=DayBounds(wake="06:30", sleep="23:00"),
    )

    assert 'class="v-tl-base v-tl-accordion"' in html
    assert "Instrument Serif" in html
    assert "↑ 06:30 wake" in html
    assert "23:00 sleep ↓" in html
    assert "Pack &amp; prep" in html
    assert "rail-wrap" in html


def test_render_plan_has_no_prototype_switcher() -> None:
    html = render_plan(
        plan_date=date(2026, 8, 11),
        bounds=DayBounds(wake="06:30", sleep="23:00"),
    )

    assert "proto-switcher" not in html
    assert "proto-banner" not in html
    assert "v-tl-tabs" not in html
    assert "v-tl-cards" not in html


def test_render_plan_shows_anchors_in_start_order() -> None:
    breakfast = Anchor(name="Breakfast", start=time(8, 0), duration=timedelta(minutes=30))
    standup = Anchor(name="Standup", start=time(7, 0), duration=timedelta(minutes=15))

    html = render_plan(
        plan_date=date(2026, 8, 11),
        bounds=DayBounds(wake="06:30", sleep="23:00"),
        anchors=[breakfast, standup],
    )

    assert html.index("Standup") < html.index("Breakfast")
    assert "07:00" in html
    assert "07:15" in html
    assert "08:00" in html
    assert "08:30" in html
    assert 'class="block anchor"' in html


def test_render_plan_with_no_anchors_has_wake_to_sleep_gap() -> None:
    html = render_plan(
        plan_date=date(2026, 8, 11),
        bounds=DayBounds(wake="06:30", sleep="23:00"),
    )

    assert 'class="block anchor"' not in html
    assert 'class="block flex"' not in html
    assert "Gap · 16h 30m" in html


def test_render_plan_shows_flex_gaps_and_complete_timeline() -> None:
    standup = Anchor(name="Standup", start=time(7, 0), duration=timedelta(minutes=15))
    sauna = Flex(name="Sauna", duration=timedelta(minutes=30), start=time(7, 15))

    html = render_plan(
        plan_date=date(2026, 8, 11),
        bounds=DayBounds(wake="06:30", sleep="23:00"),
        anchors=[standup],
        flexes=[sauna],
    )

    assert html.index("Standup") < html.index("Sauna")
    assert 'class="block anchor"' in html
    assert 'class="block flex"' in html
    assert "Gap · 30m" in html
    assert "07:15" in html
    assert "07:45" in html


def test_render_plan_shows_prep_accordion_for_attached_checklists() -> None:
    gym = Anchor(
        name="Gym",
        start=time(18, 0),
        duration=timedelta(minutes=90),
        checklist="gym-bag",
    )
    checklists = {
        "gym-bag": Checklist(
            name="Gym bag",
            items=("Water bottle", "Towel", "Lock"),
        )
    }

    html = render_plan(
        plan_date=date(2026, 8, 11),
        bounds=DayBounds(wake="06:30", sleep="23:00"),
        anchors=[gym],
        checklists=checklists,
    )

    assert 'id="prep-active"' in html
    assert 'itemId: "gym-0"' in html
    assert 'checklistId: "gym-bag"' in html
    assert '"Water bottle"' in html
    assert '"Gym bag"' in html
    assert "localStorage" in html
    assert 'dateKey: "2026-08-11"' in html


def test_render_plan_orders_prep_bundles_by_parent_start_time() -> None:
    gym = Anchor(
        name="Gym",
        start=time(18, 0),
        duration=timedelta(minutes=90),
        checklist="gym-bag",
    )
    morning = Anchor(
        name="Wake",
        start=time(6, 30),
        duration=timedelta(minutes=45),
        checklist="morning-out",
    )
    checklists = {
        "gym-bag": Checklist(name="Gym bag", items=("Towel",)),
        "morning-out": Checklist(name="Before leaving", items=("Keys",)),
    }

    html = render_plan(
        plan_date=date(2026, 8, 11),
        bounds=DayBounds(wake="06:30", sleep="23:00"),
        anchors=[gym, morning],
        checklists=checklists,
    )

    assert html.index('"Wake"') < html.index('"Gym"')


def test_render_plan_timeline_stays_schedule_only_without_inline_checklists() -> None:
    gym = Anchor(
        name="Gym",
        start=time(18, 0),
        duration=timedelta(minutes=90),
        checklist="gym-bag",
    )
    checklists = {"gym-bag": Checklist(name="Gym bag", items=("Towel",))}

    html = render_plan(
        plan_date=date(2026, 8, 11),
        bounds=DayBounds(wake="06:30", sleep="23:00"),
        anchors=[gym],
        checklists=checklists,
    )

    rail_start = html.index('class="rail-wrap"')
    prep_start = html.index('class="prep-section"')
    rail_html = html[rail_start:prep_start]
    assert '"Towel"' not in rail_html
    assert 'type="checkbox"' not in rail_html
