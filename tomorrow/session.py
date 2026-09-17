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

from tomorrow.activity_templates import (
    load_activity_template_library,
    suggest_activity_template,
)
from tomorrow.checklists import load_checklist_library, suggest_checklist
from tomorrow.defaults import DayBounds, load_defaults
from tomorrow.domain import (
    Anchor,
    Draft,
    FinalizeResult,
    Flex,
    PlanBlockedError,
    ToDo,
    compute_gaps,
    describe_blocker,
    finalize_plan,
    is_next_day,
    minutes_since_wake,
    parse_clock,
)
from tomorrow.day_templates import (
    default_day_template_path,
    load_day_template,
    load_day_template_entries,
    load_day_template_name,
    named_day_template_path,
)
from tomorrow.library import (
    _slugify,
    delete_activity_template,
    delete_checklist,
    delete_day_template,
    save_activity_template,
    save_checklist,
    save_day_template,
)
from tomorrow.icloud import try_import_icloud_items
from tomorrow.plan import (
    default_plan_date,
    discard_past_plans,
    format_plan_date,
    write_finalized_plan,
)
from tomorrow.weather import load_weather_name, try_fetch_weather

SESSION_HOST = "127.0.0.1"
SESSION_PORT = 8765
SESSION_URL = f"http://{SESSION_HOST}:{SESSION_PORT}"
LIBRARY_URL = f"{SESSION_URL}/library"
_PAGE_PATH = Path(__file__).parent / "static" / "session.html"
_LIBRARY_PAGE_PATH = Path(__file__).parent / "static" / "library.html"
_WEATHER_TIMEOUT_SECONDS = 5
_UNSET = object()


def _default_opener(request: Request) -> object:
    return urlopen(request, timeout=_WEATHER_TIMEOUT_SECONDS)


def _session_path(repo_root: Path) -> Path:
    return repo_root / "data" / "session.json"


def session_exists_for_plan_date(repo_root: Path, plan_date: date) -> bool:
    """Check for a stored Session without the load_session side effects.

    Used where an on-disk Session's existence needs checking (e.g. before
    changing Defaults) but reading it must not create, refresh, or discard
    anything the way `load_session` does.
    """

    path = _session_path(repo_root)
    if not path.is_file():
        return False
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return document.get("plan_date") == plan_date.isoformat()


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
        "todos": [],
        "undo": {"past": [], "future": []},
        "icloud_seen": [],
    }


