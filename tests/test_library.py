from datetime import date
from pathlib import Path

import pytest

from tomorrow.activity_templates import load_activity_template_library
from tomorrow.checklists import load_checklist_library
from tomorrow.day_templates import (
    default_day_template_path,
    load_day_template,
    named_day_template_path,
)
from tomorrow.library import (
    delete_activity_template,
    delete_checklist,
    delete_day_template,
    save_activity_template,
    save_checklist,
    save_day_template,
)


# --- Checklists -------------------------------------------------------------


def test_save_checklist_creates_with_a_name_only_and_derives_the_id(tmp_path: Path) -> None:
    checklist_id = save_checklist(tmp_path, name="Gym bag", items=["Towel", "Lock"])

    library = load_checklist_library(tmp_path / "data")

    assert checklist_id == "gym-bag"
    assert library["gym-bag"].name == "Gym bag"
    assert library["gym-bag"].items == ("Towel", "Lock")


def test_save_checklist_items_round_trip_including_commas_and_order(tmp_path: Path) -> None:
    save_checklist(tmp_path, name="Gym bag", items=["Shirt, spare", "Towel", "Lock"])

    library = load_checklist_library(tmp_path / "data")

    assert library["gym-bag"].items == ("Shirt, spare", "Towel", "Lock")


def test_save_checklist_rejects_a_create_name_collision_under_normalization(
    tmp_path: Path,
) -> None:
    save_checklist(tmp_path, name="Gym Bag!", items=["Towel"])

    with pytest.raises(ValueError, match="Gym Bag!"):
        save_checklist(tmp_path, name="gym bag", items=["Lock"])


def test_save_checklist_and_activity_template_may_share_a_name(tmp_path: Path) -> None:
    save_checklist(tmp_path, name="Therapy", items=["Notebook"])

    activity_id = save_activity_template(
        tmp_path, name="Therapy", duration_minutes=50, start="16:00"
    )

    assert activity_id == "therapy"


def test_save_checklist_update_overwrites_in_place(tmp_path: Path) -> None:
    checklist_id = save_checklist(tmp_path, name="Gym bag", items=["Towel"])

    save_checklist(tmp_path, id=checklist_id, name="Gym bag", items=["Towel", "Lock"])

    library = load_checklist_library(tmp_path / "data")
    assert checklist_id == "gym-bag"
    assert library["gym-bag"].items == ("Towel", "Lock")


def test_save_checklist_rename_keeps_the_id(tmp_path: Path) -> None:
    checklist_id = save_checklist(tmp_path, name="Gym bag", items=["Towel"])

    save_checklist(tmp_path, id=checklist_id, name="Gym Kit", items=["Towel"])

    library = load_checklist_library(tmp_path / "data")
    assert checklist_id not in library or library[checklist_id].name != "Gym bag"
    assert library["gym-bag"].name == "Gym Kit"


def test_save_checklist_rename_colliding_with_another_entry_is_rejected(tmp_path: Path) -> None:
    save_checklist(tmp_path, name="Gym bag", items=["Towel"])
    sauna_id = save_checklist(tmp_path, name="Sauna kit", items=["Towel"])

    with pytest.raises(ValueError):
        save_checklist(tmp_path, id=sauna_id, name="Gym Bag", items=["Towel"])


def test_save_checklist_update_keeping_its_own_name_is_not_a_self_collision(
    tmp_path: Path,
) -> None:
    checklist_id = save_checklist(tmp_path, name="Gym bag", items=["Towel"])

    save_checklist(tmp_path, id=checklist_id, name="Gym bag", items=["Towel", "Lock"])

    library = load_checklist_library(tmp_path / "data")
    assert library["gym-bag"].items == ("Towel", "Lock")


def test_save_checklist_update_of_a_missing_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_checklist(tmp_path, id="does-not-exist", name="Gym bag", items=["Towel"])


