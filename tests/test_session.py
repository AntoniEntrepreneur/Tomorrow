from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
import json

import pytest

from tomorrow.domain import PlanBlockedError
from tomorrow.session import load_session, session_view, submit_session


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
