from datetime import datetime
from http.client import HTTPConnection
from pathlib import Path
import json
import socket
import threading
import time

import pytest

from tomorrow.cli import main
from tomorrow.session import SESSION_HOST, SESSION_PORT, bind_session_server, run_session


def _write_defaults(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "defaults.toml").write_text(
        'wake = "06:30"\nsleep = "23:00"\n', encoding="utf-8"
    )
    (tmp_path / "plans").mkdir()


def _write_tuesday_template(tmp_path: Path) -> None:
    templates = tmp_path / "data" / "templates"
    templates.mkdir()
    (templates / "tuesday.toml").write_text(
        """
[[anchor]]
name = "Standup"
start = "07:00"
duration = 15

[[flex]]
name = "Sauna"
duration = 30
""".strip()
        + "\n",
        encoding="utf-8",
    )



def _write_checklist_library(tmp_path: Path) -> None:
    checklists_dir = tmp_path / "data" / "checklists"
    checklists_dir.mkdir()
    (checklists_dir / "gym-bag.toml").write_text(
        'name = "Gym bag"\nitems = ["Towel"]\n', encoding="utf-8"
    )
    (checklists_dir / "sauna-kit.toml").write_text(
        'name = "Sauna kit"\nitems = ["Towel"]\n', encoding="utf-8"
    )


def test_main_finds_clone_data_when_cwd_is_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    seen: dict[str, Path] = {}

    def fake_run_session(repo_root: Path, *, now=None) -> None:
        seen["repo_root"] = repo_root

    monkeypatch.setattr("tomorrow.cli.run_session", fake_run_session)
    main()

    assert (seen["repo_root"] / "data" / "defaults.toml").is_file()


def test_run_session_prints_plan_date_url_and_instruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_defaults(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(
        "tomorrow.session.webbrowser.open", lambda url: opened.append(url)
    )

    class FakeServer:
        submitted_path = None

        def serve_forever(self) -> None:
            return

        def server_close(self) -> None:
            return

    monkeypatch.setattr(
        "tomorrow.session.bind_session_server", lambda *_args, **_kwargs: FakeServer()
    )

    run_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))
    output = capsys.readouterr().out

    assert "Tuesday, 11 August 2026" in output
    assert "http://127.0.0.1:8765" in output
    assert "Submit in the browser, or Ctrl+C to leave." in output
    assert opened == ["http://127.0.0.1:8765"]


def test_busy_port_prints_and_exits_without_hunting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_defaults(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(
        "tomorrow.session.webbrowser.open", lambda url: opened.append(url)
    )
    occupant = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupant.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    occupant.bind((SESSION_HOST, SESSION_PORT))
    occupant.listen(1)
    try:
        run_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))
    finally:
        occupant.close()

    output = capsys.readouterr().out
    assert "8765" in output
    assert "already in use" in output.lower() or "in use" in output
    assert opened == []
    assert list((tmp_path / "plans").iterdir()) == []


