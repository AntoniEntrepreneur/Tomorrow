from __future__ import annotations

from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import errno
import json
import threading
import webbrowser

from tomorrow.defaults import DayBounds, load_defaults
from tomorrow.domain import (
    Anchor,
    Draft,
    FinalizeResult,
    Flex,
    PlanBlockedError,
    describe_blocker,
    finalize_plan,
    parse_clock,
)
from tomorrow.plan import default_plan_date, format_plan_date, write_finalized_plan
from tomorrow.weather import load_weather_name, try_fetch_weather

SESSION_HOST = "127.0.0.1"
SESSION_PORT = 8765
SESSION_URL = f"http://{SESSION_HOST}:{SESSION_PORT}"
_PAGE_PATH = Path(__file__).parent / "static" / "session.html"
_WEATHER_TIMEOUT_SECONDS = 5


def _default_opener(request: Request) -> object:
    return urlopen(request, timeout=_WEATHER_TIMEOUT_SECONDS)


def load_session(repo_root: Path, *, now: datetime | None = None) -> dict:
    path = repo_root / "data" / "session.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    defaults = load_defaults(repo_root / "data" / "defaults.toml")
    plan_date = default_plan_date(now, wake=defaults.wake)
    return {
        "plan_date": plan_date.isoformat(),
        "bounds": {"wake": defaults.wake, "sleep": defaults.sleep},
        "template_offer": "pending",
        "drafts": [],
        "anchors": [],
        "flexes": [],
        "undo": {"past": [], "future": []},
    }


def _unpack(document: dict) -> tuple[DayBounds, list[Draft], list[Anchor], list[Flex]]:
    bounds = DayBounds(
        wake=document["bounds"]["wake"],
        sleep=document["bounds"]["sleep"],
    )
    drafts = [Draft(name=item["name"]) for item in document["drafts"]]
    anchors = [
        Anchor(
            name=item["name"],
            start=parse_clock(item["start"]),
            duration=timedelta(minutes=item["duration_minutes"]),
            checklist=item.get("checklist"),
        )
        for item in document["anchors"]
    ]
    flexes = [
        Flex(
            name=item["name"],
            duration=timedelta(minutes=item["duration_minutes"]),
            start=parse_clock(item["start"]) if item.get("start") else None,
            checklist=item.get("checklist"),
        )
        for item in document["flexes"]
    ]
    return bounds, drafts, anchors, flexes


def _finalize_document(document: dict) -> FinalizeResult:
    bounds, drafts, anchors, flexes = _unpack(document)
    return finalize_plan(bounds=bounds, drafts=drafts, anchors=anchors, flexes=flexes)


def session_view(
    repo_root: Path,
    *,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)
    result = _finalize_document(document)
    undo = document.get("undo", {"past": [], "future": []})
    plan_date = date.fromisoformat(document["plan_date"])
    data_dir = repo_root / "data"
    return {
        "plan_date": document["plan_date"],
        "plan_date_label": format_plan_date(plan_date),
        "bounds": document["bounds"],
        "template_offer": document["template_offer"],
        "drafts": document["drafts"],
        "anchors": document["anchors"],
        "flexes": document["flexes"],
        "blockers": [describe_blocker(blocker) for blocker in result.blockers],
        "can_undo": bool(undo.get("past")),
        "can_redo": bool(undo.get("future")),
        "weather_name": load_weather_name(data_dir),
        "weather_one_liner": try_fetch_weather(data_dir, plan_date, opener=opener),
    }


def submit_session(
    repo_root: Path,
    *,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> Path:
    document = load_session(repo_root, now=now)
    result = _finalize_document(document)
    if not result.ok:
        raise PlanBlockedError(result.blockers)
    assert result.plan is not None
    plan_date = date.fromisoformat(document["plan_date"])
    weather = try_fetch_weather(repo_root / "data", plan_date, opener=opener)
    return write_finalized_plan(
        repo_root=repo_root,
        plan_date=plan_date,
        plan=result.plan,
        weather=weather,
    )


class SessionHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    repo_root: Path
    now: datetime | None
    opener: Callable[[Request], object]
    submitted_path: Path | None


class SessionHandler(BaseHTTPRequestHandler):
    server: SessionHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            body = _PAGE_PATH.read_bytes()
            self._send(200, "text/html; charset=utf-8", body)
            return
        if path == "/api/session":
            view = session_view(
                self.server.repo_root,
                now=self.server.now,
                opener=self.server.opener,
            )
            self._send_json(200, view)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/submit":
            self.send_error(404)
            return
        try:
            plan_path = submit_session(
                self.server.repo_root,
                now=self.server.now,
                opener=self.server.opener,
            )
        except PlanBlockedError:
            view = session_view(
                self.server.repo_root,
                now=self.server.now,
                opener=self.server.opener,
            )
            self._send_json(409, view)
            return
        self.server.submitted_path = plan_path
        self._send_json(200, {"ok": True, "path": str(plan_path)})
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def bind_session_server(
    repo_root: Path,
    *,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> SessionHTTPServer:
    server = SessionHTTPServer((SESSION_HOST, SESSION_PORT), SessionHandler)
    server.repo_root = repo_root
    server.now = now
    server.opener = opener
    server.submitted_path = None
    return server


def run_session(
    repo_root: Path,
    *,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> None:
    try:
        server = bind_session_server(repo_root, now=now, opener=opener)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        print(f"Port {SESSION_PORT} is already in use.")
        return
    document = load_session(repo_root, now=now)
    plan_date = date.fromisoformat(document["plan_date"])
    print(f"Plan date: {format_plan_date(plan_date)}")
    print(SESSION_URL)
    print("Submit in the browser, or Ctrl+C to leave.")
    webbrowser.open(SESSION_URL)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return
    finally:
        server.server_close()
    if server.submitted_path is not None:
        webbrowser.open(server.submitted_path.as_uri())
        print(server.submitted_path)
