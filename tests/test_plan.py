from datetime import date

from tomorrow.defaults import DayBounds
from tomorrow.plan import (
    default_plan_date,
    format_plan_date,
    plan_filename,
    render_stub_plan,
)


def test_default_plan_date_is_tomorrow() -> None:
    assert default_plan_date(date(2026, 8, 10)) == date(2026, 8, 11)


def test_format_plan_date_uses_english_long_form() -> None:
    assert format_plan_date(date(2026, 8, 11)) == "Tuesday, 11 August 2026"


def test_plan_filename_uses_iso_date() -> None:
    assert plan_filename(date(2026, 8, 11)) == "2026-08-11.html"


def test_render_stub_plan_shows_date_and_day_bounds() -> None:
    html = render_stub_plan(
        plan_date=date(2026, 8, 11),
        bounds=DayBounds(wake="06:30", sleep="23:00"),
    )

    assert "Tuesday, 11 August 2026" in html
    assert "Wake 06:30" in html
    assert "Sleep 23:00" in html
    assert "<!DOCTYPE html>" in html


def test_render_stub_plan_uses_tl_accordion_chrome() -> None:
    html = render_stub_plan(
        plan_date=date(2026, 8, 11),
        bounds=DayBounds(wake="06:30", sleep="23:00"),
    )

    assert 'class="v-tl-base v-tl-accordion"' in html
    assert "Instrument Serif" in html
    assert "↑ 06:30 wake" in html
    assert "23:00 sleep ↓" in html
    assert "Pack &amp; prep" in html
    assert "rail-wrap" in html


def test_render_stub_plan_has_no_prototype_switcher() -> None:
    html = render_stub_plan(
        plan_date=date(2026, 8, 11),
        bounds=DayBounds(wake="06:30", sleep="23:00"),
    )

    assert "proto-switcher" not in html
    assert "proto-banner" not in html
    assert "v-tl-tabs" not in html
    assert "v-tl-cards" not in html
