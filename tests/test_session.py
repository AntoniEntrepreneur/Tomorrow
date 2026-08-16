from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
import json

import pytest

from tomorrow.domain import (
    Anchor,
    Draft,
    Flex,
    PlanBlockedError,
    describe_blocker,
    finalize_plan,
    parse_clock,
)
from tomorrow.defaults import DayBounds
from tomorrow.session import (
    add_anchor,
    add_draft,
    add_flex,
    apply_template,
    decline_template,
    edit_anchor,
    edit_bounds,
    drop_draft,
    drop_flex,
    load_session,
    place_flex,
    promote_draft,
    reset_session,
    session_view,
    shrink_flex,
    submit_session,
)


def _write_defaults(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "defaults.toml").write_text(
        'wake = "06:30"\nsleep = "23:00"\n', encoding="utf-8"
    )
    (tmp_path / "plans").mkdir()


def _write_session(tmp_path: Path, document: dict) -> None:
    (tmp_path / "data" / "session.json").write_text(
        json.dumps(document), encoding="utf-8"
    )


def _write_tuesday_template(tmp_path: Path) -> None:
    templates = tmp_path / "data" / "templates"
    templates.mkdir()
    (templates / "tuesday.toml").write_text(
        """
[[anchor]]
name = "Standup"
start = "07:00"
duration = 15
checklist = "morning-out"

[[flex]]
name = "Sauna"
duration = 30
checklist = "sauna-kit"
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_missing_session_file_opens_as_blank_session(tmp_path: Path) -> None:
    _write_defaults(tmp_path)

    document = load_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))

    assert document == {
        "plan_date": "2026-08-11",
        "bounds": {"wake": "06:30", "sleep": "23:00"},
        "template_offer": "pending",
        "drafts": [],
        "anchors": [],
        "flexes": [],
        "undo": {"past": [], "future": []},
    }
    assert not (tmp_path / "data" / "session.json").exists()


def test_unfinished_session_resumes_with_its_own_bounds(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    saved = {
        "plan_date": "2026-08-11",
        "bounds": {"wake": "07:15", "sleep": "22:00"},
        "template_offer": "declined",
        "drafts": [{"id": "d1", "name": "Call dentist"}],
        "anchors": [],
        "flexes": [],
        "undo": {"past": [{"plan_date": "2026-08-11"}], "future": []},
    }
    _write_session(tmp_path, saved)

    document = load_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))

    assert document == saved
    assert document["bounds"] != {"wake": "06:30", "sleep": "23:00"}


def test_rolled_plan_date_replaces_session_with_blank_and_empty_undo(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    _write_session(
        tmp_path,
        {
            "plan_date": "2026-08-11",
            "bounds": {"wake": "07:15", "sleep": "22:00"},
            "template_offer": "accepted",
            "drafts": [{"id": "d1", "name": "Call dentist"}],
            "anchors": [
                {
                    "id": "a1",
                    "name": "Gym",
                    "start": "18:00",
                    "duration_minutes": 90,
                    "checklist": "gym-bag",
                }
            ],
            "flexes": [
                {
                    "id": "f1",
                    "name": "Walk",
                    "duration_minutes": 30,
                    "start": None,
                    "checklist": None,
                }
            ],
            "undo": {"past": [{"plan_date": "2026-08-11"}], "future": []},
        },
    )

    document = load_session(tmp_path, now=datetime(2026, 8, 16, 22, 0))
    flushed = json.loads((tmp_path / "data" / "session.json").read_text(encoding="utf-8"))

    blank = {
        "plan_date": "2026-08-17",
        "bounds": {"wake": "06:30", "sleep": "23:00"},
        "template_offer": "pending",
        "drafts": [],
        "anchors": [],
        "flexes": [],
        "undo": {"past": [], "future": []},
    }
    assert document == blank
    assert flushed == blank


def test_blank_session_plan_date_follows_wake_based_rule(tmp_path: Path) -> None:
    _write_defaults(tmp_path)

    pre_wake = load_session(tmp_path, now=datetime(2026, 8, 12, 0, 30))
    after_wake = load_session(tmp_path, now=datetime(2026, 8, 12, 8, 0))

    assert pre_wake["plan_date"] == "2026-08-12"
    assert after_wake["plan_date"] == "2026-08-13"



def test_session_view_omits_undo_stacks_and_reports_flags(tmp_path: Path) -> None:
    _write_defaults(tmp_path)

    view = session_view(tmp_path, now=datetime(2026, 8, 10, 22, 0))

    assert "undo" not in view
    assert view["can_undo"] is False
    assert view["can_redo"] is False
    assert view["blockers"] == []
    assert view["plan_date"] == "2026-08-11"
    assert view["plan_date_label"] == "Tuesday, 11 August 2026"
    assert view["bounds"] == {"wake": "06:30", "sleep": "23:00"}
    assert view["template_offer"] == "pending"
    assert view["show_template_offer"] is False
    assert view["drafts"] == []
    assert view["anchors"] == []
    assert view["flexes"] == []
    assert view["gaps"] == [
        {"start": "06:30", "end": "23:00", "duration_minutes": 990}
    ]
    assert view["weather_name"] is None
    assert view["weather_one_liner"] is None


def test_submit_of_blank_session_writes_plan_html(tmp_path: Path) -> None:
    _write_defaults(tmp_path)

    path = submit_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))

    assert path == tmp_path / "plans" / "2026-08-11.html"
    content = path.read_text(encoding="utf-8")
    assert "Tuesday, 11 August 2026" in content
    assert "Wake 06:30" in content
    assert "Sleep 23:00" in content


def test_submit_refuses_when_a_draft_remains(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    (tmp_path / "data" / "session.json").write_text(
        json.dumps(
            {
                "plan_date": "2026-08-11",
                "bounds": {"wake": "06:30", "sleep": "23:00"},
                "template_offer": "pending",
                "drafts": [{"id": "d1", "name": "Call dentist"}],
                "anchors": [],
                "flexes": [],
                "undo": {"past": [], "future": []},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PlanBlockedError):
        submit_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))

    assert list((tmp_path / "plans").iterdir()) == []


def test_session_view_shows_weather_name_and_one_liner(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    (tmp_path / "data" / "weather.toml").write_text(
        'name = "Warsaw"\nlatitude = 52.23\nlongitude = 21.01\n',
        encoding="utf-8",
    )
    payload = {
        "daily": {
            "time": ["2026-08-11"],
            "temperature_2m_min": [18.0],
            "temperature_2m_max": [24.0],
            "weathercode": [2],
        }
    }

    def fake_opener(_request):
        return BytesIO(json.dumps(payload).encode("utf-8"))

    view = session_view(
        tmp_path, now=datetime(2026, 8, 10, 22, 0), opener=fake_opener
    )
    document = load_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))

    assert view["weather_name"] == "Warsaw"
    assert view["weather_one_liner"] == "18° / 24° · partly cloudy"
    assert "52.23" not in str(view)
    assert "21.01" not in str(view)
    assert "weather" not in document
    assert "weather_name" not in document
    assert "weather_one_liner" not in document


def test_session_view_keeps_weather_name_when_fetch_fails(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    (tmp_path / "data" / "weather.toml").write_text(
        'name = "Warsaw"\nlatitude = 52.23\nlongitude = 21.01\n',
        encoding="utf-8",
    )

    def failing_opener(_request):
        raise URLError("offline")

    view = session_view(
        tmp_path, now=datetime(2026, 8, 10, 22, 0), opener=failing_opener
    )

    assert view["weather_name"] == "Warsaw"
    assert view["weather_one_liner"] is None


def test_session_view_omits_coordinates_when_weather_has_no_name(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    (tmp_path / "data" / "weather.toml").write_text(
        "latitude = 52.23\nlongitude = 21.01\n",
        encoding="utf-8",
    )
    payload = {
        "daily": {
            "time": ["2026-08-11"],
            "temperature_2m_min": [16.0],
            "temperature_2m_max": [22.0],
            "weathercode": [0],
        }
    }

    def fake_opener(_request):
        return BytesIO(json.dumps(payload).encode("utf-8"))

    view = session_view(
        tmp_path, now=datetime(2026, 8, 10, 22, 0), opener=fake_opener
    )

    assert view["weather_name"] is None
    assert view["weather_one_liner"] == "16° / 22° · clear"
    assert "52.23" not in str(view)
    assert "21.01" not in str(view)


def test_submit_writes_weather_one_liner_not_location_name(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    (tmp_path / "data" / "weather.toml").write_text(
        'name = "Warsaw"\nlatitude = 52.23\nlongitude = 21.01\n',
        encoding="utf-8",
    )
    payload = {
        "daily": {
            "time": ["2026-08-11"],
            "temperature_2m_min": [18.0],
            "temperature_2m_max": [24.0],
            "weathercode": [2],
        }
    }

    def fake_opener(_request):
        return BytesIO(json.dumps(payload).encode("utf-8"))

    path = submit_session(
        tmp_path, now=datetime(2026, 8, 10, 22, 0), opener=fake_opener
    )
    content = path.read_text(encoding="utf-8")

    assert '<div class="plan-weather">18° / 24° · partly cloudy</div>' in content
    assert "Warsaw" not in content
    assert "52.23" not in content


def test_submit_writes_plan_when_weather_fetch_times_out(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    (tmp_path / "data" / "weather.toml").write_text(
        'name = "Warsaw"\nlatitude = 52.23\nlongitude = 21.01\n',
        encoding="utf-8",
    )

    def timed_out_opener(_request):
        raise TimeoutError("slow")

    path = submit_session(
        tmp_path, now=datetime(2026, 8, 10, 22, 0), opener=timed_out_opener
    )
    content = path.read_text(encoding="utf-8")

    assert path.exists()
    assert "Tuesday, 11 August 2026" in content
    assert '<div class="plan-weather">' not in content
    assert "Warsaw" not in content


def test_reset_blanks_session_for_the_same_plan_date(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    _write_session(
        tmp_path,
        {
            "plan_date": "2026-08-11",
            "bounds": {"wake": "07:15", "sleep": "22:00"},
            "template_offer": "declined",
            "drafts": [{"id": "d1", "name": "Call dentist"}],
            "anchors": [
                {
                    "id": "a1",
                    "name": "Gym",
                    "start": "18:00",
                    "duration_minutes": 90,
                    "checklist": "gym-bag",
                }
            ],
            "flexes": [
                {
                    "id": "f1",
                    "name": "Walk",
                    "duration_minutes": 30,
                    "start": None,
                    "checklist": None,
                }
            ],
            "undo": {"past": [{"plan_date": "2026-08-11"}], "future": []},
        },
    )

    view = reset_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))
    flushed = json.loads((tmp_path / "data" / "session.json").read_text(encoding="utf-8"))

    assert flushed == {
        "plan_date": "2026-08-11",
        "bounds": {"wake": "06:30", "sleep": "23:00"},
        "template_offer": "pending",
        "drafts": [],
        "anchors": [],
        "flexes": [],
        "undo": {"past": [], "future": []},
    }
    assert view["plan_date"] == "2026-08-11"
    assert view["bounds"] == {"wake": "06:30", "sleep": "23:00"}
    assert view["template_offer"] == "pending"
    assert view["drafts"] == []
    assert view["anchors"] == []
    assert view["flexes"] == []
    assert view["can_undo"] is False
    assert view["can_redo"] is False
    assert "undo" not in view


def test_reset_does_not_delete_plan_html(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    plan_path = tmp_path / "plans" / "2026-08-11.html"
    plan_path.write_text("<html>existing plan</html>", encoding="utf-8")
    _write_session(
        tmp_path,
        {
            "plan_date": "2026-08-11",
            "bounds": {"wake": "07:15", "sleep": "22:00"},
            "template_offer": "pending",
            "drafts": [{"id": "d1", "name": "Call dentist"}],
            "anchors": [],
            "flexes": [],
            "undo": {"past": [], "future": []},
        },
    )

    reset_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))

    assert plan_path.read_text(encoding="utf-8") == "<html>existing plan</html>"


def test_submit_does_not_end_session_or_blank_it(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    saved = {
        "plan_date": "2026-08-11",
        "bounds": {"wake": "07:15", "sleep": "22:00"},
        "template_offer": "declined",
        "drafts": [],
        "anchors": [],
        "flexes": [],
        "undo": {"past": [{"plan_date": "2026-08-11"}], "future": []},
    }
    _write_session(tmp_path, saved)

    plan_path = submit_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))
    resumed = load_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))

    assert plan_path.exists()
    assert resumed == saved
    assert resumed["bounds"]["wake"] == "07:15"
    assert resumed["template_offer"] == "declined"
    assert resumed["undo"]["past"] == [{"plan_date": "2026-08-11"}]


def test_later_submit_overwrites_the_same_plan_date_file(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    _write_session(
        tmp_path,
        {
            "plan_date": "2026-08-11",
            "bounds": {"wake": "06:30", "sleep": "23:00"},
            "template_offer": "pending",
            "drafts": [],
            "anchors": [],
            "flexes": [],
            "undo": {"past": [], "future": []},
        },
    )
    first = submit_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))
    _write_session(
        tmp_path,
        {
            "plan_date": "2026-08-11",
            "bounds": {"wake": "07:15", "sleep": "22:00"},
            "template_offer": "pending",
            "drafts": [],
            "anchors": [],
            "flexes": [],
            "undo": {"past": [], "future": []},
        },
    )

    second = submit_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))
    content = second.read_text(encoding="utf-8")

    assert second == first
    assert list((tmp_path / "plans").glob("*.html")) == [second]
    assert "Wake 07:15" in content
    assert "Sleep 22:00" in content
    assert "Wake 06:30" not in content


def test_plans_before_today_are_deleted_and_today_or_later_are_kept(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    plans = tmp_path / "plans"
    (plans / "2026-08-10.html").write_text("yesterday", encoding="utf-8")
    (plans / "2026-08-16.html").write_text("today", encoding="utf-8")
    (plans / "2026-08-17.html").write_text("tomorrow", encoding="utf-8")
    (plans / ".gitkeep").write_text("", encoding="utf-8")

    load_session(tmp_path, now=datetime(2026, 8, 16, 22, 0))

    remaining = {path.name: path.read_text(encoding="utf-8") for path in plans.iterdir()}
    assert remaining == {
        ".gitkeep": "",
        "2026-08-16.html": "today",
        "2026-08-17.html": "tomorrow",
    }


def test_adding_an_anchor_mints_an_id_and_flushes_the_session_file(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)

    view = add_anchor(
        tmp_path,
        name="Gym",
        start="18:00",
        duration_minutes=90,
        now=datetime(2026, 8, 10, 22, 0),
    )
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert len(document["anchors"]) == 1
    anchor = document["anchors"][0]
    assert anchor["name"] == "Gym"
    assert anchor["start"] == "18:00"
    assert anchor["duration_minutes"] == 90
    assert isinstance(anchor["id"], str) and anchor["id"]
    assert view["anchors"] == document["anchors"]
    assert view["blockers"] == []
    assert "undo" not in view
    assert view["can_undo"] is True


def test_overlapping_anchors_show_the_same_blockers_as_finalize_plan(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    add_anchor(
        tmp_path, name="Gym", start="18:00", duration_minutes=90, now=now
    )
    view = add_anchor(
        tmp_path, name="Dinner", start="18:30", duration_minutes=60, now=now
    )

    gym = Anchor(
        name="Gym", start=parse_clock("18:00"), duration=timedelta(minutes=90)
    )
    dinner = Anchor(
        name="Dinner", start=parse_clock("18:30"), duration=timedelta(minutes=60)
    )
    expected = finalize_plan(
        bounds=DayBounds(wake="06:30", sleep="23:00"),
        drafts=[],
        anchors=[gym, dinner],
    )

    assert view["blockers"] == [
        describe_blocker(blocker) for blocker in expected.blockers
    ]
    assert view["blockers"]


def test_editing_an_anchor_updates_name_clock_and_duration_and_flushes(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_anchor(
        tmp_path, name="Gym", start="18:00", duration_minutes=90, now=now
    )
    item_id = added["anchors"][0]["id"]

    view = edit_anchor(
        tmp_path,
        item_id=item_id,
        name="Weights",
        start="19:00",
        duration_minutes=60,
        now=now,
    )
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["anchors"] == [
        {
            "id": item_id,
            "name": "Weights",
            "start": "19:00",
            "duration_minutes": 60,
            "checklist": None,
        }
    ]
    assert view["anchors"] == document["anchors"]
    assert view["blockers"] == []


def test_an_anchor_is_removed_by_editing_it_away(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_anchor(
        tmp_path, name="Gym", start="18:00", duration_minutes=90, now=now
    )
    item_id = added["anchors"][0]["id"]

    view = edit_anchor(tmp_path, item_id=item_id, remove=True, now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["anchors"] == []
    assert view["anchors"] == []
    assert view["blockers"] == []


def test_changing_session_bounds_flushes_and_does_not_rewrite_defaults(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)

    view = edit_bounds(tmp_path, wake="07:00", sleep="22:00", now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )
    defaults_text = (tmp_path / "data" / "defaults.toml").read_text(encoding="utf-8")

    assert document["bounds"] == {"wake": "07:00", "sleep": "22:00"}
    assert view["bounds"] == document["bounds"]
    assert 'wake = "06:30"' in defaults_text
    assert 'sleep = "23:00"' in defaults_text


def test_gaps_update_when_bounds_change(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_anchor(
        tmp_path, name="Gym", start="18:00", duration_minutes=90, now=now
    )

    assert added["gaps"] == [
        {"start": "06:30", "end": "18:00", "duration_minutes": 690},
        {"start": "19:30", "end": "23:00", "duration_minutes": 210},
    ]

    tightened = edit_bounds(tmp_path, sleep="20:00", now=now)

    assert tightened["gaps"] == [
        {"start": "06:30", "end": "18:00", "duration_minutes": 690},
        {"start": "19:30", "end": "20:00", "duration_minutes": 30},
    ]


def test_anchor_outside_new_bounds_is_a_live_blocker(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    add_anchor(tmp_path, name="Gym", start="18:00", duration_minutes=90, now=now)

    view = edit_bounds(tmp_path, sleep="18:30", now=now)
    gym = Anchor(
        name="Gym", start=parse_clock("18:00"), duration=timedelta(minutes=90)
    )
    expected = finalize_plan(
        bounds=DayBounds(wake="06:30", sleep="18:30"),
        drafts=[],
        anchors=[gym],
    )

    assert view["blockers"] == [
        describe_blocker(blocker) for blocker in expected.blockers
    ]
    assert view["blockers"]


def test_submit_of_clean_session_with_anchors_writes_plan_html(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    add_anchor(tmp_path, name="Gym", start="18:00", duration_minutes=90, now=now)

    path = submit_session(tmp_path, now=now)
    content = path.read_text(encoding="utf-8")

    assert path == tmp_path / "plans" / "2026-08-11.html"
    assert "Gym" in content
    assert "18:00" in content
    assert "19:30" in content
    assert 'class="block anchor"' in content


def test_submit_refuses_while_anchor_blockers_remain(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    add_anchor(tmp_path, name="Gym", start="18:00", duration_minutes=90, now=now)
    add_anchor(tmp_path, name="Dinner", start="18:30", duration_minutes=60, now=now)

    with pytest.raises(PlanBlockedError):
        submit_session(tmp_path, now=now)

    assert list((tmp_path / "plans").iterdir()) == []


def test_adding_flex_mints_an_id_stays_unplaced_and_flushes(tmp_path: Path) -> None:
    _write_defaults(tmp_path)

    view = add_flex(
        tmp_path,
        name="Walk",
        duration_minutes=30,
        now=datetime(2026, 8, 10, 22, 0),
    )
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert len(document["flexes"]) == 1
    flex = document["flexes"][0]
    assert flex["name"] == "Walk"
    assert flex["duration_minutes"] == 30
    assert flex["start"] is None
    assert flex["checklist"] is None
    assert isinstance(flex["id"], str) and flex["id"]
    assert view["flexes"] == document["flexes"]
    assert "undo" not in view
    assert view["can_undo"] is True


def test_unplaced_flex_shows_the_same_blocker_as_finalize_plan(tmp_path: Path) -> None:
    _write_defaults(tmp_path)

    view = add_flex(
        tmp_path,
        name="Walk",
        duration_minutes=30,
        now=datetime(2026, 8, 10, 22, 0),
    )
    expected = finalize_plan(
        bounds=DayBounds(wake="06:30", sleep="23:00"),
        drafts=[],
        anchors=[],
        flexes=[Flex(name="Walk", duration=timedelta(minutes=30))],
    )

    assert view["blockers"] == [
        describe_blocker(blocker) for blocker in expected.blockers
    ]
    assert view["blockers"]


def test_placing_flex_into_a_gap_flushes_and_clears_the_unplaced_blocker(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_flex(tmp_path, name="Walk", duration_minutes=30, now=now)
    item_id = added["flexes"][0]["id"]

    view = place_flex(tmp_path, item_id=item_id, start="07:15", now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["flexes"] == [
        {
            "id": item_id,
            "name": "Walk",
            "duration_minutes": 30,
            "start": "07:15",
            "checklist": None,
        }
    ]
    assert view["flexes"] == document["flexes"]
    assert view["blockers"] == []


def test_placed_flex_that_does_not_fit_is_a_live_blocker(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_flex(tmp_path, name="Deep work", duration_minutes=90, now=now)
    item_id = added["flexes"][0]["id"]

    view = place_flex(tmp_path, item_id=item_id, start="22:00", now=now)
    expected = finalize_plan(
        bounds=DayBounds(wake="06:30", sleep="23:00"),
        drafts=[],
        anchors=[],
        flexes=[
            Flex(
                name="Deep work",
                duration=timedelta(minutes=90),
                start=parse_clock("22:00"),
            )
        ],
    )

    assert view["blockers"] == [
        describe_blocker(blocker) for blocker in expected.blockers
    ]
    assert view["blockers"]


def test_shrinking_flex_flushes_and_can_clear_a_does_not_fit_blocker(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_flex(tmp_path, name="Deep work", duration_minutes=90, now=now)
    item_id = added["flexes"][0]["id"]
    place_flex(tmp_path, item_id=item_id, start="22:00", now=now)

    view = shrink_flex(tmp_path, item_id=item_id, duration_minutes=45, now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["flexes"][0]["duration_minutes"] == 45
    assert document["flexes"][0]["start"] == "22:00"
    assert view["flexes"] == document["flexes"]
    assert view["blockers"] == []


def test_shrinking_unplaced_flex_leaves_it_unplaced(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_flex(tmp_path, name="Walk", duration_minutes=45, now=now)
    item_id = added["flexes"][0]["id"]

    view = shrink_flex(tmp_path, item_id=item_id, duration_minutes=20, now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["flexes"][0]["duration_minutes"] == 20
    assert document["flexes"][0]["start"] is None
    assert view["flexes"] == document["flexes"]
    assert view["blockers"]


def test_dropping_flex_removes_it_from_the_session_and_flushes(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_flex(tmp_path, name="Walk", duration_minutes=30, now=now)
    item_id = added["flexes"][0]["id"]

    view = drop_flex(tmp_path, item_id=item_id, now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["flexes"] == []
    assert view["flexes"] == []
    assert view["blockers"] == []


def test_drop_cannot_vanish_an_anchor(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_anchor(
        tmp_path, name="Gym", start="18:00", duration_minutes=90, now=now
    )
    add_flex(tmp_path, name="Walk", duration_minutes=30, now=now)
    anchor_id = added["anchors"][0]["id"]

    with pytest.raises(KeyError):
        drop_flex(tmp_path, item_id=anchor_id, now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["anchors"][0]["id"] == anchor_id
    assert document["anchors"][0]["name"] == "Gym"
    assert len(document["flexes"]) == 1


def test_submit_refuses_while_flex_blockers_remain(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    add_flex(tmp_path, name="Walk", duration_minutes=30, now=now)

    with pytest.raises(PlanBlockedError):
        submit_session(tmp_path, now=now)

    assert list((tmp_path / "plans").iterdir()) == []


def test_submit_of_honestly_placed_flex_writes_plan_html(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_flex(tmp_path, name="Walk", duration_minutes=30, now=now)
    place_flex(tmp_path, item_id=added["flexes"][0]["id"], start="07:15", now=now)

    path = submit_session(tmp_path, now=now)
    content = path.read_text(encoding="utf-8")

    assert path == tmp_path / "plans" / "2026-08-11.html"
    assert "Walk" in content
    assert "07:15" in content
    assert 'class="block flex"' in content


def test_dropped_flex_is_absent_from_the_submitted_plan(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_flex(tmp_path, name="Walk", duration_minutes=30, now=now)
    drop_flex(tmp_path, item_id=added["flexes"][0]["id"], now=now)

    path = submit_session(tmp_path, now=now)
    content = path.read_text(encoding="utf-8")

    assert "Walk" not in content
    assert "not today" not in content.lower()
    assert "dropped" not in content.lower()


def test_adding_a_draft_mints_an_id_and_flushes_the_session_file(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)

    view = add_draft(
        tmp_path,
        name="Call dentist",
        now=datetime(2026, 8, 10, 22, 0),
    )
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert len(document["drafts"]) == 1
    draft = document["drafts"][0]
    assert draft["name"] == "Call dentist"
    assert list(draft) == ["id", "name"]
    assert isinstance(draft["id"], str) and draft["id"]
    assert view["drafts"] == document["drafts"]
    assert "undo" not in view
    assert view["can_undo"] is True


def test_leftover_draft_shows_the_same_blocker_as_finalize_plan(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)

    view = add_draft(
        tmp_path,
        name="Call dentist",
        now=datetime(2026, 8, 10, 22, 0),
    )
    expected = finalize_plan(
        bounds=DayBounds(wake="06:30", sleep="23:00"),
        drafts=[Draft(name="Call dentist")],
        anchors=[],
    )

    assert view["blockers"] == [
        describe_blocker(blocker) for blocker in expected.blockers
    ]
    assert view["blockers"]


def test_adding_anchor_or_flex_still_works_while_a_draft_is_present(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    add_draft(tmp_path, name="Call dentist", now=now)

    anchored = add_anchor(
        tmp_path, name="Gym", start="18:00", duration_minutes=90, now=now
    )
    flexed = add_flex(tmp_path, name="Walk", duration_minutes=30, now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert [draft["name"] for draft in document["drafts"]] == ["Call dentist"]
    assert document["anchors"][0]["name"] == "Gym"
    assert document["flexes"][0]["name"] == "Walk"
    assert anchored["anchors"] == document["anchors"]
    assert flexed["flexes"] == document["flexes"]
    assert flexed["blockers"]


def test_dropping_a_draft_removes_it_from_the_session_and_flushes(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_draft(tmp_path, name="Call dentist", now=now)
    item_id = added["drafts"][0]["id"]

    view = drop_draft(tmp_path, item_id=item_id, now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["drafts"] == []
    assert view["drafts"] == []
    assert view["blockers"] == []


def test_dropped_draft_is_absent_from_the_submitted_plan(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_draft(tmp_path, name="Call dentist", now=now)
    drop_draft(tmp_path, item_id=added["drafts"][0]["id"], now=now)

    path = submit_session(tmp_path, now=now)
    content = path.read_text(encoding="utf-8")

    assert "Call dentist" not in content
    assert "not today" not in content.lower()
    assert "dropped" not in content.lower()


def test_drop_cannot_vanish_an_anchor_via_drop_draft(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_anchor(
        tmp_path, name="Gym", start="18:00", duration_minutes=90, now=now
    )
    add_draft(tmp_path, name="Call dentist", now=now)
    anchor_id = added["anchors"][0]["id"]

    with pytest.raises(KeyError):
        drop_draft(tmp_path, item_id=anchor_id, now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["anchors"][0]["id"] == anchor_id
    assert len(document["drafts"]) == 1


def test_promoting_a_draft_to_anchor_mints_a_new_id_and_does_not_leak(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_draft(tmp_path, name="Call dentist", now=now)
    draft_id = added["drafts"][0]["id"]

    view = promote_draft(
        tmp_path,
        item_id=draft_id,
        kind="anchor",
        start="09:00",
        duration_minutes=30,
        now=now,
    )
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["drafts"] == []
    assert view["drafts"] == []
    assert len(document["anchors"]) == 1
    anchor = document["anchors"][0]
    assert anchor["name"] == "Call dentist"
    assert anchor["start"] == "09:00"
    assert anchor["duration_minutes"] == 30
    assert anchor["checklist"] is None
    assert isinstance(anchor["id"], str) and anchor["id"]
    assert anchor["id"] != draft_id
    assert draft_id not in json.dumps({"anchors": document["anchors"]})
    assert view["anchors"] == document["anchors"]
    assert view["blockers"] == []


def test_promoting_a_draft_to_flex_mints_a_new_id_and_stays_unplaced(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_draft(tmp_path, name="Walk", now=now)
    draft_id = added["drafts"][0]["id"]

    view = promote_draft(
        tmp_path,
        item_id=draft_id,
        kind="flex",
        duration_minutes=30,
        now=now,
    )
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["drafts"] == []
    assert view["drafts"] == []
    assert len(document["flexes"]) == 1
    flex = document["flexes"][0]
    assert flex["name"] == "Walk"
    assert flex["duration_minutes"] == 30
    assert flex["start"] is None
    assert flex["checklist"] is None
    assert isinstance(flex["id"], str) and flex["id"]
    assert flex["id"] != draft_id
    assert draft_id not in json.dumps({"flexes": document["flexes"]})
    assert view["flexes"] == document["flexes"]
    assert view["blockers"]


def test_submit_refuses_while_any_draft_remains_after_add(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    add_draft(tmp_path, name="Call dentist", now=now)

    with pytest.raises(PlanBlockedError):
        submit_session(tmp_path, now=now)

    assert list((tmp_path / "plans").iterdir()) == []


def test_blank_session_offers_weekday_template_when_file_exists(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    _write_tuesday_template(tmp_path)

    view = session_view(tmp_path, now=datetime(2026, 8, 10, 22, 0))

    assert view["template_offer"] == "pending"
    assert view["show_template_offer"] is True
    assert view["anchors"] == []
    assert view["flexes"] == []
    assert view["drafts"] == []


def test_blank_session_does_not_offer_template_when_weekday_file_is_missing(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)

    view = session_view(tmp_path, now=datetime(2026, 8, 10, 22, 0))

    assert view["template_offer"] == "pending"
    assert view["show_template_offer"] is False


def test_accepting_template_copies_anchors_and_unplaced_flex_and_flushes(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    _write_tuesday_template(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)

    view = apply_template(tmp_path, now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["template_offer"] == "accepted"
    assert view["template_offer"] == "accepted"
    assert view["show_template_offer"] is False
    assert document["anchors"] == view["anchors"]
    assert document["flexes"] == view["flexes"]
    assert len(document["anchors"]) == 1
    assert document["anchors"][0]["name"] == "Standup"
    assert document["anchors"][0]["start"] == "07:00"
    assert document["anchors"][0]["duration_minutes"] == 15
    assert document["anchors"][0]["checklist"] == "morning-out"
    assert document["anchors"][0]["id"]
    assert document["flexes"] == [
        {
            "id": document["flexes"][0]["id"],
            "name": "Sauna",
            "duration_minutes": 30,
            "start": None,
            "checklist": "sauna-kit",
        }
    ]
    assert document["flexes"][0]["id"]
    assert document["anchors"][0]["id"] != document["flexes"][0]["id"]
    assert len(document["undo"]["past"]) == 1
    assert document["undo"]["future"] == []
    assert view["can_undo"] is True
    assert "undo" not in view


def test_declining_template_persists_through_an_empty_session(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    _write_tuesday_template(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)

    declined = decline_template(tmp_path, now=now)
    added = add_flex(tmp_path, name="Walk", duration_minutes=30, now=now)
    emptied = drop_flex(tmp_path, item_id=added["flexes"][0]["id"], now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert declined["template_offer"] == "declined"
    assert declined["show_template_offer"] is False
    assert declined["can_undo"] is True
    assert "undo" not in declined
    assert emptied["template_offer"] == "declined"
    assert emptied["show_template_offer"] is False
    assert emptied["flexes"] == []
    assert emptied["anchors"] == []
    assert emptied["drafts"] == []
    assert document["template_offer"] == "declined"
    assert len(document["undo"]["past"]) >= 1


def test_template_offer_hides_while_the_session_has_items(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    _write_tuesday_template(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)

    view = add_flex(tmp_path, name="Walk", duration_minutes=30, now=now)

    assert view["template_offer"] == "pending"
    assert view["show_template_offer"] is False
    assert view["flexes"]


def test_template_offer_hides_when_a_draft_remains(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    _write_tuesday_template(tmp_path)
    _write_session(
        tmp_path,
        {
            "plan_date": "2026-08-11",
            "bounds": {"wake": "06:30", "sleep": "23:00"},
            "template_offer": "pending",
            "drafts": [{"id": "d1", "name": "Call dentist"}],
            "anchors": [],
            "flexes": [],
            "undo": {"past": [], "future": []},
        },
    )

    view = session_view(tmp_path, now=datetime(2026, 8, 10, 22, 0))

    assert view["template_offer"] == "pending"
    assert view["show_template_offer"] is False


def test_offer_uses_this_weekdays_template_file_only(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    templates = tmp_path / "data" / "templates"
    templates.mkdir()
    (templates / "wednesday.toml").write_text(
        '[[flex]]\nname = "Wrong day"\nduration = 20\n',
        encoding="utf-8",
    )

    view = session_view(tmp_path, now=datetime(2026, 8, 10, 22, 0))

    assert view["plan_date"] == "2026-08-11"
    assert view["show_template_offer"] is False


def test_accepting_template_does_not_seed_a_session_that_already_has_items(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    _write_tuesday_template(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    added = add_flex(tmp_path, name="Walk", duration_minutes=30, now=now)

    view = apply_template(tmp_path, now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["template_offer"] == "pending"
    assert [flex["name"] for flex in document["flexes"]] == ["Walk"]
    assert document["anchors"] == []
    assert view["template_offer"] == "pending"
    assert view["flexes"][0]["id"] == added["flexes"][0]["id"]


def test_reset_returns_template_offer_to_pending_and_offers_again(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    _write_tuesday_template(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    apply_template(tmp_path, now=now)

    view = reset_session(tmp_path, now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["template_offer"] == "pending"
    assert document["anchors"] == []
    assert document["flexes"] == []
    assert view["template_offer"] == "pending"
    assert view["show_template_offer"] is True


def test_accepted_then_empty_session_does_not_look_like_pending(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    _write_tuesday_template(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    seeded = apply_template(tmp_path, now=now)
    for flex in list(seeded["flexes"]):
        drop_flex(tmp_path, item_id=flex["id"], now=now)
    for anchor in list(seeded["anchors"]):
        edit_anchor(tmp_path, item_id=anchor["id"], remove=True, now=now)

    view = session_view(tmp_path, now=now)
    document = json.loads(
        (tmp_path / "data" / "session.json").read_text(encoding="utf-8")
    )

    assert document["template_offer"] == "accepted"
    assert document["anchors"] == []
    assert document["flexes"] == []
    assert document["drafts"] == []
    assert view["template_offer"] == "accepted"
    assert view["show_template_offer"] is False
