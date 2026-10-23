from __future__ import annotations

from datetime import date, datetime
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
import json
import threading
import webbrowser

from tomorrow.library import (
    delete_activity_template,
    delete_checklist,
    delete_day_template,
    list_activity_templates,
    list_checklists,
    list_day_templates,
    reorder_day_templates,
    save_activity_template,
    save_checklist,
    save_day_template,
    suggest_activity,
)
from tomorrow.session import (
    add_anchor,
    add_draft,
    add_flex,
    add_todo,
    apply_named_day_template,
    apply_template,
    change_flex_duration,
    decline_template,
    drop_draft,
    drop_flex,
    drop_todo,
    edit_activity,
    edit_bounds,
    edit_draft,
    insert_activity_template,
    place_flex,
    unplace_flex,
    promote_checklist,
    promote_draft,
    redo_session,
    refresh_icloud_items,
    reset_session,
    save_template_mode,
    session_view,
    submit_session,
    template_mode_view,
    undo_session,
)
from tomorrow.domain import PlanBlockedError
from tomorrow.plan import ForeignPlanFileError, format_plan_date
from tomorrow.weather import get_ssl_context, reverse_geocode, save_weather_location

SESSION_HOST = "127.0.0.1"
SESSION_PORT = 8765
SESSION_URL = f"http://{SESSION_HOST}:{SESSION_PORT}"
LIBRARY_URL = f"{SESSION_URL}/library"
_WEATHER_TIMEOUT_SECONDS = 5


def default_opener(request: Request) -> object:
    ctx = get_ssl_context()
    if ctx is not None:
        return urlopen(request, timeout=_WEATHER_TIMEOUT_SECONDS, context=ctx)
    return urlopen(request, timeout=_WEATHER_TIMEOUT_SECONDS)


_default_opener = default_opener

_PAGE_PATH = Path(__file__).parent / "static" / "session.html"
_LIBRARY_PAGE_PATH = Path(__file__).parent / "static" / "library.html"


def _checklist_kwargs(payload: dict) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    if "checklist" in payload:
        kwargs["checklist"] = payload.get("checklist")
    if "checklist_items" in payload:
        kwargs["checklist_items"] = payload.get("checklist_items")
    return kwargs


_LIBRARY_VIEW_SECTIONS: dict[str, Callable[[Path], list[dict]]] = {
    "checklists": list_checklists,
    "activity_templates": list_activity_templates,
    "day_templates": list_day_templates,
}


class _LibraryEntityOps:
    """Save/delete callbacks for one `/api/library/<entity>` kind."""

    def __init__(
        self,
        save: Callable[[Path, dict], None],
        delete: Callable[[Path, dict], None],
        reorder: Callable[[Path, dict], None] | None = None,
    ) -> None:
        self.save = save
        self.delete = delete
        self.reorder = reorder


def _save_checklist_entity(repo_root: Path, payload: dict) -> None:
    save_checklist(
        repo_root,
        id=payload.get("id") or None,
        name=payload["name"],
        items=list(payload.get("items", [])),
    )


def _save_activity_template_entity(repo_root: Path, payload: dict) -> None:
    duration_value = payload.get("duration_minutes")
    save_activity_template(
        repo_root,
        id=payload.get("id") or None,
        name=payload["name"],
        duration_minutes=int(duration_value) if duration_value not in (None, "") else None,
        start=payload.get("start") or None,
        end=payload.get("end") or None,
        checklist=payload.get("checklist") or None,
        daily=bool(payload.get("daily", False)),
    )


def _save_day_template_entity(repo_root: Path, payload: dict) -> None:
    save_day_template(
        repo_root,
        id=payload.get("id") or None,
        name=payload["name"],
        anchors=payload.get("anchors"),
        flexes=payload.get("flexes"),
        weekday=payload.get("weekday") or None,
        wake=payload.get("wake") or None,
        sleep=payload.get("sleep") or None,
    )