def test_save_checklist_slug_suffix_after_a_rename_frees_the_name(tmp_path: Path) -> None:
    first_id = save_checklist(tmp_path, name="Gym bag", items=["Towel"])
    save_checklist(tmp_path, id=first_id, name="Gym Kit", items=["Towel"])

    second_id = save_checklist(tmp_path, name="Gym bag", items=["Lock"])

    assert second_id == "gym-bag-2"
    library = load_checklist_library(tmp_path / "data")
    assert library["gym-bag"].name == "Gym Kit"
    assert library["gym-bag-2"].name == "Gym bag"


def test_delete_checklist_removes_the_file(tmp_path: Path) -> None:
    save_checklist(tmp_path, name="Gym bag", items=["Towel"])

    delete_checklist(tmp_path, checklist_id="gym-bag")

    assert load_checklist_library(tmp_path / "data") == {}


def test_delete_checklist_is_a_no_op_when_missing(tmp_path: Path) -> None:
    delete_checklist(tmp_path, checklist_id="missing")


# --- Activity Templates ------------------------------------------------------


def test_save_activity_template_round_trips_anchor_shaped_entry(tmp_path: Path) -> None:
    activity_id = save_activity_template(
        tmp_path, name="Therapy", duration_minutes=50, start="16:00"
    )

    library = load_activity_template_library(tmp_path / "data")

    assert activity_id == "therapy"
    assert library["therapy"].name == "Therapy"
    assert library["therapy"].start.strftime("%H:%M") == "16:00"


def test_save_activity_template_round_trips_flex_shaped_entry_with_checklist(
    tmp_path: Path,
) -> None:
    save_activity_template(
        tmp_path, name="Deep work", duration_minutes=90, checklist="focus-kit"
    )

    library = load_activity_template_library(tmp_path / "data")

    assert library["deep-work"].start is None
    assert library["deep-work"].checklist == "focus-kit"


def test_save_activity_template_daily_round_trips(tmp_path: Path) -> None:
    save_activity_template(tmp_path, name="Yoga Nidra", duration_minutes=20, daily=True)

    library = load_activity_template_library(tmp_path / "data")

    assert library["yoga-nidra"].daily is True


def test_activity_template_without_daily_field_loads_as_not_daily(tmp_path: Path) -> None:
    save_activity_template(tmp_path, name="Deep work", duration_minutes=90)

    library = load_activity_template_library(tmp_path / "data")

    assert library["deep-work"].daily is False


