from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
import json

import pytest

from tomorrow.domain import (
    Anchor,
    PlanBlockedError,
    describe_blocker,
    finalize_plan,
    parse_clock,
)
from tomorrow.defaults import DayBounds
from tomorrow.session import (
    add_anchor,
    edit_anchor,
    edit_bounds,
    load_session,
    session_view,
    submit_session,
)


def _write_defaults(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "defaults.toml").write_text(
        'wake = "06:30"\nsleep = "23:00"\n', encoding="utf-8"
    )
    (tmp_path / "plans").mkdir()


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