_LIBRARY_ENTITY_OPS: dict[str, _LibraryEntityOps] = {
    "checklist": _LibraryEntityOps(
        save=_save_checklist_entity,
        delete=lambda repo_root, payload: delete_checklist(
            repo_root, checklist_id=payload["id"]
        ),
    ),
    "activity-template": _LibraryEntityOps(
        save=_save_activity_template_entity,
        delete=lambda repo_root, payload: delete_activity_template(
            repo_root, activity_id=payload["id"]
        ),
    ),
    "day-template": _LibraryEntityOps(
        save=_save_day_template_entity,
        delete=lambda repo_root, payload: delete_day_template(
            repo_root, template_id=payload["id"]
        ),
        reorder=lambda repo_root, payload: reorder_day_templates(
            repo_root, ids=list(payload.get("ids", []))
        ),
    ),
}


class SessionHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    repo_root: Path
    output_dir: Path
    now: datetime | None
    opener: Callable[[Request], object]
    submitted_path: Path | None


class SessionHandler(BaseHTTPRequestHandler):
    server: SessionHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def _view_args(self) -> dict:
        return {
            "output_dir": self.server.output_dir,
            "now": self.server.now,
            "opener": self.server.opener,
        }

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/index.html"}:
            body = _PAGE_PATH.read_bytes()
            self._send(200, "text/html; charset=utf-8", body)
            return
        if path in {
            "/static/session-page.js",
            "/static/session-state.js",
            "/static/clock.js",
        }:
            asset = Path(__file__).parent / "static" / Path(path).name
            self._send(200, "text/javascript; charset=utf-8", asset.read_bytes())
            return
        if path == "/api/session":
            self._send_json(200, session_view(self.server.repo_root, **self._view_args()))
            return
        if path == "/api/template":
            template_id = parse_qs(parsed.query).get("id", [None])[0]
            self._send_json(
                200, template_mode_view(self.server.repo_root, template_id=template_id)
            )
            return
        if path in {"/library", "/library.html"}:
            body = _LIBRARY_PAGE_PATH.read_bytes()
            self._send(200, "text/html; charset=utf-8", body)
            return
        if path == "/api/library":
            self._send_json(200, self._library_view())
            return
        self.send_error(404)

    def _library_view(self) -> dict:
        data_dir = self.server.repo_root / "data"
        return {
            key: lister(data_dir) for key, lister in _LIBRARY_VIEW_SECTIONS.items()
        }

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/location":
            payload = self._read_json()
            try:
                lat = float(payload["latitude"])
                lon = float(payload["longitude"])
            except (KeyError, ValueError, TypeError):
                self._send_json(400, {"error": "Invalid coordinates"})
                return
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                self._send_json(400, {"error": "Coordinates out of bounds"})
                return
            data_dir = self.server.repo_root / "data"
            name = reverse_geocode(lat, lon, opener=self.server.opener)
            save_weather_location(data_dir, latitude=lat, longitude=lon, name=name)
            view = session_view(self.server.repo_root, **self._view_args())
            self._send_json(200, view)
            return
        if path == "/api/reset":
            view = reset_session(self.server.repo_root, **self._view_args())
            self._send_json(200, view)
            return
        if path == "/api/add":
            payload = self._read_json()
            kind = payload.get("kind")
            if kind == "draft":
                view = add_draft(
                    self.server.repo_root,
                    name=payload["name"],
                    **self._view_args(),
                )
                self._send_json(200, view)
                return
            if kind == "flex":
                view = add_flex(
                    self.server.repo_root,
                    name=payload["name"],
                    duration_minutes=int(payload["duration_minutes"]),
                    **_checklist_kwargs(payload),
                    **self._view_args(),
                )
                self._send_json(200, view)
                return
            if kind == "todo":
                view = add_todo(
                    self.server.repo_root,
                    name=payload["name"],
                    note=payload.get("note") or "",
                    **self._view_args(),
                )
                self._send_json(200, view)
                return
            if kind != "anchor":
                self.send_error(404)
                return
            view = add_anchor(
                self.server.repo_root,
                name=payload["name"],
                start=payload["start"],
                duration_minutes=int(payload["duration_minutes"]),
                **_checklist_kwargs(payload),
                **self._view_args(),
            )
            self._send_json(200, view)
            return
        if path == "/api/edit":
            payload = self._read_json()
            kind = payload.get("kind")
            if kind == "draft":
                try:
                    view = edit_draft(
                        self.server.repo_root,
                        item_id=payload["id"],
                        name=payload["name"],
                        **self._view_args(),
                    )
                except KeyError as exc:
                    self._send_json(400, {"error": f"Item not found: {exc.args[0] if exc.args else ''}"})
                    return
                except ValueError as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                self._send_json(200, view)
                return
            if kind == "bounds":
                try:
                    view = edit_bounds(
                        self.server.repo_root,
                        wake=payload.get("wake"),
                        sleep=payload.get("sleep"),
                        **self._view_args(),
                    )
                except ValueError as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                self._send_json(200, view)
                return
            if kind in ("anchor", "flex", "todo"):
                item_id = payload.get("id")
                if not item_id:
                    self._send_json(400, {"error": "Item ID is required"})
                    return
                duration = payload.get("duration_minutes")
                try:
                    view = edit_activity(
                        self.server.repo_root,
                        item_id=item_id,
                        kind=kind,
                        name=payload.get("name"),
                        start=payload.get("start"),
                        duration_minutes=int(duration) if duration is not None and str(duration).strip() != "" else None,
                        note=payload.get("note"),
                        remove=bool(payload.get("remove")),
                        **_checklist_kwargs(payload),
                        **self._view_args(),
                    )
                except KeyError as exc:
                    self._send_json(400, {"error": f"Item not found: {exc.args[0] if exc.args else ''}"})
                    return
                except ValueError as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                self._send_json(200, view)
                return
            self.send_error(404)
            return
        if path == "/api/place":
            payload = self._read_json()
            try:
                view = place_flex(
                    self.server.repo_root,
                    item_id=payload["id"],
                    start=payload["start"],
                    **self._view_args(),
                )
            except KeyError as exc:
                self._send_json(400, {"error": f"Item not found: {exc.args[0] if exc.args else ''}"})
                return
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, view)
            return
        if path == "/api/unplace":
            payload = self._read_json()
            try:
                view = unplace_flex(
                    self.server.repo_root,
                    item_id=payload["id"],
                    **self._view_args(),
                )
            except KeyError as exc:
                self._send_json(400, {"error": f"Item not found: {exc.args[0] if exc.args else ''}"})
                return
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, view)
            return
        if path == "/api/change-duration":
            payload = self._read_json()
            try:
                view = change_flex_duration(
                    self.server.repo_root,
                    item_id=payload["id"],
                    duration_minutes=int(payload["duration_minutes"]),
                    **self._view_args(),
                )
            except KeyError as exc:
                self._send_json(400, {"error": f"Item not found: {exc.args[0] if exc.args else ''}"})
                return
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, view)
            return
        if path == "/api/drop":
            payload = self._read_json()
            kind = payload.get("kind")
            try:
                if kind == "draft":
                    view = drop_draft(
                        self.server.repo_root,
                        item_id=payload["id"],
                        **self._view_args(),
                    )
                elif kind == "todo":
                    view = drop_todo(
                        self.server.repo_root,
                        item_id=payload["id"],
                        **self._view_args(),
                    )
                elif kind == "flex":
                    view = drop_flex(
                        self.server.repo_root,
                        item_id=payload["id"],
                        **self._view_args(),
                    )
                else:
                    self.send_error(404)
                    return
            except KeyError as exc:
                self._send_json(400, {"error": f"Item not found: {exc.args[0] if exc.args else ''}"})
                return
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, view)
            return
        if path == "/api/promote":
            payload = self._read_json()
            duration = payload.get("duration_minutes")
            extra = {}
            if "checklist" in payload:
                extra["checklist"] = payload.get("checklist")
            try:
                view = promote_draft(
                    self.server.repo_root,
                    item_id=payload["id"],
                    kind=payload["kind"],
                    duration_minutes=int(duration) if duration is not None else None,
                    start=payload.get("start") or None,
                    name=payload.get("name"),
                    **extra,
                    **self._view_args(),
                )
            except KeyError as exc:
                self._send_json(400, {"error": f"Item not found: {exc.args[0] if exc.args else ''}"})
                return
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, view)
            return
        if path == "/api/promote-checklist":
            payload = self._read_json()
            try:
                view = promote_checklist(
                    self.server.repo_root,
                    item_id=payload["id"],
                    item_kind=payload["kind"],
                    name=payload.get("name") or "",
                    **self._view_args(),
                )
            except KeyError as exc:
                self._send_json(400, {"error": f"Item not found: {exc.args[0] if exc.args else ''}"})
                return
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, view)
            return
        if path == "/api/template":
            payload = self._read_json()
            action = payload.get("action")
            if action == "save":
                try:
                    view = save_template_mode(
                        self.server.repo_root,
                        template_id=payload.get("template_id") or None,
                        name=payload["name"],
                        weekday=payload.get("weekday") or None,
                        wake=payload["wake"],
                        sleep=payload["sleep"],
                        anchors=list(payload.get("anchors", [])),
                        flexes=list(payload.get("flexes", [])),
                    )
                except (KeyError, ValueError) as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                self._send_json(200, view)
                return
            if action == "apply":
                view = apply_template(self.server.repo_root, **self._view_args())
                self._send_json(200, view)
                return
            if action == "apply_named":
                view = apply_named_day_template(
                    self.server.repo_root,
                    template_id=payload["template_id"],
                    **self._view_args(),
                )
                self._send_json(200, view)
                return
            if action == "decline":
                view = decline_template(self.server.repo_root, **self._view_args())
                self._send_json(200, view)
                return
            self.send_error(404)
            return
        if path == "/api/activity-template/insert":
            payload = self._read_json()
            view = insert_activity_template(
                self.server.repo_root,
                activity_id=payload["activity_id"],
                **self._view_args(),
            )
            self._send_json(200, view)
            return
        if path == "/api/suggest-activity":
            payload = self._read_json()
            suggestion = suggest_activity(self.server.repo_root, payload.get("name", ""))
            self._send_json(200, {"suggestion": suggestion})
            return
        if path.startswith("/api/library/"):
            self._handle_library_post(path[len("/api/library/") :])
            return
        if path == "/api/undo":
            view = undo_session(self.server.repo_root, **self._view_args())
            self._send_json(200, view)
            return
        if path == "/api/redo":
            view = redo_session(self.server.repo_root, **self._view_args())
            self._send_json(200, view)
            return
        if path != "/api/submit":
            self.send_error(404)
            return
        try:
            plan_path = submit_session(self.server.repo_root, **self._view_args())
        except (PlanBlockedError, ForeignPlanFileError):
            self._send_json(409, session_view(self.server.repo_root, **self._view_args()))
            return
        self.server.submitted_path = plan_path
        self._send_json(200, {"ok": True, "path": str(plan_path)})
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _handle_library_post(self, entity: str) -> None:
        payload = self._read_json()
        action = payload.get("action")
        ops = _LIBRARY_ENTITY_OPS.get(entity)
        if ops is None:
            self.send_error(404)
            return
        repo_root = self.server.repo_root
        if action == "save":
            try:
                ops.save(repo_root, payload)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
        elif action == "delete":
            ops.delete(repo_root, payload)
        elif action == "reorder" and ops.reorder is not None:
            try:
                ops.reorder(repo_root, payload)
            except ValueError as exc:
                self._send_json(409, {"error": str(exc)})
                return
        else:
            self.send_error(404)
            return
        self._send_json(200, self._library_view())

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

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
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = default_opener,
    host: str = SESSION_HOST,
    port: int = SESSION_PORT,
) -> SessionHTTPServer:
    server = SessionHTTPServer((host, port), SessionHandler)
    server.repo_root = repo_root
    server.output_dir = output_dir
    server.now = now
    server.opener = opener
    server.submitted_path = None
    return server


def run_session(
    repo_root: Path,
    *,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = default_opener,
) -> None:
    try:
        server = bind_session_server(repo_root, output_dir=output_dir, now=now, opener=opener)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        print(f"Port {SESSION_PORT} is already in use.")
        return
    document = refresh_icloud_items(repo_root, output_dir=output_dir, now=now)
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


def run_library(
    repo_root: Path,
    *,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = default_opener,
) -> None:
    """Open the library page without touching the Session (no refresh, no import).

    If a Session server is already running on the usual port, its library
    page is opened instead — this deliberately differs from `run_session`'s
    "Port in use" message, since browsing the library never needs a fresh
    server.
    """

    try:
        server = bind_session_server(repo_root, output_dir=output_dir, now=now, opener=opener)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        webbrowser.open(LIBRARY_URL)
        return
    print(LIBRARY_URL)
    print("Ctrl+C to leave.")
    webbrowser.open(LIBRARY_URL)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return
    finally:
        server.server_close()