def test_save_activity_template_rejects_daily_with_a_start(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_activity_template(
            tmp_path, name="Therapy", duration_minutes=50, start="16:00", daily=True
        )

    assert load_activity_template_library(tmp_path / "data") == {}


def test_unmarking_a_daily_activity_saves_it_as_not_daily(tmp_path: Path) -> None:
    activity_id = save_activity_template(
        tmp_path, name="Yoga Nidra", duration_minutes=20, daily=True
    )

    save_activity_template(
        tmp_path, id=activity_id, name="Yoga Nidra", duration_minutes=20, daily=False
    )

    library = load_activity_template_library(tmp_path / "data")
    assert library["yoga-nidra"].daily is False


def test_save_activity_template_rejects_a_create_name_collision_under_normalization(
    tmp_path: Path,
) -> None:
    save_activity_template(tmp_path, name="Deep Work!", duration_minutes=90)

    with pytest.raises(ValueError, match="Deep Work!"):
        save_activity_template(tmp_path, name="deep work", duration_minutes=45)


def test_save_activity_template_rename_keeps_the_id(tmp_path: Path) -> None:
    activity_id = save_activity_template(tmp_path, name="Deep work", duration_minutes=90)

    save_activity_template(tmp_path, id=activity_id, name="Focus block", duration_minutes=90)

    library = load_activity_template_library(tmp_path / "data")
    assert library["deep-work"].name == "Focus block"


def test_save_activity_template_rename_colliding_with_another_entry_is_rejected(
    tmp_path: Path,
) -> None:
    save_activity_template(tmp_path, name="Deep work", duration_minutes=90)
    therapy_id = save_activity_template(
        tmp_path, name="Therapy", duration_minutes=50, start="16:00"
    )

    with pytest.raises(ValueError):
        save_activity_template(
            tmp_path, id=therapy_id, name="Deep work", duration_minutes=50, start="16:00"
        )


def test_save_activity_template_update_of_a_missing_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_activity_template(tmp_path, id="does-not-exist", name="X", duration_minutes=10)


def test_delete_activity_template_removes_the_file(tmp_path: Path) -> None:
    save_activity_template(tmp_path, name="Deep work", duration_minutes=90)

    delete_activity_template(tmp_path, activity_id="deep-work")

    assert load_activity_template_library(tmp_path / "data") == {}


def test_save_activity_template_end_bound_anchor_round_trips(tmp_path: Path) -> None:
    save_activity_template(tmp_path, name="Therapy", duration_minutes=None, start="16:00", end="17:15")

    library = load_activity_template_library(tmp_path / "data")

    assert library["therapy"].end == "17:15"
    assert library["therapy"].duration.total_seconds() / 60 == 75


def test_save_activity_template_end_before_start_wraps_past_midnight(tmp_path: Path) -> None:
    save_activity_template(tmp_path, name="Sleep", start="23:00", end="01:00")

    library = load_activity_template_library(tmp_path / "data")

    assert library["sleep"].duration.total_seconds() / 60 == 120


def test_save_activity_template_rejects_both_duration_and_end(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_activity_template(
            tmp_path, name="Therapy", duration_minutes=50, start="16:00", end="17:00"
        )


def test_save_activity_template_rejects_neither_duration_nor_end(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_activity_template(tmp_path, name="Therapy", start="16:00")


def test_save_activity_template_rejects_end_equal_to_start(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_activity_template(tmp_path, name="Therapy", start="16:00", end="16:00")


def test_save_activity_template_rejects_end_on_a_flex_shaped_entry(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_activity_template(tmp_path, name="Deep work", end="17:00")


# --- Day Templates ------------------------------------------------------


def test_save_day_template_creates_with_a_name_only_and_derives_the_id(tmp_path: Path) -> None:
    template_id = save_day_template(
        tmp_path,
        name="Tuesday",
        anchors=[{"name": "Standup", "start": "07:00", "duration": 15}],
        flexes=[{"name": "Sauna", "duration": 30, "checklist": "sauna-kit"}],
    )

    path = named_day_template_path(tmp_path / "data", template_id)
    seed = load_day_template(path, {})

    assert template_id == "tuesday"
    assert seed is not None
    assert seed.anchors[0].name == "Standup"
    assert seed.flexes[0].checklist == "sauna-kit"


def test_save_day_template_with_activity_reference(tmp_path: Path) -> None:
    save_activity_template(tmp_path, name="Therapy", duration_minutes=50, start="16:00")
    save_day_template(tmp_path, name="Tuesday", anchors=[{"activity": "therapy"}])

    activity_library = load_activity_template_library(tmp_path / "data")
    path = named_day_template_path(tmp_path / "data", "tuesday")
    seed = load_day_template(path, activity_library)

    assert seed is not None
    assert seed.anchors[0].name == "Therapy"


def test_activity_reference_stored_under_the_wrong_section_still_resolves_by_current_shape(
    tmp_path: Path,
) -> None:
    save_activity_template(tmp_path, name="Therapy", duration_minutes=50, start="16:00")
    # Stored under [[flex]] even though Therapy is Anchor-shaped.
    save_day_template(tmp_path, name="Tuesday", flexes=[{"activity": "therapy"}])

    activity_library = load_activity_template_library(tmp_path / "data")
    path = named_day_template_path(tmp_path / "data", "tuesday")
    seed = load_day_template(path, activity_library)

    assert seed is not None
    assert seed.flexes == ()
    assert seed.anchors[0].name == "Therapy"
    assert seed.anchors[0].start.strftime("%H:%M") == "16:00"


def test_save_day_template_enforces_single_weekday_default(tmp_path: Path) -> None:
    save_day_template(tmp_path, name="A", weekday="tuesday")
    save_day_template(tmp_path, name="B", weekday="tuesday")

    winner = default_day_template_path(tmp_path / "data", date(2026, 8, 11))
    assert winner.stem == "b"

    a_data = (tmp_path / "data" / "templates" / "a.toml").read_text(encoding="utf-8")
    assert "weekday" not in a_data


def test_save_day_template_rejects_a_create_name_collision_under_normalization(
    tmp_path: Path,
) -> None:
    save_day_template(tmp_path, name="Travel Day!")

    with pytest.raises(ValueError, match="Travel Day!"):
        save_day_template(tmp_path, name="travel day")


def test_save_day_template_rename_keeps_the_id(tmp_path: Path) -> None:
    template_id = save_day_template(tmp_path, name="Tuesday")

    save_day_template(tmp_path, id=template_id, name="Tuesday (travel)")

    path = named_day_template_path(tmp_path / "data", "tuesday")
    from tomorrow.day_templates import load_day_template_name

    assert load_day_template_name(path) == "Tuesday (travel)"


def test_save_day_template_rename_colliding_with_another_entry_is_rejected(
    tmp_path: Path,
) -> None:
    save_day_template(tmp_path, name="Tuesday")
    wednesday_id = save_day_template(tmp_path, name="Wednesday")

    with pytest.raises(ValueError):
        save_day_template(tmp_path, id=wednesday_id, name="Tuesday")


def test_save_day_template_update_of_a_missing_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_day_template(tmp_path, id="does-not-exist", name="Tuesday")


def test_delete_day_template_removes_the_file(tmp_path: Path) -> None:
    save_day_template(tmp_path, name="Tuesday")

    delete_day_template(tmp_path, template_id="tuesday")

    assert not named_day_template_path(tmp_path / "data", "tuesday").exists()


def test_delete_referenced_activity_template_does_not_touch_day_template(
    tmp_path: Path,
) -> None:
    save_activity_template(tmp_path, name="Therapy", duration_minutes=50, start="16:00")
    save_day_template(tmp_path, name="Tuesday", anchors=[{"activity": "therapy"}])

    delete_activity_template(tmp_path, activity_id="therapy")

    path = named_day_template_path(tmp_path / "data", "tuesday")
    assert path.exists()
    seed = load_day_template(path, {})
    assert seed is not None
    assert seed.anchors == ()


def test_save_day_template_end_bound_anchor_round_trips(tmp_path: Path) -> None:
    save_day_template(
        tmp_path,
        name="Late night",
        anchors=[{"name": "Wind down", "start": "23:00", "end": "01:00"}],
    )

    path = named_day_template_path(tmp_path / "data", "late-night")
    seed = load_day_template(path, {})

    assert seed is not None
    assert seed.anchors[0].duration.total_seconds() / 60 == 120


def test_save_day_template_rejects_both_duration_and_end_on_an_anchor(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_day_template(
            tmp_path,
            name="Late night",
            anchors=[{"name": "Wind down", "start": "23:00", "duration": 30, "end": "01:00"}],
        )


def test_save_day_template_rejects_neither_duration_nor_end_on_an_anchor(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_day_template(
            tmp_path, name="Late night", anchors=[{"name": "Wind down", "start": "23:00"}]
        )


def test_save_day_template_rejects_end_equal_to_start_on_an_anchor(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_day_template(
            tmp_path,
            name="Late night",
            anchors=[{"name": "Wind down", "start": "23:00", "end": "23:00"}],
        )