def _start_server(tmp_path: Path, *, now: datetime | None = None):
    server = bind_session_server(tmp_path, now=now or datetime(2026, 8, 10, 22, 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.connect((SESSION_HOST, SESSION_PORT))
            probe.close()
            return server, thread
        except OSError:
            probe.close()
            time.sleep(0.02)
    server.shutdown()
    server.server_close()
    raise RuntimeError("Session server did not start")


def _stop_server(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def _http(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    timeout: float = 2,
) -> tuple[int, bytes]:
    conn = HTTPConnection(SESSION_HOST, SESSION_PORT, timeout=timeout)
    try:
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload)
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def test_construction_page_is_blank_canvas_with_domain_jargon(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        status, body = _http("GET", "/")
    finally:
        _stop_server(server, thread)

    html = body.decode("utf-8")
    assert status == 200
    assert "Anchor" in html
    assert "Flex" in html
    assert "Draft" in html
    assert "Gap" in html
    assert "Drop" in html
    assert "Submit" in html
    assert "Unplaced Flex" in html
    assert "Promote" in html
    assert "Template" in html
    assert "Undo" in html
    assert "Redo" in html
    assert 'id="undo"' in html
    assert 'id="redo"' in html
    assert "/api/undo" in html
    assert "/api/redo" in html
    assert "confirm(" not in html
    assert "toast" not in html
    assert 'type="date"' not in html
    assert "named-routine" not in html
    assert "latitude" not in html
    assert "longitude" not in html


def test_session_page_wires_undo_shortcuts_and_keeps_stamps_enabled(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        status, body = _http("GET", "/")
    finally:
        _stop_server(server, thread)

    html = body.decode("utf-8")
    assert status == 200
    assert 'key === "z"' in html or 'key === "Z"' in html or 'toLowerCase()' in html
    assert "shiftKey" in html
    assert 'key === "y"' in html or 'key === "Y"' in html
    assert "INPUT" in html
    assert "TEXTAREA" in html
    assert "sheetKind" in html or 'kind === "stamp"' in html or 'kind === "edit"' in html
    assert "openSheet(" in html
    assert "stamp" in html
    assert "disabled" in html


def test_session_json_omits_undo_stacks(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        status, body = _http("GET", "/api/session")
    finally:
        _stop_server(server, thread)

    payload = json.loads(body)
    assert status == 200
    assert "undo" not in payload
    assert payload["can_undo"] is False
    assert payload["can_redo"] is False
    assert payload["plan_date"] == "2026-08-11"
    assert payload["template_offer"] == "pending"
    assert payload["show_template_offer"] is False


def test_submit_writes_plan_opens_file_and_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_defaults(tmp_path)
    opened: list[str] = []
    monkeypatch.setattr(
        "tomorrow.session.webbrowser.open", lambda url: opened.append(url)
    )

    def bind_then_submit(repo_root: Path, **kwargs):
        server = bind_session_server(repo_root, **kwargs)

        def post_submit() -> None:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    status, _body = _http("POST", "/api/submit")
                    assert status == 200
                    return
                except OSError:
                    time.sleep(0.02)
            raise RuntimeError("Submit never reached the server")

        threading.Thread(target=post_submit, daemon=True).start()
        return server

    monkeypatch.setattr("tomorrow.session.bind_session_server", bind_then_submit)
    run_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))

    plan_path = tmp_path / "plans" / "2026-08-11.html"
    output = capsys.readouterr().out
    assert plan_path.exists()
    assert str(plan_path) in output
    assert opened[0] == "http://127.0.0.1:8765"
    assert opened[1] == plan_path.as_uri()
    assert opened[1].startswith("file:")
    assert "http://" not in opened[1]


def test_submit_refuses_blocked_session_over_http(tmp_path: Path) -> None:
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
    server, thread = _start_server(tmp_path)
    try:
        status, body = _http("POST", "/api/submit")
    finally:
        _stop_server(server, thread)

    payload = json.loads(body)
    assert status == 409
    assert payload["blockers"]
    assert list((tmp_path / "plans").iterdir()) == []


def test_reset_over_http_blanks_session_and_keeps_plan_html(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    plan_path = tmp_path / "plans" / "2026-08-11.html"
    plan_path.write_text("<html>existing plan</html>", encoding="utf-8")
    (tmp_path / "data" / "session.json").write_text(
        json.dumps(
            {
                "plan_date": "2026-08-11",
                "bounds": {"wake": "07:15", "sleep": "22:00"},
                "template_offer": "declined",
                "drafts": [{"id": "d1", "name": "Call dentist"}],
                "anchors": [],
                "flexes": [],
                "undo": {"past": [{"plan_date": "2026-08-11"}], "future": []},
            }
        ),
        encoding="utf-8",
    )
    server, thread = _start_server(tmp_path)
    try:
        status, body = _http("POST", "/api/reset")
    finally:
        _stop_server(server, thread)

    payload = json.loads(body)
    flushed = json.loads((tmp_path / "data" / "session.json").read_text(encoding="utf-8"))
    assert status == 200
    assert payload["plan_date"] == "2026-08-11"
    assert payload["bounds"] == {"wake": "06:30", "sleep": "23:00"}
    assert payload["template_offer"] == "pending"
    assert payload["drafts"] == []
    assert payload["anchors"] == []
    assert payload["flexes"] == []
    assert "undo" not in payload
    assert payload["can_undo"] is True
    assert payload["can_redo"] is False
    assert flushed["drafts"] == []
    assert flushed["bounds"] == {"wake": "06:30", "sleep": "23:00"}
    assert plan_path.read_text(encoding="utf-8") == "<html>existing plan</html>"


def test_ctrl_c_stops_without_writing_a_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_defaults(tmp_path)
    monkeypatch.setattr("tomorrow.session.webbrowser.open", lambda _url: None)

    class FakeServer:
        submitted_path = None

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            return

    monkeypatch.setattr(
        "tomorrow.session.bind_session_server", lambda *_args, **_kwargs: FakeServer()
    )
    run_session(tmp_path, now=datetime(2026, 8, 10, 22, 0))

    assert list((tmp_path / "plans").iterdir()) == []


def test_add_anchor_over_http_returns_session_without_undo_stacks(
    tmp_path: Path,
) -> None:
    _write_defaults(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        status, body = _http(
            "POST",
            "/api/add",
            payload={
                "kind": "anchor",
                "name": "Gym",
                "start": "18:00",
                "duration_minutes": 90,
            },
        )
    finally:
        _stop_server(server, thread)

    payload = json.loads(body)
    assert status == 200
    assert "undo" not in payload
    assert payload["can_undo"] is True
    assert len(payload["anchors"]) == 1
    assert payload["anchors"][0]["name"] == "Gym"


def test_edit_anchor_and_bounds_over_http(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        _, added_body = _http(
            "POST",
            "/api/add",
            payload={
                "kind": "anchor",
                "name": "Gym",
                "start": "18:00",
                "duration_minutes": 90,
            },
        )
        item_id = json.loads(added_body)["anchors"][0]["id"]
        status, edited_body = _http(
            "POST",
            "/api/edit",
            payload={
                "kind": "anchor",
                "id": item_id,
                "name": "Weights",
                "start": "19:00",
                "duration_minutes": 60,
            },
        )
        bounds_status, bounds_body = _http(
            "POST",
            "/api/edit",
            payload={"kind": "bounds", "wake": "07:00", "sleep": "22:00"},
        )
        remove_status, removed_body = _http(
            "POST",
            "/api/edit",
            payload={"kind": "anchor", "id": item_id, "remove": True},
        )
    finally:
        _stop_server(server, thread)

    edited = json.loads(edited_body)
    bounds = json.loads(bounds_body)
    removed = json.loads(removed_body)
    assert status == 200
    assert edited["anchors"][0]["name"] == "Weights"
    assert edited["anchors"][0]["start"] == "19:00"
    assert "undo" not in edited
    assert bounds_status == 200
    assert bounds["bounds"] == {"wake": "07:00", "sleep": "22:00"}
    assert remove_status == 200
    assert removed["anchors"] == []


def test_add_place_change_duration_and_drop_flex_over_http(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        add_status, added_body = _http(
            "POST",
            "/api/add",
            payload={"kind": "flex", "name": "Walk", "duration_minutes": 90},
        )
        item_id = json.loads(added_body)["flexes"][0]["id"]
        place_status, placed_body = _http(
            "POST",
            "/api/place",
            payload={"id": item_id, "start": "22:00"},
        )
        change_duration_status, changed_duration_body = _http(
            "POST",
            "/api/change-duration",
            payload={"id": item_id, "duration_minutes": 45},
        )
        drop_status, dropped_body = _http(
            "POST",
            "/api/drop",
            payload={"kind": "flex", "id": item_id},
        )
    finally:
        _stop_server(server, thread)

    added = json.loads(added_body)
    placed = json.loads(placed_body)
    changed_duration = json.loads(changed_duration_body)
    dropped = json.loads(dropped_body)
    flushed = json.loads((tmp_path / "data" / "session.json").read_text(encoding="utf-8"))
    assert add_status == 200
    assert added["flexes"][0]["name"] == "Walk"
    assert added["flexes"][0]["id"]
    assert "undo" not in added
    assert place_status == 200
    assert placed["flexes"][0]["start"] == "22:00"
    assert "undo" not in placed
    assert change_duration_status == 200
    assert changed_duration["flexes"][0]["duration_minutes"] == 45
    assert "undo" not in changed_duration
    assert drop_status == 200
    assert dropped["flexes"] == []
    assert "undo" not in dropped
    assert flushed["flexes"] == []


def test_drop_over_http_cannot_vanish_an_anchor(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        _, added_body = _http(
            "POST",
            "/api/add",
            payload={
                "kind": "anchor",
                "name": "Gym",
                "start": "18:00",
                "duration_minutes": 90,
            },
        )
        item_id = json.loads(added_body)["anchors"][0]["id"]
        status, _body = _http(
            "POST",
            "/api/drop",
            payload={"kind": "anchor", "id": item_id},
        )
        _, session_body = _http("GET", "/api/session")
    finally:
        _stop_server(server, thread)

    payload = json.loads(session_body)
    assert status == 404
    assert payload["anchors"][0]["id"] == item_id
    assert payload["anchors"][0]["name"] == "Gym"


def test_add_promote_and_drop_draft_over_http(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        add_status, added_body = _http(
            "POST",
            "/api/add",
            payload={"kind": "draft", "name": "Call dentist"},
        )
        draft_id = json.loads(added_body)["drafts"][0]["id"]
        promote_status, promoted_body = _http(
            "POST",
            "/api/promote",
            payload={
                "id": draft_id,
                "kind": "anchor",
                "start": "09:00",
                "duration_minutes": 30,
            },
        )
        drop_add_status, drop_added_body = _http(
            "POST",
            "/api/add",
            payload={"kind": "draft", "name": "Buy milk"},
        )
        leftover_id = json.loads(drop_added_body)["drafts"][0]["id"]
        drop_status, dropped_body = _http(
            "POST",
            "/api/drop",
            payload={"kind": "draft", "id": leftover_id},
        )
    finally:
        _stop_server(server, thread)

    added = json.loads(added_body)
    promoted = json.loads(promoted_body)
    dropped = json.loads(dropped_body)
    flushed = json.loads((tmp_path / "data" / "session.json").read_text(encoding="utf-8"))
    assert add_status == 200
    assert added["drafts"][0]["name"] == "Call dentist"
    assert added["drafts"][0]["id"]
    assert "undo" not in added
    assert added["blockers"]
    assert promote_status == 200
    assert promoted["drafts"] == []
    assert promoted["anchors"][0]["name"] == "Call dentist"
    assert promoted["anchors"][0]["id"] != draft_id
    assert "undo" not in promoted
    assert drop_add_status == 200
    assert drop_status == 200
    assert dropped["drafts"] == []
    assert "undo" not in dropped
    assert flushed["drafts"] == []
    assert flushed["anchors"][0]["name"] == "Call dentist"


def test_promote_draft_to_flex_over_http(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        _, added_body = _http(
            "POST",
            "/api/add",
            payload={"kind": "draft", "name": "Walk"},
        )
        draft_id = json.loads(added_body)["drafts"][0]["id"]
        status, body = _http(
            "POST",
            "/api/promote",
            payload={"id": draft_id, "kind": "flex", "duration_minutes": 30},
        )
    finally:
        _stop_server(server, thread)

    payload = json.loads(body)
    assert status == 200
    assert payload["drafts"] == []
    assert payload["flexes"][0]["name"] == "Walk"
    assert payload["flexes"][0]["start"] is None
    assert payload["flexes"][0]["id"] != draft_id
    assert "undo" not in payload

def test_apply_template_over_http(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    _write_tuesday_template(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        _, offered_body = _http("GET", "/api/session")
        apply_status, applied_body = _http(
            "POST", "/api/template", payload={"action": "apply"}
        )
    finally:
        _stop_server(server, thread)

    offered = json.loads(offered_body)
    applied = json.loads(applied_body)
    flushed = json.loads((tmp_path / "data" / "session.json").read_text(encoding="utf-8"))
    assert offered["show_template_offer"] is True
    assert apply_status == 200
    assert applied["template_offer"] == "accepted"
    assert applied["show_template_offer"] is False
    assert "undo" not in applied
    assert applied["can_undo"] is True
    assert applied["anchors"][0]["name"] == "Standup"
    assert applied["flexes"][0]["name"] == "Sauna"
    assert applied["flexes"][0]["start"] is None
    assert flushed["template_offer"] == "accepted"


def test_decline_template_over_http(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    _write_tuesday_template(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        decline_status, declined_body = _http(
            "POST", "/api/template", payload={"action": "decline"}
        )
    finally:
        _stop_server(server, thread)

    declined = json.loads(declined_body)
    flushed = json.loads((tmp_path / "data" / "session.json").read_text(encoding="utf-8"))
    assert decline_status == 200
    assert declined["template_offer"] == "declined"
    assert declined["show_template_offer"] is False
    assert "undo" not in declined
    assert declined["can_undo"] is True
    assert flushed["template_offer"] == "declined"


def test_checklist_library_and_item_attach_over_http(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    _write_checklist_library(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        get_status, get_body = _http("GET", "/api/session")
        add_status, added_body = _http(
            "POST",
            "/api/add",
            payload={
                "kind": "anchor",
                "name": "Gym",
                "start": "18:00",
                "duration_minutes": 90,
            },
        )
        item_id = json.loads(added_body)["anchors"][0]["id"]
        clear_status, cleared_body = _http(
            "POST",
            "/api/edit",
            payload={"kind": "anchor", "id": item_id, "checklist": None},
        )
        pick_status, picked_body = _http(
            "POST",
            "/api/edit",
            payload={"kind": "anchor", "id": item_id, "checklist": "sauna-kit"},
        )
        flex_status, flex_body = _http(
            "POST",
            "/api/add",
            payload={
                "kind": "flex",
                "name": "Walk",
                "duration_minutes": 30,
                "checklist": "gym-bag",
            },
        )
        flex_id = json.loads(flex_body)["flexes"][0]["id"]
        flex_edit_status, flex_edited_body = _http(
            "POST",
            "/api/edit",
            payload={"kind": "flex", "id": flex_id, "checklist": None},
        )
    finally:
        _stop_server(server, thread)

    session = json.loads(get_body)
    added = json.loads(added_body)
    cleared = json.loads(cleared_body)
    picked = json.loads(picked_body)
    flex = json.loads(flex_body)
    flex_edited = json.loads(flex_edited_body)
    flushed = json.loads((tmp_path / "data" / "session.json").read_text(encoding="utf-8"))
    assert get_status == 200
    assert session["checklists"] == [
        {"id": "gym-bag", "name": "Gym bag"},
        {"id": "sauna-kit", "name": "Sauna kit"},
    ]
    assert all("items" not in entry for entry in session["checklists"])
    assert add_status == 200
    assert added["anchors"][0]["checklist"] == "gym-bag"
    assert "undo" not in added
    assert clear_status == 200
    assert cleared["anchors"][0]["checklist"] is None
    assert pick_status == 200
    assert picked["anchors"][0]["checklist"] == "sauna-kit"
    assert flex_status == 200
    assert flex["flexes"][0]["checklist"] == "gym-bag"
    assert flex_edit_status == 200
    assert flex_edited["flexes"][0]["checklist"] is None
    assert flushed["anchors"][0]["checklist"] == "sauna-kit"
    assert flushed["flexes"][0]["checklist"] is None


def test_undo_and_redo_over_http_omit_stacks_and_restore_ids(tmp_path: Path) -> None:
    _write_defaults(tmp_path)
    server, thread = _start_server(tmp_path)
    try:
        _, added_body = _http(
            "POST",
            "/api/add",
            payload={"kind": "draft", "name": "Call dentist"},
        )
        added = json.loads(added_body)
        undo_status, undo_body = _http("POST", "/api/undo")
        redo_status, redo_body = _http("POST", "/api/redo")
    finally:
        _stop_server(server, thread)

    undone = json.loads(undo_body)
    redone = json.loads(redo_body)
    assert undo_status == 200
    assert redo_status == 200
    assert "undo" not in undone
    assert "undo" not in redone
    assert undone["drafts"] == []
    assert undone["can_undo"] is False
    assert undone["can_redo"] is True
    assert redone["drafts"] == added["drafts"]
    assert redone["drafts"][0]["id"] == added["drafts"][0]["id"]
    assert redone["can_undo"] is True
    assert redone["can_redo"] is False
