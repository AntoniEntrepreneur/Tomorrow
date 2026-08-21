from pathlib import Path

from tomorrow.activity_templates import load_activity_template_library
from tomorrow.checklists import load_checklist_library
from tomorrow.day_templates import load_day_template, named_day_template_path
from tomorrow.library import (
    delete_activity_template,
    delete_checklist,
    delete_day_template,
    save_activity_template,
    save_checklist,
    save_day_template,
)


def test_save_checklist_round_trips_through_the_filesystem(tmp_path: Path) -> None:
    checklist_id = save_checklist(
        tmp_path, checklist_id="gym-bag", name="Gym bag", items=["Towel", "Lock"]
    )

    library = load_checklist_library(tmp_path / "data")

    assert checklist_id == "gym-bag"
    assert library["gym-bag"].name == "Gym bag"
    assert library["gym-bag"].items == ("Towel", "Lock")


def test_delete_checklist_removes_the_file(tmp_path: Path) -> None:
    save_checklist(tmp_path, checklist_id="gym-bag", name="Gym bag", items=["Towel"])

    delete_checklist(tmp_path, checklist_id="gym-bag")

    assert load_checklist_library(tmp_path / "data") == {}


def test_delete_checklist_is_a_no_op_when_missing(tmp_path: Path) -> None:
    delete_checklist(tmp_path, checklist_id="missing")


def test_save_activity_template_round_trips_anchor_shaped_entry(tmp_path: Path) -> None:
    activity_id = save_activity_template(
        tmp_path,
        activity_id="therapy",
        name="Therapy",
        duration_minutes=50,
        start="16:00",
    )

    library = load_activity_template_library(tmp_path / "data")

    assert activity_id == "therapy"
    assert library["therapy"].name == "Therapy"
    assert library["therapy"].start.strftime("%H:%M") == "16:00"


def test_save_activity_template_round_trips_flex_shaped_entry_with_checklist(
    tmp_path: Path,
) -> None:
    save_activity_template(
        tmp_path,
        activity_id="deep-work",
        name="Deep work",
        duration_minutes=90,
        checklist="focus-kit",
    )

    library = load_activity_template_library(tmp_path / "data")

    assert library["deep-work"].start is None
    assert library["deep-work"].checklist == "focus-kit"


def test_delete_activity_template_removes_the_file(tmp_path: Path) -> None:
    save_activity_template(
        tmp_path, activity_id="deep-work", name="Deep work", duration_minutes=90
    )

    delete_activity_template(tmp_path, activity_id="deep-work")

    assert load_activity_template_library(tmp_path / "data") == {}


def test_save_day_template_round_trips_entries(tmp_path: Path) -> None:
    template_id = save_day_template(
        tmp_path,
        template_id="tuesday",
        name="Tuesday",
        anchors=[{"name": "Standup", "start": "07:00", "duration": 15}],
        flexes=[{"name": "Sauna", "duration": 30, "checklist": "sauna-kit"}],
    )

    path = named_day_template_path(tmp_path / "data", "tuesday")
    seed = load_day_template(path, {})

    assert template_id == "tuesday"
    assert seed is not None
    assert seed.anchors[0].name == "Standup"
    assert seed.flexes[0].checklist == "sauna-kit"


def test_save_day_template_with_activity_reference(tmp_path: Path) -> None:
    save_activity_template(
        tmp_path, activity_id="therapy", name="Therapy", duration_minutes=50, start="16:00"
    )
    save_day_template(
        tmp_path,
        template_id="tuesday",
        name="Tuesday",
        anchors=[{"activity": "therapy"}],
    )

    activity_library = load_activity_template_library(tmp_path / "data")
    path = named_day_template_path(tmp_path / "data", "tuesday")
    seed = load_day_template(path, activity_library)

    assert seed is not None
    assert seed.anchors[0].name == "Therapy"


def test_save_day_template_enforces_single_weekday_default(tmp_path: Path) -> None:
    save_day_template(tmp_path, template_id="a", name="A", weekday="tuesday")

    save_day_template(tmp_path, template_id="b", name="B", weekday="tuesday")

    from tomorrow.day_templates import default_day_template_path
    from datetime import date

    winner = default_day_template_path(tmp_path / "data", date(2026, 8, 11))
    assert winner.stem == "b"

    a_data = (tmp_path / "data" / "templates" / "a.toml").read_text(encoding="utf-8")
    assert "weekday" not in a_data


def test_delete_day_template_removes_the_file(tmp_path: Path) -> None:
    save_day_template(tmp_path, template_id="tuesday", name="Tuesday")

    delete_day_template(tmp_path, template_id="tuesday")

    assert not named_day_template_path(tmp_path / "data", "tuesday").exists()


def test_delete_referenced_activity_template_does_not_touch_day_template(
    tmp_path: Path,
) -> None:
    save_activity_template(
        tmp_path, activity_id="therapy", name="Therapy", duration_minutes=50, start="16:00"
    )
    save_day_template(
        tmp_path,
        template_id="tuesday",
        name="Tuesday",
        anchors=[{"activity": "therapy"}],
    )

    delete_activity_template(tmp_path, activity_id="therapy")

    path = named_day_template_path(tmp_path / "data", "tuesday")
    assert path.exists()
    seed = load_day_template(path, {})
    assert seed is not None
    assert seed.anchors == ()
