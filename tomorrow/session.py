from __future__ import annotations

from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import copy
import errno
import json
import threading
import uuid
import webbrowser

from tomorrow.checklists import load_checklist_library, suggest_checklist
from tomorrow.defaults import DayBounds, load_defaults
from tomorrow.domain import (
    Anchor,
    Draft,
    FinalizeResult,
    Flex,
    PlanBlockedError,
    compute_gaps,
    describe_blocker,
    finalize_plan,
    minutes_between,
    parse_clock,
)
from tomorrow.plan import default_plan_date, format_plan_date, write_finalized_plan
from tomorrow.weather import load_weather_name, try_fetch_weather
from tomorrow.weekday_template import load_weekday_template, weekday_template_path

SESSION_HOST = "127.0.0.1"
SESSION_PORT = 8765
SESSION_URL = f"http://{SESSION_HOST}:{SESSION_PORT}"
_PAGE_PATH = Path(__file__).parent / "static" / "session.html"
_WEATHER_TIMEOUT_SECONDS = 5
_UNSET = object()


def _default_opener(request: Request) -> object:
    return urlopen(request, timeout=_WEATHER_TIMEOUT_SECONDS)


def _session_path(repo_root: Path) -> Path:
    return repo_root / "data" / "session.json"


def _blank_session(repo_root: Path, *, now: datetime | None = None) -> dict:
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


def save_session(repo_root: Path, document: dict) -> None:
    for draft in document.get("drafts", []):
        draft.pop("checklist", None)
    path = _session_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _discard_past_plans(repo_root: Path, *, now: datetime | None = None) -> None:
    today = (now if now is not None else datetime.now()).date()
    plans_dir = repo_root / "plans"
    if not plans_dir.is_dir():
        return
    for path in plans_dir.glob("*.html"):
        try:
            plan_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if plan_date < today:
            path.unlink()


def load_session(repo_root: Path, *, now: datetime | None = None) -> dict:
    _discard_past_plans(repo_root, now=now)
    blank = _blank_session(repo_root, now=now)
    path = _session_path(repo_root)
    if not path.is_file():
        return blank
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("plan_date") != blank["plan_date"]:
        save_session(repo_root, blank)
        return blank
    for draft in document.get("drafts", []):
        draft.pop("checklist", None)
    return document


def _weekday_template_file(repo_root: Path, document: dict) -> Path:
    return weekday_template_path(
        repo_root / "data", date.fromisoformat(document["plan_date"])
    )


def _session_has_items(document: dict) -> bool:
    return bool(document["drafts"] or document["anchors"] or document["flexes"])


def _show_template_offer(repo_root: Path, document: dict) -> bool:
    if document["template_offer"] != "pending" or _session_has_items(document):
        return False
    return _weekday_template_file(repo_root, document).is_file()


def _snapshot_without_undo(document: dict) -> dict:
    snapshot = copy.deepcopy(document)
    snapshot.pop("undo", None)
    return snapshot


def _apply_mutation(document: dict, mutate: Callable[[dict], None]) -> None:
    undo = document.get("undo", {"past": [], "future": []})
    past = list(undo.get("past", []))
    past.append(_snapshot_without_undo(document))
    mutate(document)
    document["undo"] = {"past": past[-20:], "future": []}


def _commit(
    repo_root: Path,
    document: dict,
    mutate: Callable[[dict], None],
    *,
    now: datetime | None,
    opener: Callable[[Request], object],
) -> dict:
    _apply_mutation(document, mutate)
    save_session(repo_root, document)
    return session_view(repo_root, now=now, opener=opener)


def _attached_checklist(
    repo_root: Path, name: str, checklist: str | None | object
) -> str | None:
    if checklist is not _UNSET:
        return checklist  # type: ignore[return-value]
    return suggest_checklist(name, load_checklist_library(repo_root / "data"))