def _seed_daily_activities(repo_root: Path, document: dict) -> bool:
    """Add an unplaced Flex for every Daily Activity Template, source="daily".

    Returns True if anything was added. Called both when a new Session
    document is built and on every Reset.
    """

    library = load_activity_template_library(repo_root / "data")
    added = False
    for activity_id, activity in library.items():
        if not activity.daily:
            continue
        document["flexes"].append(
            {
                "id": uuid.uuid4().hex,
                "name": activity.name,
                "duration_minutes": int(activity.duration.total_seconds() // 60),
                "start": None,
                "checklist": activity.checklist,
                "source": "daily",
                "activity_template_id": activity_id,
            }
        )
        added = True
    return added


def _icloud_key(kind: str, item) -> str:
    """Stable identity for an imported item, so a re-import never duplicates it."""
    start = item.start.strftime("%H:%M") if item.start is not None else ""
    return f"{kind}|{item.name}|{start}"


def _seed_icloud_items(repo_root: Path, document: dict) -> bool:
    """Import iCloud items into `document`, skipping anything imported before.

    Returns True if anything was added. The `icloud_seen` ledger is what keeps a
    re-import from resurrecting an item the user has since deleted.
    """

    plan_date = date.fromisoformat(document["plan_date"])
    existing_anchors = _unpack(document)[2]
    imported = try_import_icloud_items(
        repo_root / "data", plan_date, existing_anchors=existing_anchors
    )
    seen = set(document.get("icloud_seen", []))
    added = False

    for item in imported.anchors:
        key = _icloud_key("anchor", item)
        if key in seen:
            continue
        seen.add(key)
        document["anchors"].append(
            {
                "id": uuid.uuid4().hex,
                "name": item.name,
                "start": item.start.strftime("%H:%M"),
                "duration_minutes": item.duration_minutes,
                "checklist": None,
                "source": item.source,
            }
        )
        added = True

    for item in imported.drafts:
        key = _icloud_key("draft", item)
        if key in seen:
            continue
        seen.add(key)
        document["drafts"].append(
            {
                "id": uuid.uuid4().hex,
                "name": item.name,
                "source": item.source,
                "note": item.note,
            }
        )
        added = True

    document["icloud_seen"] = sorted(seen)
    return added


def refresh_icloud_items(repo_root: Path, *, now: datetime | None = None) -> dict:
    """Re-run the iCloud import against the stored Session and persist new items.

    Called once per process at startup, so events and reminders added to iCloud
    since the Session was created show up on the next restart.
    """

    document = load_session(repo_root, now=now)
    if _seed_icloud_items(repo_root, document):
        save_session(repo_root, document)
    return document


def _new_session_document(repo_root: Path, *, now: datetime | None = None) -> dict:
    """Build a brand-new Session document for the current Plan date.

    Undo and Redo never call this; Reset re-runs the same iCloud and daily
    seeding inside its own undoable mutation.
    """

    document = _blank_session(repo_root, now=now)
    _seed_icloud_items(repo_root, document)
    _seed_daily_activities(repo_root, document)
    return document


def save_session(repo_root: Path, document: dict) -> None:
    for draft in document.get("drafts", []):
        draft.pop("checklist", None)
    path = _session_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def load_session(repo_root: Path, *, now: datetime | None = None) -> dict:
    discard_past_plans(repo_root, now=now)
    blank = _blank_session(repo_root, now=now)
    path = _session_path(repo_root)
    if not path.is_file():
        document = _new_session_document(repo_root, now=now)
        # Persist immediately only if there is something to keep stable: an
        # icloud import or daily seeding ran and produced items with ids that
        # must stay put across reloads. A truly empty Session is left
        # unwritten until the first real mutation, as before.
        if _document_has_any_items(document):
            save_session(repo_root, document)
        return document
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("plan_date") != blank["plan_date"]:
        document = _new_session_document(repo_root, now=now)
        save_session(repo_root, document)
        return document
    document.setdefault("todos", [])
    for draft in document.get("drafts", []):
        draft.pop("checklist", None)
    return document


def _default_day_template_file(repo_root: Path, document: dict) -> Path:
    return default_day_template_path(
        repo_root / "data", date.fromisoformat(document["plan_date"])
    )


def _document_has_any_items(document: dict) -> bool:
    return bool(
        document["drafts"]
        or document["anchors"]
        or document["flexes"]
        or document.get("todos")
    )


def _added_by_user(item: dict) -> bool:
    """Whether an Anchor/Flex/Draft record was added by hand rather than
    seeded automatically (daily or iCloud). Records with no `source` predate
    this distinction and count as added by hand.
    """

    return not item.get("source")


def _session_has_items(document: dict) -> bool:
    """"Session has items" for Day Template purposes: automatically added
    items (daily, iCloud) don't count, but To-dos and anything you added,
    promoted, or inserted yourself still block the offer and both applies.
    """

    return bool(
        any(_added_by_user(item) for item in document["drafts"])
        or any(_added_by_user(item) for item in document["anchors"])
        or any(_added_by_user(item) for item in document["flexes"])
        or document.get("todos")
    )


def _show_template_offer(repo_root: Path, document: dict) -> bool:
    if document["template_offer"] != "pending" or _session_has_items(document):
        return False
    return _default_day_template_file(repo_root, document).is_file()


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


def _clean_checklist_items(items: object) -> tuple[str, ...]:
    """Strip blank lines from typed one-time checklist rows.

    `items` is `None`-safe so callers can pass through an unset/None value.
    """

    if not items:
        return ()
    return tuple(line.strip() for line in items if line and line.strip())


def _library_checklist_rows(repo_root: Path, checklist_id: str | None) -> tuple[str, ...] | None:
    """Return a Library Checklist's current rows, or `None` if it has none/doesn't exist."""

    if not checklist_id:
        return None
    entry = load_checklist_library(repo_root / "data").get(checklist_id)
    return entry.items if entry is not None else None


def _resolve_checklist_fields(
    repo_root: Path,
    name: str,
    checklist: str | None | object,
    checklist_items: object,
) -> tuple[str | None, tuple[str, ...]]:
    """Resolve the (checklist, checklist_items) pair for a new item.

    At most one of the two is ever non-empty. Typed rows that exactly match
    an explicitly selected Library Checklist's current rows (the untouched
    prefill from attaching it) keep the item a reference. Any other
    non-blank typed rows win outright as literal, one-time rows (no Library
    lookup, no auto-suggest). Otherwise this falls back to the existing
    Library-reference resolution (`_attached_checklist`), unchanged.
    """

    if checklist_items is not _UNSET:
        cleaned = _clean_checklist_items(checklist_items)
        if cleaned:
            if checklist not in (_UNSET, None):
                if _library_checklist_rows(repo_root, checklist) == cleaned:  # type: ignore[arg-type]
                    return checklist, ()  # type: ignore[return-value]
            return None, cleaned
        if checklist is _UNSET:
            # Rows were explicitly supplied but empty: an explicit "no
            # checklist" rather than "auto-suggest one from the name".
            return None, ()
    attached = _attached_checklist(repo_root, name, checklist)
    return attached, ()


def add_anchor(
    repo_root: Path,
    *,
    name: str,
    start: str,
    duration_minutes: int,
    checklist: str | None | object = _UNSET,
    checklist_items: object = _UNSET,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)
    attached, items = _resolve_checklist_fields(repo_root, name, checklist, checklist_items)

    def mutate(current: dict) -> None:
        current["anchors"].append(
            {
                "id": uuid.uuid4().hex,
                "name": name,
                "start": start,
                "duration_minutes": duration_minutes,
                "checklist": attached,
                "checklist_items": list(items),
            }
        )

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def add_flex(
    repo_root: Path,
    *,
    name: str,
    duration_minutes: int,
    checklist: str | None | object = _UNSET,
    checklist_items: object = _UNSET,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)
    attached, items = _resolve_checklist_fields(repo_root, name, checklist, checklist_items)

    def mutate(current: dict) -> None:
        current["flexes"].append(
            {
                "id": uuid.uuid4().hex,
                "name": name,
                "duration_minutes": duration_minutes,
                "start": None,
                "checklist": attached,
                "checklist_items": list(items),
            }
        )

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def insert_activity_template(
    repo_root: Path,
    *,
    activity_id: str,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    """Insert a single Activity Template into the Session as a new Anchor or Flex.

    Independent of Day Template state: usable at any point in the Session,
    not only when it is blank.
    """

    document = load_session(repo_root, now=now)
    library = load_activity_template_library(repo_root / "data")
    activity = library.get(activity_id)
    if activity is None:
        return session_view(repo_root, now=now, opener=opener)

    def mutate(current: dict) -> None:
        if activity.start is not None:
            current["anchors"].append(
                {
                    "id": uuid.uuid4().hex,
                    "name": activity.name,
                    "start": activity.start.strftime("%H:%M"),
                    "duration_minutes": int(activity.duration.total_seconds() // 60),
                    "checklist": activity.checklist,
                }
            )
        else:
            current["flexes"].append(
                {
                    "id": uuid.uuid4().hex,
                    "name": activity.name,
                    "duration_minutes": int(activity.duration.total_seconds() // 60),
                    "start": None,
                    "checklist": activity.checklist,
                }
            )

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def suggest_activity(
    repo_root: Path, item_name: str
) -> dict | None:
    """Suggest a bundle (start-or-duration plus Checklist) for a typed name.

    Checks the Activity Template library first; an Activity Template match
    takes precedence over the older bare-Checklist-name-match suggestion.
    Falls back to `suggest_checklist` when no Activity Template matches, so
    Checklist-only matching keeps working.
    """

    data_dir = repo_root / "data"
    activity_library = load_activity_template_library(data_dir)
    activity_id = suggest_activity_template(item_name, activity_library)
    if activity_id is not None:
        activity = activity_library[activity_id]
        return {
            "kind": "activity",
            "activity_id": activity_id,
            "name": activity.name,
            "start": activity.start.strftime("%H:%M") if activity.start else None,
            "duration_minutes": int(activity.duration.total_seconds() // 60),
            "checklist": activity.checklist,
        }

    checklist_id = suggest_checklist(item_name, load_checklist_library(data_dir))
    if checklist_id is not None:
        return {"kind": "checklist", "checklist_id": checklist_id}
    return None


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


def _new_todo(name: str, note: str = "") -> dict:
    return {"id": uuid.uuid4().hex, "name": name, "note": note}


def add_todo(
    repo_root: Path,
    *,
    name: str,
    note: str = "",
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        current["todos"].append(_new_todo(name, note))

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def edit_todo(
    repo_root: Path,
    *,
    item_id: str,
    name: str | None = None,
    note: str | None = None,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        todo = _item_by_id(current["todos"], item_id)
        if name is not None:
            todo["name"] = name
        if note is not None:
            todo["note"] = note

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def drop_todo(
    repo_root: Path,
    *,
    item_id: str,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        _drop_keyed(current, "todos", item_id)

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def convert_todo_to_flex(
    repo_root: Path,
    *,
    item_id: str,
    duration_minutes: int,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        todo = _drop_keyed(current, "todos", item_id)
        current["flexes"].append(
            {
                "id": uuid.uuid4().hex,
                "name": todo["name"],
                "duration_minutes": duration_minutes,
                "start": None,
                "checklist": None,
            }
        )

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def convert_todo_to_anchor(
    repo_root: Path,
    *,
    item_id: str,
    start: str,
    duration_minutes: int,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        todo = _drop_keyed(current, "todos", item_id)
        current["anchors"].append(
            {
                "id": uuid.uuid4().hex,
                "name": todo["name"],
                "start": start,
                "duration_minutes": duration_minutes,
                "checklist": None,
            }
        )

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def convert_flex_to_todo(
    repo_root: Path,
    *,
    item_id: str,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        flex = _drop_keyed(current, "flexes", item_id)
        current["todos"].append(_new_todo(flex["name"]))

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


def change_flex_duration(
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


def edit_draft(
    repo_root: Path,
    *,
    item_id: str,
    name: str,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)
    _item_by_id(document["drafts"], item_id)
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("Draft name cannot be blank.")

    def mutate(current: dict) -> None:
        draft = _item_by_id(current["drafts"], item_id)
        draft["name"] = trimmed

    return _commit(repo_root, document, mutate, now=now, opener=opener)


def promote_draft(
    repo_root: Path,
    *,
    item_id: str,
    kind: str,
    duration_minutes: int | None = None,
    start: str | None = None,
    name: str | None = None,
    checklist: str | None | object = _UNSET,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)
    draft = _item_by_id(document["drafts"], item_id)
    resolved_name = draft["name"] if name is None else name.strip()
    if not resolved_name:
        raise ValueError("Draft name cannot be blank.")
    attached = _attached_checklist(repo_root, resolved_name, checklist)
    source = draft.get("source")

    def mutate(current: dict) -> None:
        _drop_keyed(current, "drafts", item_id)
        new_id = uuid.uuid4().hex
        if kind == "todo":
            current["todos"].append(_new_todo(resolved_name, draft.get("note") or ""))
            return
        entry = {"id": new_id, "name": resolved_name}
        if kind == "anchor":
            entry["start"] = start
            entry["duration_minutes"] = duration_minutes
            entry["checklist"] = attached
            if source is not None:
                entry["source"] = source
            current["anchors"].append(entry)
            return
        if kind == "flex":
            entry["duration_minutes"] = duration_minutes
            entry["start"] = start
            entry["checklist"] = attached
            if source is not None:
                entry["source"] = source
            current["flexes"].append(entry)
            return
        raise ValueError(kind)

    return _commit(repo_root, document, mutate, now=now, opener=opener)


_ITEM_KIND_KEYS = {"anchor": "anchors", "flex": "flexes"}


def promote_checklist(
    repo_root: Path,
    *,
    item_id: str,
    item_kind: str,
    name: str,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    """Save an item's one-time checklist rows to the Library under `name`.

    Copy-out only: the Session item is not read again after its rows are
    fetched and is never rewritten, so this deliberately bypasses `_commit`
    and its undo-snapshotting. Rejects when `name`'s slug already matches an
    existing Library Checklist, leaving that file untouched.
    """

    key = _ITEM_KIND_KEYS.get(item_kind)
    if key is None:
        raise ValueError(item_kind)
    document = load_session(repo_root, now=now)
    item = _item_by_id(document[key], item_id)
    rows = list(item.get("checklist_items") or ())

    trimmed = name.strip()
    if not trimmed:
        raise ValueError("Checklist name cannot be blank.")

    data_dir = repo_root / "data"
    slug = _slugify(trimmed)
    if slug in load_checklist_library(data_dir):
        raise ValueError(f'A Checklist named "{trimmed}" already exists.')

    save_checklist(repo_root, checklist_id=slug, name=trimmed, items=rows)
    return session_view(repo_root, now=now, opener=opener)


def _is_duplicate_of_seed_entry(
    flex: dict, *, entry_ids: set[str], entry_names: set[str]
) -> bool:
    if flex.get("source") != "daily":
        return False
    activity_id = flex.get("activity_template_id")
    if activity_id and activity_id in entry_ids:
        return True
    return flex["name"].strip().lower() in entry_names


def _seed_mutation(seed) -> Callable[[dict], None]:
    entry_ids = {
        entry.activity_template_id
        for entry in (*seed.anchors, *seed.flexes)
        if entry.activity_template_id
    }
    entry_names = {entry.name.strip().lower() for entry in (*seed.anchors, *seed.flexes)}

    def mutate(current: dict) -> None:
        current["flexes"] = [
            flex
            for flex in current["flexes"]
            if not _is_duplicate_of_seed_entry(
                flex, entry_ids=entry_ids, entry_names=entry_names
            )
        ]
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

    return mutate


def apply_template(
    repo_root: Path,
    *,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)
    activity_library = load_activity_template_library(repo_root / "data")
    seed = load_day_template(
        _default_day_template_file(repo_root, document), activity_library
    )
    if (
        seed is None
        or document["template_offer"] != "pending"
        or _session_has_items(document)
    ):
        return session_view(repo_root, now=now, opener=opener)

    return _commit(repo_root, document, _seed_mutation(seed), now=now, opener=opener)


def apply_named_day_template(
    repo_root: Path,
    *,
    template_id: str,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    """Manually seed the Session from a specific Day Template by id.

    Reuses the blank-Session-only guard used by the weekday auto-offer: a
    Day Template can only ever seed a blank Session, whether chosen
    automatically or picked by name.
    """

    document = load_session(repo_root, now=now)
    if _session_has_items(document):
        return session_view(repo_root, now=now, opener=opener)

    activity_library = load_activity_template_library(repo_root / "data")
    seed = load_day_template(
        named_day_template_path(repo_root / "data", template_id), activity_library
    )
    if seed is None:
        return session_view(repo_root, now=now, opener=opener)

    return _commit(repo_root, document, _seed_mutation(seed), now=now, opener=opener)


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
    repo_root: Path,
    item: dict,
    *,
    name: str,
    checklist: object,
    checklist_items: object = _UNSET,
) -> None:
    current_checklist = item.get("checklist")
    if checklist is not _UNSET and checklist != current_checklist:
        # The select was changed to a different Checklist (or cleared): that
        # always wins outright, discarding whatever the rows editor holds,
        # per the "re-attaching overwrites typed rows" rule (Undo recovers
        # them, not a confirmation dialog).
        item["checklist"] = checklist
        item["checklist_items"] = []
        return
    if checklist_items is not _UNSET:
        cleaned = _clean_checklist_items(checklist_items)
        if cleaned:
            reference = checklist if checklist is not _UNSET else current_checklist
            if reference and _library_checklist_rows(repo_root, reference) == cleaned:
                # Rows match the referenced Checklist's current rows
                # verbatim: nothing was actually edited (e.g. a plain
                # re-save), so the reference stays attached.
                item["checklist"] = reference
                item["checklist_items"] = []
                return
            # The rows editor was edited away from what the referenced
            # Checklist holds (or there was no reference at all): detach.
            # One rule, no provenance marker, no merge with the Library.
            item["checklist_items"] = list(cleaned)
            item["checklist"] = None
            return
        item["checklist_items"] = []
        if checklist is _UNSET:
            # Rows explicitly cleared to empty: leave the item with no
            # checklist at all, rather than falling through to auto-suggest.
            item["checklist"] = None
            return
    if checklist is not _UNSET:
        item["checklist"] = checklist
        item["checklist_items"] = []
    elif not item.get("checklist") and not item.get("checklist_items"):
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
    checklist_items: object = _UNSET,
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
            repo_root,
            flex,
            name=flex["name"],
            checklist=checklist,
            checklist_items=checklist_items,
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
    checklist_items: object = _UNSET,
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
                    repo_root,
                    anchor,
                    name=anchor["name"],
                    checklist=checklist,
                    checklist_items=checklist_items,
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


def _unpack(
    document: dict,
) -> tuple[DayBounds, list[Draft], list[Anchor], list[Flex], list[ToDo]]:
    bounds = DayBounds(
        wake=document["bounds"]["wake"],
        sleep=document["bounds"]["sleep"],
    )
    drafts = [
        Draft(name=item["name"], source=item.get("source"), note=item.get("note"))
        for item in document["drafts"]
    ]
    anchors = [
        Anchor(
            name=item["name"],
            start=parse_clock(item["start"]),
            duration=timedelta(minutes=item["duration_minutes"]),
            checklist=item.get("checklist"),
            checklist_items=tuple(item.get("checklist_items") or ()),
            source=item.get("source"),
        )
        for item in document["anchors"]
    ]
    flexes = [
        Flex(
            name=item["name"],
            duration=timedelta(minutes=item["duration_minutes"]),
            start=parse_clock(item["start"]) if item.get("start") else None,
            checklist=item.get("checklist"),
            checklist_items=tuple(item.get("checklist_items") or ()),
            source=item.get("source"),
            activity_template_id=item.get("activity_template_id"),
        )
        for item in document["flexes"]
    ]
    todos = [
        ToDo(name=item["name"], note=item.get("note") or "")
        for item in document.get("todos", [])
    ]
    return bounds, drafts, anchors, flexes, todos


def _finalize_document(document: dict) -> FinalizeResult:
    bounds, drafts, anchors, flexes, todos = _unpack(document)
    return finalize_plan(
        bounds=bounds, drafts=drafts, anchors=anchors, flexes=flexes, todos=todos
    )


def _with_checklist_kind(item: dict) -> dict:
    """Report per-item whether the checklist is a Library reference or typed rows.

    Raw item dicts are passed through to the frontend, so this adds a
    `checklist_kind` key without mutating the stored document.
    """

    view = dict(item)
    if item.get("checklist_items"):
        view["checklist_kind"] = "literal"
    elif item.get("checklist"):
        view["checklist_kind"] = "reference"
    else:
        view["checklist_kind"] = None
    return view


def session_view(
    repo_root: Path,
    *,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)
    bounds, drafts, anchors, flexes, todos = _unpack(document)
    result = finalize_plan(
        bounds=bounds, drafts=drafts, anchors=anchors, flexes=flexes, todos=todos
    )
    undo = document.get("undo", {"past": [], "future": []})
    plan_date = date.fromisoformat(document["plan_date"])
    data_dir = repo_root / "data"
    wake_time = parse_clock(bounds.wake)
    gaps = []
    for gap in compute_gaps(bounds=bounds, anchors=anchors):
        gap_view = {
            "start": gap.start.strftime("%H:%M"),
            "end": gap.end.strftime("%H:%M"),
            "duration_minutes": minutes_since_wake(gap.end, wake=wake_time)
            - minutes_since_wake(gap.start, wake=wake_time),
        }
        if is_next_day(gap.start, wake=wake_time):
            gap_view["start_is_next_day"] = True
        if is_next_day(gap.end, wake=wake_time):
            gap_view["end_is_next_day"] = True
        gaps.append(gap_view)
    bounds_view = dict(document["bounds"])
    if is_next_day(parse_clock(bounds.sleep), wake=wake_time):
        bounds_view["sleep_is_next_day"] = True
    return {
        "plan_date": document["plan_date"],
        "plan_date_label": format_plan_date(plan_date),
        "bounds": bounds_view,
        "template_offer": document["template_offer"],
        "show_template_offer": _show_template_offer(repo_root, document),
        "drafts": [
            {key: value for key, value in item.items() if key != "checklist"}
            for item in document["drafts"]
        ],
        "anchors": [_with_checklist_kind(item) for item in document["anchors"]],
        "flexes": [_with_checklist_kind(item) for item in document["flexes"]],
        "todos": document.get("todos", []),
        "gaps": gaps,
        "blockers": [describe_blocker(blocker) for blocker in result.blockers],
        "can_undo": bool(undo.get("past")),
        "can_redo": bool(undo.get("future")),
        "weather_name": load_weather_name(data_dir),
        "weather_one_liner": try_fetch_weather(data_dir, plan_date, opener=opener),
        "checklists": [
            {
                "id": checklist_id,
                "name": checklist.name,
                "items": list(checklist.items),
            }
            for checklist_id, checklist in load_checklist_library(data_dir).items()
        ],
    }


def undo_session(
    repo_root: Path,
    *,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)
    undo = document.get("undo", {"past": [], "future": []})
    past = list(undo.get("past", []))
    if not past:
        return session_view(repo_root, now=now, opener=opener)
    future = list(undo.get("future", []))
    snapshot = past.pop()
    future.append(_snapshot_without_undo(document))
    restored = copy.deepcopy(snapshot)
    restored["undo"] = {"past": past, "future": future}
    save_session(repo_root, restored)
    return session_view(repo_root, now=now, opener=opener)


def redo_session(
    repo_root: Path,
    *,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)
    undo = document.get("undo", {"past": [], "future": []})
    future = list(undo.get("future", []))
    if not future:
        return session_view(repo_root, now=now, opener=opener)
    past = list(undo.get("past", []))
    snapshot = future.pop()
    past.append(_snapshot_without_undo(document))
    restored = copy.deepcopy(snapshot)
    restored["undo"] = {"past": past[-20:], "future": future}
    save_session(repo_root, restored)
    return session_view(repo_root, now=now, opener=opener)


def reset_session(
    repo_root: Path,
    *,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, now=now)
    blank = _blank_session(repo_root, now=now)

    def mutate(current: dict) -> None:
        current["bounds"] = blank["bounds"]
        current["template_offer"] = blank["template_offer"]
        current["drafts"] = []
        current["anchors"] = []
        current["flexes"] = []
        current["todos"] = []
        # Reset forgets what was imported, so dropped iCloud items come back.
        current["icloud_seen"] = []
        _seed_icloud_items(repo_root, current)
        _seed_daily_activities(repo_root, current)

    return _commit(repo_root, document, mutate, now=now, opener=opener)


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


def _optional_checklist_items(payload: dict) -> object:
    if "checklist_items" not in payload:
        return _UNSET
    return payload.get("checklist_items")


def _list_checklists(data_dir: Path) -> list[dict]:
    return [
        {"id": checklist_id, "name": checklist.name}
        for checklist_id, checklist in load_checklist_library(data_dir).items()
    ]


def _list_activity_templates(data_dir: Path) -> list[dict]:
    return [
        {
            "id": activity_id,
            "name": activity.name,
            "is_anchor_shaped": activity.start is not None,
            "daily": activity.daily,
        }
        for activity_id, activity in load_activity_template_library(data_dir).items()
    ]


def _list_day_templates(data_dir: Path) -> list[dict]:
    templates_dir = data_dir / "templates"
    paths = sorted(templates_dir.glob("*.toml")) if templates_dir.is_dir() else []
    return [
        {
            "id": path.stem,
            "name": load_day_template_name(path),
            **load_day_template_entries(path),
        }
        for path in paths
    ]


_LIBRARY_VIEW_SECTIONS: dict[str, Callable[[Path], list[dict]]] = {
    "checklists": _list_checklists,
    "activity_templates": _list_activity_templates,
    "day_templates": _list_day_templates,
}


class _LibraryEntityOps:
    """Save/delete callbacks for one `/api/library/<entity>` kind."""

    def __init__(
        self,
        save: Callable[[Path, dict], None],
        delete: Callable[[Path, dict], None],
    ) -> None:
        self.save = save
        self.delete = delete


def _save_checklist_entity(repo_root: Path, payload: dict) -> None:
    save_checklist(
        repo_root,
        checklist_id=payload["id"],
        name=payload["name"],
        items=list(payload.get("items", [])),
    )


def _save_activity_template_entity(repo_root: Path, payload: dict) -> None:
    save_activity_template(
        repo_root,
        activity_id=payload["id"],
        name=payload["name"],
        duration_minutes=int(payload["duration_minutes"]),
        start=payload.get("start") or None,
        checklist=payload.get("checklist") or None,
        daily=bool(payload.get("daily", False)),
    )


def _save_day_template_entity(repo_root: Path, payload: dict) -> None:
    save_day_template(
        repo_root,
        template_id=payload["id"],
        name=payload["name"],
        anchors=payload.get("anchors"),
        flexes=payload.get("flexes"),
        weekday=payload.get("weekday") or None,
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
    ),
}


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
                    checklist_items=_optional_checklist_items(payload),
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
                checklist=_optional_checklist(payload),
                checklist_items=_optional_checklist_items(payload),
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
                except ValueError as exc:
                    self._send_json(400, {"error": str(exc)})
                    return
                self._send_json(200, view)
                return
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
                    checklist_items=_optional_checklist_items(payload),
                    **self._view_args(),
                )
                self._send_json(200, view)
                return
            if kind == "todo":
                view = edit_todo(
                    self.server.repo_root,
                    item_id=payload["id"],
                    name=payload.get("name"),
                    note=payload.get("note"),
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
                checklist_items=_optional_checklist_items(payload),
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
        if path == "/api/change-duration":
            payload = self._read_json()
            view = change_flex_duration(
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
            if kind == "todo":
                view = drop_todo(
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
            duration = payload.get("duration_minutes")
            try:
                view = promote_draft(
                    self.server.repo_root,
                    item_id=payload["id"],
                    kind=payload["kind"],
                    duration_minutes=int(duration) if duration is not None else None,
                    start=payload.get("start") or None,
                    name=payload.get("name"),
                    checklist=_optional_checklist(payload),
                    **self._view_args(),
                )
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
            except (ValueError, KeyError) as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, view)
            return
        if path == "/api/convert":
            payload = self._read_json()
            kind = payload.get("kind")
            if kind == "todo-to-flex":
                view = convert_todo_to_flex(
                    self.server.repo_root,
                    item_id=payload["id"],
                    duration_minutes=int(payload["duration_minutes"]),
                    **self._view_args(),
                )
                self._send_json(200, view)
                return
            if kind == "todo-to-anchor":
                view = convert_todo_to_anchor(
                    self.server.repo_root,
                    item_id=payload["id"],
                    start=payload["start"],
                    duration_minutes=int(payload["duration_minutes"]),
                    **self._view_args(),
                )
                self._send_json(200, view)
                return
            if kind != "flex-to-todo":
                self.send_error(404)
                return
            view = convert_flex_to_todo(
                self.server.repo_root,
                item_id=payload["id"],
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
        except PlanBlockedError:
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
    document = refresh_icloud_items(repo_root, now=now)
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
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> None:
    """Open the library page without touching the Session (no refresh, no import).

    If a Session server is already running on the usual port, its library
    page is opened instead — this deliberately differs from `run_session`'s
    "Port in use" message, since browsing the library never needs a fresh
    server.
    """

    try:
        server = bind_session_server(repo_root, now=now, opener=opener)
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
