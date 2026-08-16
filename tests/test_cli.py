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


def _http(method: str, path: str, *, timeout: float = 2) -> tuple[int, bytes]:
    conn = HTTPConnection(SESSION_HOST, SESSION_PORT, timeout=timeout)
    try:
        conn.request(method, path)
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
    assert 'type="date"' not in html
    assert "latitude" not in html
    assert "longitude" not in html


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