def add_anchor(
    repo_root: Path,
    *,
    name: str,
    start: str,
    duration_minutes: int,
    checklist: str | None | object = _UNSET,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)
    attached = _attached_checklist(repo_root, name, checklist)

    def mutate(current: dict) -> None:
        current["anchors"].append(
            {
                "id": uuid.uuid4().hex,
                "name": name,
                "start": start,
                "duration_minutes": duration_minutes,
                "checklist": attached,
            }
        )

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def add_flex(
    repo_root: Path,
    *,
    name: str,
    duration_minutes: int,
    checklist: str | None | object = _UNSET,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)
    attached = _attached_checklist(repo_root, name, checklist)

    def mutate(current: dict) -> None:
        current["flexes"].append(
            {
                "id": uuid.uuid4().hex,
                "name": name,
                "duration_minutes": duration_minutes,
                "start": None,
                "checklist": attached,
            }
        )

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def _item_by_id(items: list, item_id: str) -> dict:
    for item in items:
        if item["id"] == item_id:
            return item
    raise KeyError(item_id)


def _drop_keyed(current: dict, key: str, item_id: str) -> dict:
    item = _item_by_id(current[key], item_id)
    current[key] = [entry for entry in current[key] if entry["id"] != item_id]
    return item


def add_draft(
    repo_root: Path,
    *,
    name: str,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        current["drafts"].append({"id": uuid.uuid4().hex, "name": name})

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def _require_flex(current: dict, item_id: str) -> dict:
    return _item_by_id(current["flexes"], item_id)


def place_flex(
    repo_root: Path,
    *,
    item_id: str,
    start: str,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        _require_flex(current, item_id)["start"] = start

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def shrink_flex(
    repo_root: Path,
    *,
    item_id: str,
    duration_minutes: int,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        _require_flex(current, item_id)["duration_minutes"] = duration_minutes

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def drop_flex(
    repo_root: Path,
    *,
    item_id: str,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        _drop_keyed(current, "flexes", item_id)

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def drop_draft(
    repo_root: Path,
    *,
    item_id: str,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        _drop_keyed(current, "drafts", item_id)

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def promote_draft(
    repo_root: Path,
    *,
    item_id: str,
    kind: str,
    duration_minutes: int,
    start: str | None = None,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        draft = _drop_keyed(current, "drafts", item_id)
        new_id = uuid.uuid4().hex
        if kind == "anchor":
            current["anchors"].append(
                {
                    "id": new_id,
                    "name": draft["name"],
                    "start": start,
                    "duration_minutes": duration_minutes,
                    "checklist": None,
                }
            )
            return
        if kind == "flex":
            current["flexes"].append(
                {
                    "id": new_id,
                    "name": draft["name"],
                    "duration_minutes": duration_minutes,
                    "start": start,
                    "checklist": None,
                }
            )
            return
        raise ValueError(kind)

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def apply_template(
    repo_root: Path,
    *,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)
    seed = load_weekday_template(_weekday_template_file(repo_root, document))
    if (
        seed is None
        or document["template_offer"] != "pending"
        or _session_has_items(document)
    ):
        return session_view(repo_root, now=now, opener=opener)

    def mutate(current: dict) -> None:
        current["anchors"].extend(
            {
                "id": uuid.uuid4().hex,
                "name": anchor.name,
                "start": anchor.start.strftime("%H:%M"),
                "duration_minutes": int(anchor.duration.total_seconds() // 60),
                "checklist": anchor.checklist,
            }
            for anchor in seed.anchors
        )
        current["flexes"].extend(
            {
                "id": uuid.uuid4().hex,
                "name": flex.name,
                "duration_minutes": int(flex.duration.total_seconds() // 60),
                "start": None,
                "checklist": flex.checklist,
            }
            for flex in seed.flexes
        )
        current["template_offer"] = "accepted"

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def decline_template(
    repo_root: Path,
    *,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)
    if document["template_offer"] != "pending":
        return session_view(repo_root, now=now, opener=opener)

    def mutate(current: dict) -> None:
        current["template_offer"] = "declined"

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def _apply_item_checklist(
    repo_root: Path, item: dict, *, name: str, checklist: object
) -> None:
    if checklist is not _UNSET:
        item["checklist"] = checklist
    elif not item.get("checklist"):
        item["checklist"] = suggest_checklist(
            name, load_checklist_library(repo_root / "data")
        )


def edit_flex(
    repo_root: Path,
    *,
    item_id: str,
    name: str | None = None,
    duration_minutes: int | None = None,
    checklist: str | None | object = _UNSET,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        flex = _require_flex(current, item_id)
        if name is not None:
            flex["name"] = name
        if duration_minutes is not None:
            flex["duration_minutes"] = duration_minutes
        _apply_item_checklist(
            repo_root, flex, name=flex["name"], checklist=checklist
        )

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def edit_anchor(
    repo_root: Path,
    *,
    item_id: str,
    name: str | None = None,
    start: str | None = None,
    duration_minutes: int | None = None,
    checklist: str | None | object = _UNSET,
    remove: bool = False,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        if remove:
            remaining = [
                anchor for anchor in current["anchors"] if anchor["id"] != item_id
            ]
            if len(remaining) == len(current["anchors"]):
                raise KeyError(item_id)
            current["anchors"] = remaining
            return
        for anchor in current["anchors"]:
            if anchor["id"] == item_id:
                if name is not None:
                    anchor["name"] = name
                if start is not None:
                    anchor["start"] = start
                if duration_minutes is not None:
                    anchor["duration_minutes"] = duration_minutes
                _apply_item_checklist(
                    repo_root, anchor, name=anchor["name"], checklist=checklist
                )
                return
        raise KeyError(item_id)

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def edit_bounds(
    repo_root: Path,
    *,
    wake: str | None = None,
    sleep: str | None = None,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        if wake is not None:
            current["bounds"]["wake"] = wake
        if sleep is not None:
            current["bounds"]["sleep"] = sleep

    return _commit(repo_root, document, mutate, now=now, opener=opener)


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
    bounds, drafts, anchors, flexes = _unpack(document)
    result = finalize_plan(
        bounds=bounds, drafts=drafts, anchors=anchors, flexes=flexes
    )
    undo = document.get("undo", {"past": [], "future": []})
    plan_date = date.fromisoformat(document["plan_date"])
    data_dir = repo_root / "data"
    gaps = [
        {
            "start": gap.start.strftime("%H:%M"),
            "end": gap.end.strftime("%H:%M"),
            "duration_minutes": minutes_between(gap.start, gap.end),
        }
        for gap in compute_gaps(bounds=bounds, anchors=anchors)
    ]
    return {
        "plan_date": document["plan_date"],
        "plan_date_label": format_plan_date(plan_date),
        "bounds": document["bounds"],
        "template_offer": document["template_offer"],
        "show_template_offer": _show_template_offer(repo_root, document),
        "drafts": [
            {key: value for key, value in item.items() if key != "checklist"}
            for item in document["drafts"]
        ],
        "anchors": document["anchors"],
        "flexes": document["flexes"],
        "gaps": gaps,
        "blockers": [describe_blocker(blocker) for blocker in result.blockers],
        "can_undo": bool(undo.get("past")),
        "can_redo": bool(undo.get("future")),
        "weather_name": load_weather_name(data_dir),
        "weather_one_liner": try_fetch_weather(data_dir, plan_date, opener=opener),
        "checklists": [
            {"id": checklist_id, "name": checklist.name}
            for checklist_id, checklist in load_checklist_library(data_dir).items()
        ],
    }


def reset_session(
    repo_root: Path,
    *,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    save_session(repo_root, _blank_session(repo_root, now=now))
    return session_view(repo_root, now=now, opener=opener)


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


def _optional_checklist(payload: dict) -> str | None | object:
    if "checklist" not in payload:
        return _UNSET
    return payload.get("checklist")


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

    def _view_args(self) -> dict:
        return {
            "now": self.server.now,
            "opener": self.server.opener,
        }

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            body = _PAGE_PATH.read_bytes()
            self._send(200, "text/html; charset=utf-8", body)
            return
        if path == "/api/session":
            self._send_json(200, session_view(self.server.repo_root, **self._view_args()))
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
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
                    checklist=_optional_checklist(payload),
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
                checklist=_optional_checklist(payload),
                **self._view_args(),
            )
            self._send_json(200, view)
            return
        if path == "/api/edit":
            payload = self._read_json()
            kind = payload.get("kind")
            if kind == "bounds":
                view = edit_bounds(
                    self.server.repo_root,
                    wake=payload.get("wake"),
                    sleep=payload.get("sleep"),
                    **self._view_args(),
                )
                self._send_json(200, view)
                return
            if kind == "flex":
                duration = payload.get("duration_minutes")
                view = edit_flex(
                    self.server.repo_root,
                    item_id=payload["id"],
                    name=payload.get("name"),
                    duration_minutes=int(duration) if duration is not None else None,
                    checklist=_optional_checklist(payload),
                    **self._view_args(),
                )
                self._send_json(200, view)
                return
            if kind != "anchor":
                self.send_error(404)
                return
            duration = payload.get("duration_minutes")
            view = edit_anchor(
                self.server.repo_root,
                item_id=payload["id"],
                name=payload.get("name"),
                start=payload.get("start"),
                duration_minutes=int(duration) if duration is not None else None,
                checklist=_optional_checklist(payload),
                remove=bool(payload.get("remove")),
                **self._view_args(),
            )
            self._send_json(200, view)
            return
        if path == "/api/place":
            payload = self._read_json()
            view = place_flex(
                self.server.repo_root,
                item_id=payload["id"],
                start=payload["start"],
                **self._view_args(),
            )
            self._send_json(200, view)
            return
        if path == "/api/shrink":
            payload = self._read_json()
            view = shrink_flex(
                self.server.repo_root,
                item_id=payload["id"],
                duration_minutes=int(payload["duration_minutes"]),
                **self._view_args(),
            )
            self._send_json(200, view)
            return
        if path == "/api/drop":
            payload = self._read_json()
            kind = payload.get("kind")
            if kind == "draft":
                view = drop_draft(
                    self.server.repo_root,
                    item_id=payload["id"],
                    **self._view_args(),
                )
                self._send_json(200, view)
                return
            if kind != "flex":
                self.send_error(404)
                return
            view = drop_flex(
                self.server.repo_root,
                item_id=payload["id"],
                **self._view_args(),
            )
            self._send_json(200, view)
            return
        if path == "/api/promote":
            payload = self._read_json()
            view = promote_draft(
                self.server.repo_root,
                item_id=payload["id"],
                kind=payload["kind"],
                duration_minutes=int(payload["duration_minutes"]),
                start=payload.get("start") or None,
                **self._view_args(),
            )
            self._send_json(200, view)
            return
        if path == "/api/template":
            payload = self._read_json()
            action = payload.get("action")
            if action == "apply":
                view = apply_template(self.server.repo_root, **self._view_args())
                self._send_json(200, view)
                return
            if action == "decline":
                view = decline_template(self.server.repo_root, **self._view_args())
                self._send_json(200, view)
                return
            self.send_error(404)
            return
        if path != "/api/submit":
            self.send_error(404)
            return
        try:
            plan_path = submit_session(self.server.repo_root, **self._view_args())
        except PlanBlockedError:
            self._send_json(409, session_view(self.server.repo_root, **self._view_args()))
            return
        self.server.submitted_path = plan_path
        self._send_json(200, {"ok": True, "path": str(plan_path)})
        threading.Thread(target=self.server.shutdown, daemon=True).start()

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
