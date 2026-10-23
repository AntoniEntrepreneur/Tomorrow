from datetime import datetime
from http.client import HTTPConnection
from pathlib import Path
import json
import threading
import time

import pytest

from tomorrow.library import save_activity_template
from tomorrow.session import (
    add_anchor,
    add_flex,
    add_todo,
    place_flex,
    session_view,
)
from tomorrow.session_http import bind_session_server


def _write_defaults(repo_root: Path) -> None:
    data_dir = repo_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "defaults.toml").write_text(
        'wake = "06:30"\nsleep = "23:00"\n', encoding="utf-8"
    )


def _desktop_dir(tmp_path: Path) -> Path:
    desktop = tmp_path / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    return desktop


def _start_server(tmp_path: Path, *, now: datetime | None = None):
    server = bind_session_server(
        tmp_path,
        output_dir=_desktop_dir(tmp_path),
        now=now or datetime(2026, 8, 10, 22, 0),
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + 2
    host, port = server.server_address[:2]
    while time.monotonic() < deadline:
        try:
            conn = HTTPConnection(host, port, timeout=1)
            conn.request("GET", "/api/session")
            res = conn.getresponse()
            res.read()
            conn.close()
            return server, thread
        except OSError:
            time.sleep(0.02)
    server.shutdown()
    server.server_close()
    raise RuntimeError("Session server did not start")


def _stop_server(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def _http(
    server,
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    timeout: float = 2,
) -> tuple[int, dict | bytes]:
    host, port = server.server_address[:2]
    conn = HTTPConnection(host, port, timeout=timeout)
    try:
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload)
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        try:
            parsed = json.loads(raw.decode("utf-8"))
            return response.status, parsed
        except Exception:
            return response.status, raw
    finally:
        conn.close()


def test_edit_anchor_to_flex_preserves_start_and_checklist_over_http(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    view = add_anchor(
        tmp_path,
        output_dir=_desktop_dir(tmp_path),
        name="Focus block",
        start="10:00",
        duration_minutes=60,
        checklist_items=["Music", "Tea"],
        now=now,
    )
    anchor_id = view["anchors"][0]["id"]

    server, thread = _start_server(tmp_path, now=now)
    try:
        status, body = _http(
            server,
            "POST",
            "/api/edit",
            payload={"kind": "flex", "id": anchor_id},
        )
        assert status == 200
        assert body["anchors"] == []
        assert len(body["flexes"]) == 1
        flex = body["flexes"][0]
        assert flex["id"] == anchor_id
        assert flex["name"] == "Focus block"
        assert flex["start"] == "10:00"
        assert flex["duration_minutes"] == 60
        assert flex["checklist_items"] == ["Music", "Tea"]
    finally:
        _stop_server(server, thread)


def test_edit_flex_to_anchor_placed_and_unplaced_over_http(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    view = add_flex(
        tmp_path,
        output_dir=_desktop_dir(tmp_path),
        name="Placed flex",
        duration_minutes=45,
        now=now,
    )
    placed_id = view["flexes"][0]["id"]
    place_flex(tmp_path, output_dir=_desktop_dir(tmp_path), item_id=placed_id, start="14:00", now=now)

    view = add_flex(
        tmp_path,
        output_dir=_desktop_dir(tmp_path),
        name="Unplaced flex",
        duration_minutes=30,
        now=now,
    )
    unplaced_id = next(f["id"] for f in view["flexes"] if f["name"] == "Unplaced flex")

    server, thread = _start_server(tmp_path, now=now)
    try:
        # Placed flex converted to anchor preserves start time
        status, body = _http(
            server,
            "POST",
            "/api/edit",
            payload={"kind": "anchor", "id": placed_id},
        )
        assert status == 200
        placed_anchor = next(a for a in body["anchors"] if a["id"] == placed_id)
        assert placed_anchor["start"] == "14:00"
        assert placed_anchor["duration_minutes"] == 45

        # Unplaced flex converted without start fails with 400
        status, body = _http(
            server,
            "POST",
            "/api/edit",
            payload={"kind": "anchor", "id": unplaced_id},
        )
        assert status == 400
        assert "start" in body["error"].lower()

        # Unplaced flex converted with start succeeds
        status, body = _http(
            server,
            "POST",
            "/api/edit",
            payload={"kind": "anchor", "id": unplaced_id, "start": "16:00"},
        )
        assert status == 200
        unplaced_anchor = next(a for a in body["anchors"] if a["id"] == unplaced_id)
        assert unplaced_anchor["start"] == "16:00"
        assert unplaced_anchor["duration_minutes"] == 30
    finally:
        _stop_server(server, thread)


def test_edit_activity_to_todo_drops_timings_and_checklist_over_http(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    view = add_anchor(
        tmp_path,
        output_dir=_desktop_dir(tmp_path),
        name="Meeting",
        start="11:00",
        duration_minutes=30,
        checklist_items=["Slides"],
        now=now,
    )
    anchor_id = view["anchors"][0]["id"]

    server, thread = _start_server(tmp_path, now=now)
    try:
        status, body = _http(
            server,
            "POST",
            "/api/edit",
            payload={"kind": "todo", "id": anchor_id, "note": "Prepare slides beforehand"},
        )
        assert status == 200
        assert body["anchors"] == []
        assert len(body["todos"]) == 1
        todo = body["todos"][0]
        assert todo["id"] == anchor_id
        assert todo["name"] == "Meeting"
        assert todo["note"] == "Prepare slides beforehand"
        assert "start" not in todo
        assert "duration_minutes" not in todo
        assert "checklist" not in todo
    finally:
        _stop_server(server, thread)


def test_edit_todo_conversions_over_http(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    view = add_todo(
        tmp_path,
        output_dir=_desktop_dir(tmp_path),
        name="Tidy workspace",
        note="Screens and cable management",
        now=now,
    )
    todo_id = view["todos"][0]["id"]

    server, thread = _start_server(tmp_path, now=now)
    try:
        # To-do -> Flex: default duration 30, start None, discard note
        status, body = _http(
            server,
            "POST",
            "/api/edit",
            payload={"kind": "flex", "id": todo_id},
        )
        assert status == 200
        assert body["todos"] == []
        assert len(body["flexes"]) == 1
        flex = body["flexes"][0]
        assert flex["id"] == todo_id
        assert flex["duration_minutes"] == 30
        assert flex["start"] is None
        assert "note" not in flex

        # Flex -> To-do again
        status, body = _http(
            server,
            "POST",
            "/api/edit",
            payload={"kind": "todo", "id": todo_id},
        )
        assert status == 200
        assert len(body["todos"]) == 1
        assert body["flexes"] == []

        # To-do -> Anchor: default start 09:00, default duration 30
        status, body = _http(
            server,
            "POST",
            "/api/edit",
            payload={"kind": "anchor", "id": todo_id},
        )
        assert status == 200
        assert body["todos"] == []
        assert len(body["anchors"]) == 1
        anchor = body["anchors"][0]
        assert anchor["id"] == todo_id
        assert anchor["start"] == "09:00"
        assert anchor["duration_minutes"] == 30
    finally:
        _stop_server(server, thread)


def test_converting_daily_activity_clears_daily_source_over_http(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    save_activity_template(
        tmp_path, name="Yoga", duration_minutes=30, daily=True
    )
    view = session_view(tmp_path, output_dir=_desktop_dir(tmp_path), now=now)
    daily_flex = next(f for f in view["flexes"] if f["name"] == "Yoga")
    assert daily_flex["source"] == "daily"
    item_id = daily_flex["id"]

    server, thread = _start_server(tmp_path, now=now)
    try:
        # Convert daily Flex to Anchor -> clears daily source
        status, body = _http(
            server,
            "POST",
            "/api/edit",
            payload={"kind": "anchor", "id": item_id, "start": "07:30"},
        )
        assert status == 200
        anchor = next(a for a in body["anchors"] if a["id"] == item_id)
        assert anchor.get("source") != "daily"

        # Convert to To-do -> clears daily source
        status, body = _http(
            server,
            "POST",
            "/api/edit",
            payload={"kind": "todo", "id": item_id},
        )
        assert status == 200
        todo = next(t for t in body["todos"] if t["id"] == item_id)
        assert todo.get("source") != "daily"
    finally:
        _stop_server(server, thread)


def test_undo_and_redo_restore_state_across_conversions_over_http(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    view = add_anchor(
        tmp_path,
        output_dir=_desktop_dir(tmp_path),
        name="Review",
        start="15:00",
        duration_minutes=45,
        now=now,
    )
    item_id = view["anchors"][0]["id"]

    server, thread = _start_server(tmp_path, now=now)
    try:
        # Convert to Flex
        status, body = _http(server, "POST", "/api/edit", payload={"kind": "flex", "id": item_id})
        assert status == 200
        assert len(body["flexes"]) == 1
        assert len(body["anchors"]) == 0

        # Convert to To-do
        status, body = _http(server, "POST", "/api/edit", payload={"kind": "todo", "id": item_id})
        assert status == 200
        assert len(body["todos"]) == 1
        assert len(body["flexes"]) == 0

        # Undo -> back to Flex
        status, body = _http(server, "POST", "/api/undo")
        assert status == 200
        assert len(body["flexes"]) == 1
        assert len(body["todos"]) == 0
        assert body["flexes"][0]["start"] == "15:00"

        # Undo -> back to Anchor
        status, body = _http(server, "POST", "/api/undo")
        assert status == 200
        assert len(body["anchors"]) == 1
        assert len(body["flexes"]) == 0
        assert body["anchors"][0]["start"] == "15:00"

        # Redo -> back to Flex
        status, body = _http(server, "POST", "/api/redo")
        assert status == 200
        assert len(body["flexes"]) == 1
        assert len(body["anchors"]) == 0

        # Redo -> back to To-do
        status, body = _http(server, "POST", "/api/redo")
        assert status == 200
        assert len(body["todos"]) == 1
        assert len(body["flexes"]) == 0
    finally:
        _stop_server(server, thread)


def test_obsolete_conversion_routes_are_removed(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    server, thread = _start_server(tmp_path, now=now)
    try:
        for route in ("/api/todo-to-flex", "/api/todo-to-anchor", "/api/flex-to-todo", "/api/convert"):
            status, _ = _http(server, "POST", route, payload={"id": "abc"})
            assert status == 404, f"Route {route} should return 404 Not Found"
    finally:
        _stop_server(server, thread)


def test_unplace_route_and_undo_redo_over_http(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    now = datetime(2026, 8, 10, 22, 0)
    view = add_flex(
        tmp_path,
        output_dir=_desktop_dir(tmp_path),
        name="Reading",
        duration_minutes=45,
        now=now,
    )
    item_id = view["flexes"][0]["id"]
    place_flex(
        tmp_path,
        output_dir=_desktop_dir(tmp_path),
        item_id=item_id,
        start="14:00",
        now=now,
    )

    server, thread = _start_server(tmp_path, now=now)
    try:
        # Invalid / unknown ID returns 400 Bad Request
        status, body = _http(
            server, "POST", "/api/unplace", payload={"id": "nonexistent-id"}
        )
        assert status == 400
        assert "error" in body

        # Valid ID unplaces flex, returns 200 OK and updated session view
        status, body = _http(server, "POST", "/api/unplace", payload={"id": item_id})
        assert status == 200
        unplaced = next(f for f in body["flexes"] if f["id"] == item_id)
        assert unplaced["start"] is None
        assert unplaced["name"] == "Reading"

        # Undo over HTTP restores placed start time
        status, body = _http(server, "POST", "/api/undo")
        assert status == 200
        restored = next(f for f in body["flexes"] if f["id"] == item_id)
        assert restored["start"] == "14:00"

        # Redo over HTTP clears start time again
        status, body = _http(server, "POST", "/api/redo")
        assert status == 200
        redone = next(f for f in body["flexes"] if f["id"] == item_id)
        assert redone["start"] is None
    finally:
        _stop_server(server, thread)


def test_location_endpoint_persists_to_untracked_local_weather(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        status, body = _http(
            server,
            "POST",
            "/api/location",
            payload={"latitude": 52.23, "longitude": 21.01},
        )
        assert status == 200
        assert isinstance(body, dict)
        assert "weather" in body

        local_file = tmp_path / "data" / "weather.local.toml"
        default_file = tmp_path / "data" / "weather.toml"
        assert local_file.exists()
        assert not default_file.exists()
        content = local_file.read_text(encoding="utf-8")
        assert "52.23" in content
        assert "21.01" in content
    finally:
        _stop_server(server, thread)


def test_static_clock_module_served_and_construction_shared_removed(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        status, body = _http(server, "GET", "/static/clock.js")
        assert status == 200
        assert b"toWakeMin" in body

        status_old, _ = _http(server, "GET", "/static/construction-shared.js")
        assert status_old == 404
    finally:
        _stop_server(server, thread)


