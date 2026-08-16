from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
import json

import pytest

from tomorrow.domain import PlanBlockedError
from tomorrow.session import load_session, reset_session, session_view, submit_session


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
    assert view["drafts"] == []
    assert view["anchors"] == []
    assert view["flexes"] == []
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
