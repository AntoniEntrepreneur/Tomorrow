from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Sequence
from urllib.request import Request, urlopen
import copy
import errno
import json
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
    AnchorOverlapBlocker,
    Draft,
    FinalizeResult,
    Flex,
    PlanBlockedError,
    ToDo,
    compute_gaps,
    describe_blocker,
    finalize_plan,
    is_next_day,
    minutes_between,
    minutes_since_midnight,
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
    day_template_order,
    delete_activity_template,
    delete_checklist,
    delete_day_template,
    save_activity_template,
    save_checklist,
    save_day_template,
    reorder_day_templates,
)
from tomorrow.icloud import try_import_icloud_items
from tomorrow.name_times import NameTimeResult, parse_name_time
from tomorrow.plan import (
    default_plan_date,
    describe_foreign_plan_file,
    discard_past_plans,
    ensure_plan_file_not_foreign,
    format_plan_date,
    write_finalized_plan,
)
from tomorrow.weather import (
    format_weather_one_liner,
    load_weather_name,
    try_fetch_weather,
    try_fetch_weather_forecast,
)

SESSION_HOST = "127.0.0.1"
SESSION_PORT = 8765
SESSION_URL = f"http://{SESSION_HOST}:{SESSION_PORT}"
LIBRARY_URL = f"{SESSION_URL}/library"
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
        draft = {
            "id": uuid.uuid4().hex,
            "name": item.name,
            "source": item.source,
            "note": item.note,
            "overdue": bool(getattr(item, "overdue", False)),
        }
        document["drafts"].append(draft)
        added = True

    document["icloud_seen"] = sorted(seen)
    return added


def refresh_icloud_items(
    repo_root: Path, *, output_dir: Path, now: datetime | None = None
) -> dict:
    """Re-run the iCloud import against the stored Session and persist new items.

    Called once per process at startup, so events and reminders added to iCloud
    since the Session was created show up on the next restart.
    """

    document = load_session(repo_root, output_dir=output_dir, now=now)
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


def load_session(
    repo_root: Path, *, output_dir: Path, now: datetime | None = None
) -> dict:
    discard_past_plans(output_dir=output_dir, now=now)
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
    output_dir: Path,
    now: datetime | None,
    opener: Callable[[Request], object],
) -> dict:
    _apply_mutation(document, mutate)
    save_session(repo_root, document)
    return session_view(repo_root, output_dir=output_dir, now=now, opener=opener)


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


def _resolve_checklist(
    repo_root: Path,
    name: str,
    *,
    checklist: str | None | object,
    checklist_items: object,
    current_checklist: str | None | object = _UNSET,
    current_checklist_items: object = (),
) -> tuple[str | None, tuple[str, ...]]:
    """Resolve the (checklist, checklist_items) pair for a new or edited item.

    At most one of the two is ever non-empty. `current_checklist` is
    `_UNSET` for a brand-new item -- there's nothing yet to "re-attach away
    from" -- or the item's existing `checklist` value (possibly `None`) for
    an edit; `current_checklist_items` is that item's existing typed rows,
    used only to gate the auto-suggest fallback.

    For an edit, explicitly changing the checklist select to a different
    value (including clearing it) always wins outright, discarding whatever
    the rows editor holds, per the "re-attaching overwrites typed rows"
    rule (Undo recovers them, not a confirmation dialog).

    Otherwise: typed rows that exactly match the (explicitly selected, or
    already-attached) Library Checklist's current rows -- the untouched
    prefill from attaching it -- keep the item a reference. Any other
    non-blank typed rows win outright as literal, one-time rows (no Library
    lookup, no auto-suggest). With no rows at all, this falls back to the
    existing Library-reference resolution: the explicit checklist if one
    was given, otherwise the item's current checklist, otherwise an
    auto-suggestion from the name (only when the item has nothing at all).
    """

    if (
        current_checklist is not _UNSET
        and checklist is not _UNSET
        and checklist != current_checklist
    ):
        return checklist, ()  # type: ignore[return-value]

    if checklist_items is not _UNSET:
        cleaned = _clean_checklist_items(checklist_items)
        if cleaned:
            reference = (
                checklist
                if checklist is not _UNSET
                else (None if current_checklist is _UNSET else current_checklist)
            )
            if reference and _library_checklist_rows(repo_root, reference) == cleaned:  # type: ignore[arg-type]
                # Rows match the referenced Checklist's current rows
                # verbatim: nothing was actually edited (e.g. a plain
                # re-save, or the untouched prefill from attaching it), so
                # the reference stays attached.
                return reference, ()  # type: ignore[return-value]
            # The rows differ from what the referenced Checklist holds (or
            # there was no reference at all): go literal. One rule, no
            # provenance marker, no merge with the Library.
            return None, cleaned
        if checklist is _UNSET:
            # Rows were explicitly supplied but empty: an explicit "no
            # checklist" rather than "auto-suggest one from the name".
            return None, ()

    if checklist is not _UNSET:
        return checklist, ()  # type: ignore[return-value]

    if current_checklist is _UNSET:
        return suggest_checklist(name, load_checklist_library(repo_root / "data")), ()

    if not current_checklist and not current_checklist_items:
        return suggest_checklist(name, load_checklist_library(repo_root / "data")), ()

    return current_checklist, tuple(current_checklist_items)  # type: ignore[return-value]


def add_anchor(
    repo_root: Path,
    *,
    name: str,
    start: str,
    duration_minutes: int,
    checklist: str | None | object = _UNSET,
    checklist_items: object = _UNSET,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)
    attached, items = _resolve_checklist(
        repo_root, name, checklist=checklist, checklist_items=checklist_items
    )

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

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


def add_flex(
    repo_root: Path,
    *,
    name: str,
    duration_minutes: int,
    checklist: str | None | object = _UNSET,
    checklist_items: object = _UNSET,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)
    attached, items = _resolve_checklist(
        repo_root, name, checklist=checklist, checklist_items=checklist_items
    )

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

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


def insert_activity_template(
    repo_root: Path,
    *,
    activity_id: str,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    """Insert a single Activity Template into the Session as a new Anchor or Flex.

    Independent of Day Template state: usable at any point in the Session,
    not only when it is blank.
    """

    document = load_session(repo_root, output_dir=output_dir, now=now)
    library = load_activity_template_library(repo_root / "data")
    activity = library.get(activity_id)
    if activity is None:
        return session_view(repo_root, output_dir=output_dir, now=now, opener=opener)

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

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


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
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)

    def mutate(current: dict) -> None:
        current["drafts"].append({"id": uuid.uuid4().hex, "name": name})

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


def _new_todo(name: str, note: str = "") -> dict:
    return {"id": uuid.uuid4().hex, "name": name, "note": note}


def add_todo(
    repo_root: Path,
    *,
    name: str,
    note: str = "",
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)

    def mutate(current: dict) -> None:
        current["todos"].append(_new_todo(name, note))

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


def edit_todo(
    repo_root: Path,
    *,
    item_id: str,
    name: str | None = None,
    note: str | None = None,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    return edit_activity(
        repo_root,
        item_id=item_id,
        kind="todo",
        name=name,
        note=note,
        output_dir=output_dir,
        now=now,
        opener=opener,
    )


def drop_todo(
    repo_root: Path,
    *,
    item_id: str,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)

    def mutate(current: dict) -> None:
        _drop_keyed(current, "todos", item_id)

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


def convert_todo_to_flex(
    repo_root: Path,
    *,
    item_id: str,
    duration_minutes: int,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    return edit_activity(
        repo_root,
        item_id=item_id,
        kind="flex",
        duration_minutes=duration_minutes,
        output_dir=output_dir,
        now=now,
        opener=opener,
    )


def convert_todo_to_anchor(
    repo_root: Path,
    *,
    item_id: str,
    start: str,
    duration_minutes: int,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    return edit_activity(
        repo_root,
        item_id=item_id,
        kind="anchor",
        start=start,
        duration_minutes=duration_minutes,
        output_dir=output_dir,
        now=now,
        opener=opener,
    )


def convert_flex_to_todo(
    repo_root: Path,
    *,
    item_id: str,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    return edit_activity(
        repo_root,
        item_id=item_id,
        kind="todo",
        output_dir=output_dir,
        now=now,
        opener=opener,
    )


def _require_flex(current: dict, item_id: str) -> dict:
    return _item_by_id(current["flexes"], item_id)


def place_flex(
    repo_root: Path,
    *,
    item_id: str,
    start: str,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)

    def mutate(current: dict) -> None:
        _require_flex(current, item_id)["start"] = start

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


def change_flex_duration(
    repo_root: Path,
    *,
    item_id: str,
    duration_minutes: int,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)

    def mutate(current: dict) -> None:
        _require_flex(current, item_id)["duration_minutes"] = duration_minutes

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


def drop_flex(
    repo_root: Path,
    *,
    item_id: str,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)

    def mutate(current: dict) -> None:
        _drop_keyed(current, "flexes", item_id)

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


def drop_draft(
    repo_root: Path,
    *,
    item_id: str,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)

    def mutate(current: dict) -> None:
        _drop_keyed(current, "drafts", item_id)

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


def edit_draft(
    repo_root: Path,
    *,
    item_id: str,
    name: str,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)
    _item_by_id(document["drafts"], item_id)
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("Draft name cannot be blank.")

    def mutate(current: dict) -> None:
        draft = _item_by_id(current["drafts"], item_id)
        draft["name"] = trimmed

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


def promote_draft(
    repo_root: Path,
    *,
    item_id: str,
    kind: str,
    duration_minutes: int | None = None,
    start: str | None = None,
    name: str | None = None,
    checklist: str | None | object = _UNSET,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)
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

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


_ITEM_KIND_KEYS = {"anchor": "anchors", "flex": "flexes"}


def promote_checklist(
    repo_root: Path,
    *,
    item_id: str,
    item_kind: str,
    name: str,
    output_dir: Path,
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
    document = load_session(repo_root, output_dir=output_dir, now=now)
    item = _item_by_id(document[key], item_id)
    rows = list(item.get("checklist_items") or ())

    trimmed = name.strip()
    if not trimmed:
        raise ValueError("Checklist name cannot be blank.")

    save_checklist(repo_root, name=trimmed, items=rows)
    return session_view(repo_root, output_dir=output_dir, now=now, opener=opener)


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
        if seed.wake is not None:
            current["bounds"]["wake"] = parse_clock(seed.wake).strftime("%H:%M")
        if seed.sleep is not None:
            current["bounds"]["sleep"] = parse_clock(seed.sleep).strftime("%H:%M")
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
                "activity_template_id": anchor.activity_template_id,
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
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)
    activity_library = load_activity_template_library(repo_root / "data")
    seed = load_day_template(
        _default_day_template_file(repo_root, document), activity_library
    )
    if (
        seed is None
        or document["template_offer"] != "pending"
        or _session_has_items(document)
    ):
        return session_view(repo_root, output_dir=output_dir, now=now, opener=opener)

    return _commit(repo_root, document, _seed_mutation(seed), output_dir=output_dir, now=now, opener=opener)


def apply_named_day_template(
    repo_root: Path,
    *,
    template_id: str,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    """Manually seed the Session from a specific Day Template by id.

    Reuses the blank-Session-only guard used by the weekday auto-offer: a
    Day Template can only ever seed a blank Session, whether chosen
    automatically or picked by name.
    """

    document = load_session(repo_root, output_dir=output_dir, now=now)
    if _session_has_items(document):
        return session_view(repo_root, output_dir=output_dir, now=now, opener=opener)

    activity_library = load_activity_template_library(repo_root / "data")
    seed = load_day_template(
        named_day_template_path(repo_root / "data", template_id), activity_library
    )
    if seed is None:
        return session_view(repo_root, output_dir=output_dir, now=now, opener=opener)

    return _commit(repo_root, document, _seed_mutation(seed), output_dir=output_dir, now=now, opener=opener)


def template_mode_view(repo_root: Path, *, template_id: str | None) -> dict:
    """Return the shared planner's editable Day Template context.

    This deliberately reads the template directly rather than creating or
    loading the concrete Session, so editing a template cannot alter a plan
    that is already in progress.
    """

    defaults = load_defaults(repo_root / "data" / "defaults.toml")
    path = (
        named_day_template_path(repo_root / "data", template_id)
        if template_id
        else None
    )
    entries = load_day_template_entries(path) if path is not None else {
        "weekday": None,
        "wake": None,
        "sleep": None,
        "anchors": [],
        "flexes": [],
    }
    activity_library = load_activity_template_library(repo_root / "data")

    def present(raw: list[dict[str, object]], section: str) -> list[dict[str, object]]:
        result = []
        for source in raw:
            entry = dict(source)
            activity_id = entry.get("activity")
            if activity_id is None:
                matching_act = next(
                    (act for act in activity_library.values() if act.name.strip().lower() == str(entry.get("name", "")).strip().lower()),
                    None
                )
                if matching_act is not None and matching_act.daily:
                    entry["daily"] = True
                result.append(entry)
                continue
            activity = activity_library.get(str(activity_id))
            shape = str(entry.get("shape") or (
                "anchor" if activity is not None and activity.start is not None
                else "flex"
            ))
            entry["shape"] = shape
            if activity is None:
                entry.update({"broken": True, "name": entry.get("name") or f"Missing Activity Template: {activity_id}"})
            else:
                entry.setdefault("name", activity.name)
                entry.setdefault("checklist", activity.checklist)
                if shape == "anchor":
                    entry.setdefault("start", activity.start.strftime("%H:%M") if activity.start else None)
                    if "end" not in source and "duration" not in source and activity.end is not None:
                        entry.setdefault("end", activity.end)
                entry.setdefault("duration", int(activity.duration.total_seconds() // 60))
                entry["broken"] = False
                if activity.daily:
                    entry["daily"] = True
            entry["name_overridden"] = "name" in source
            entry["checklist_overridden"] = "checklist" in source
            entry["timing_overridden"] = any(key in source for key in ("start", "end", "duration"))
            entry["shape_overridden"] = "shape" in source
            entry["start_overridden"] = "start" in source
            result.append(entry)
        return result

    referenced_activity_ids = {
        str(entry.get("activity"))
        for entry in entries["anchors"] + entries["flexes"]
        if entry.get("activity")
    }
    referenced_names = {
        str(entry.get("name", "")).strip().lower()
        for entry in entries["anchors"] + entries["flexes"]
        if entry.get("name")
    }
    daily_activities = [
        {
            "id": activity_id,
            "name": activity.name,
            "duration_minutes": int(activity.duration.total_seconds() // 60),
            "checklist": activity.checklist,
            "daily": True,
        }
        for activity_id, activity in activity_library.items()
        if activity.daily
        and activity_id not in referenced_activity_ids
        and activity.name.strip().lower() not in referenced_names
    ]

    return {
        "mode": "template",
        "template_id": template_id,
        "name": load_day_template_name(path) if path is not None else "",
        "weekday": entries["weekday"],
        "bounds": {
            "wake": entries["wake"] or defaults.wake,
            "sleep": entries["sleep"] or defaults.sleep,
        },
        "anchors": present(entries["anchors"], "anchor"),
        "flexes": present(entries["flexes"], "flex"),
        "daily_activities": daily_activities,
        "activity_templates": _list_activity_templates(repo_root / "data"),
        "checklists": _list_checklists(repo_root / "data"),
        "saved": False,
    }


def save_template_mode(
    repo_root: Path,
    *,
    template_id: str | None,
    name: str,
    weekday: str | None,
    wake: str,
    sleep: str,
    anchors: list[dict[str, object]],
    flexes: list[dict[str, object]],
) -> dict:
    """Persist only reusable Day Template data and return template mode.

    Template-mode entries are copied at this boundary so a caller can safely
    pass data derived from an open concrete Session without handing mutable
    Session records to the library writer. Concrete Session and Plan storage
    is intentionally not touched here; applying a template remains an
    explicit operation.
    """

    if not name.strip():
        raise ValueError("Day Template name cannot be blank.")

    def literal_entry(entry: dict[str, object], *, flex: bool) -> dict[str, object]:
        """Translate the shared planner's fields to the template file shape."""

        if "activity" in entry:
            cleaned = {
                key: value
                for key, value in entry.items()
                if key in {
                    "activity", "shape", "name", "start", "end", "duration",
                    "duration_minutes", "checklist",
                }
                and value is not None
            }
            for key, flag in (
                ("name", "name_overridden"),
                ("checklist", "checklist_overridden"),
                ("start", "start_overridden"),
                ("shape", "shape_overridden"),
            ):
                if not entry.get(flag, key in entry):
                    cleaned.pop(key, None)
            if not entry.get("timing_overridden", any(
                key in entry for key in ("start", "end", "duration", "duration_minutes")
            )):
                for key in ("start", "end", "duration", "duration_minutes"):
                    cleaned.pop(key, None)
            if "end" in cleaned:
                cleaned.pop("duration", None)
                cleaned.pop("duration_minutes", None)
            return cleaned | (
                {"duration": entry["duration_minutes"]}
                if "duration_minutes" in entry
                else {}
            )
        result = {
            key: value
            for key, value in entry.items()
            if key in {"name", "start", "end", "duration", "checklist"}
        }
        if "duration_minutes" in entry:
            result["duration"] = entry["duration_minutes"]
        return result

    template_anchors = [literal_entry(entry, flex=False) for entry in anchors]
    template_flexes = [literal_entry(entry, flex=True) for entry in flexes]
    saved_id = save_day_template(
        repo_root,
        id=template_id,
        name=name.strip(),
        weekday=weekday or None,
        wake=wake,
        sleep=sleep,
        anchors=template_anchors,
        flexes=template_flexes,
    )
    result = template_mode_view(repo_root, template_id=saved_id)
    result["saved"] = True
    return result


def decline_template(
    repo_root: Path,
    *,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)
    if document["template_offer"] != "pending":
        return session_view(repo_root, output_dir=output_dir, now=now, opener=opener)

    def mutate(current: dict) -> None:
        current["template_offer"] = "declined"

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


def _apply_item_checklist(
    repo_root: Path,
    item: dict,
    *,
    name: str,
    checklist: object,
    checklist_items: object = _UNSET,
) -> None:
    checklist_value, checklist_items_value = _resolve_checklist(
        repo_root,
        name,
        checklist=checklist,
        checklist_items=checklist_items,
        current_checklist=item.get("checklist"),
        current_checklist_items=item.get("checklist_items") or (),
    )
    item["checklist"] = checklist_value
    item["checklist_items"] = list(checklist_items_value)


def edit_activity(
    repo_root: Path,
    *,
    item_id: str,
    kind: str,
    name: str | None = None,
    start: str | None = None,
    duration_minutes: int | None = None,
    checklist: str | None | object = _UNSET,
    checklist_items: object = _UNSET,
    note: str | None = None,
    remove: bool = False,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)

    def mutate(current: dict) -> None:
        source_kind = None
        source_index = -1
        source_list = None
        item = None

        for i, a in enumerate(current.get("anchors", [])):
            if a.get("id") == item_id:
                source_kind = "anchor"
                source_index = i
                source_list = current["anchors"]
                item = a
                break

        if item is None:
            for i, f in enumerate(current.get("flexes", [])):
                if f.get("id") == item_id:
                    source_kind = "flex"
                    source_index = i
                    source_list = current["flexes"]
                    item = f
                    break

        if item is None:
            for i, t in enumerate(current.get("todos", [])):
                if t.get("id") == item_id:
                    source_kind = "todo"
                    source_index = i
                    source_list = current["todos"]
                    item = t
                    break

        if item is None or source_list is None:
            raise KeyError(item_id)

        if remove:
            source_list.pop(source_index)
            return

        if kind not in ("anchor", "flex", "todo"):
            raise ValueError(f"Unknown activity kind: {kind}")

        new_name = name if name is not None and name.strip() != "" else item["name"]

        if kind == source_kind:
            if name is not None:
                item["name"] = name
            if kind == "anchor":
                if start is not None:
                    item["start"] = start
                if duration_minutes is not None:
                    item["duration_minutes"] = duration_minutes
                _apply_item_checklist(
                    repo_root,
                    item,
                    name=item["name"],
                    checklist=checklist,
                    checklist_items=checklist_items,
                )
            elif kind == "flex":
                if duration_minutes is not None:
                    item["duration_minutes"] = duration_minutes
                if start is not None:
                    item["start"] = start
                _apply_item_checklist(
                    repo_root,
                    item,
                    name=item["name"],
                    checklist=checklist,
                    checklist_items=checklist_items,
                )
            elif kind == "todo":
                if note is not None:
                    item["note"] = note
            return

        # Type conversion
        source_list.pop(source_index)
        source = item.get("source")
        if source == "daily":
            source = None

        activity_template_id = item.get("activity_template_id")

        if kind == "anchor":
            if start is not None and str(start).strip() != "":
                final_start = start
            elif source_kind == "flex":
                final_start = item.get("start")
                if not final_start:
                    raise ValueError("Start time is required for Anchor")
            elif source_kind == "todo":
                final_start = "09:00"
            else:
                final_start = item.get("start") or "09:00"

            if duration_minutes is not None:
                final_duration = duration_minutes
            elif "duration_minutes" in item:
                final_duration = item["duration_minutes"]
            else:
                final_duration = 30

            new_anchor = {
                "id": item_id,
                "name": new_name,
                "start": final_start,
                "duration_minutes": final_duration,
                "checklist": item.get("checklist"),
                "checklist_items": list(item.get("checklist_items") or []),
            }
            if source:
                new_anchor["source"] = source
            if activity_template_id:
                new_anchor["activity_template_id"] = activity_template_id

            _apply_item_checklist(
                repo_root,
                new_anchor,
                name=new_name,
                checklist=checklist,
                checklist_items=checklist_items,
            )
            current.setdefault("anchors", []).append(new_anchor)

        elif kind == "flex":
            if duration_minutes is not None:
                final_duration = duration_minutes
            elif "duration_minutes" in item:
                final_duration = item["duration_minutes"]
            else:
                final_duration = 30

            if start is not None and str(start).strip() != "":
                final_start = start
            elif source_kind == "anchor":
                final_start = item.get("start")
            elif source_kind == "todo":
                final_start = None
            else:
                final_start = item.get("start")

            new_flex = {
                "id": item_id,
                "name": new_name,
                "duration_minutes": final_duration,
                "start": final_start,
                "checklist": item.get("checklist"),
                "checklist_items": list(item.get("checklist_items") or []),
            }
            if source:
                new_flex["source"] = source
            if activity_template_id:
                new_flex["activity_template_id"] = activity_template_id

            _apply_item_checklist(
                repo_root,
                new_flex,
                name=new_name,
                checklist=checklist,
                checklist_items=checklist_items,
            )
            current.setdefault("flexes", []).append(new_flex)

        elif kind == "todo":
            new_todo = {
                "id": item_id,
                "name": new_name,
                "note": note if note is not None else "",
            }
            if source:
                new_todo["source"] = source
            current.setdefault("todos", []).append(new_todo)

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


def edit_flex(
    repo_root: Path,
    *,
    item_id: str,
    name: str | None = None,
    duration_minutes: int | None = None,
    checklist: str | None | object = _UNSET,
    checklist_items: object = _UNSET,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    return edit_activity(
        repo_root,
        item_id=item_id,
        kind="flex",
        name=name,
        duration_minutes=duration_minutes,
        checklist=checklist,
        checklist_items=checklist_items,
        output_dir=output_dir,
        now=now,
        opener=opener,
    )


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
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    return edit_activity(
        repo_root,
        item_id=item_id,
        kind="anchor",
        name=name,
        start=start,
        duration_minutes=duration_minutes,
        checklist=checklist,
        checklist_items=checklist_items,
        remove=remove,
        output_dir=output_dir,
        now=now,
        opener=opener,
    )


def edit_bounds(
    repo_root: Path,
    *,
    wake: str | None = None,
    sleep: str | None = None,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)

    def mutate(current: dict) -> None:
        final_wake = parse_clock(wake or current["bounds"]["wake"])
        final_sleep = parse_clock(sleep or current["bounds"]["sleep"])
        day_length = minutes_since_wake(final_sleep, wake=final_wake)

        # Work on a copy until every scheduled item has a valid repair.  This
        # keeps an edit atomic when an item is longer than the final day.
        repaired_anchors = copy.deepcopy(current["anchors"])
        repaired_flexes = copy.deepcopy(current["flexes"])
        current_wake = parse_clock(current["bounds"]["wake"])
        final_wraps_midnight = (
            minutes_since_midnight(final_sleep)
            <= minutes_since_midnight(final_wake)
        )
        scheduled = [
            {"kind": "Anchor", "item": item} for item in repaired_anchors
        ] + [
            {"kind": "Flex", "item": item}
            for item in repaired_flexes
            if item.get("start")
        ]

        if day_length == 0:
            # Keep the existing live zero-length-day blocker behavior.
            current["bounds"]["wake"] = wake or current["bounds"]["wake"]
            current["bounds"]["sleep"] = sleep or current["bounds"]["sleep"]
            return

        def clock_at(offset: int) -> str:
            value = datetime.combine(date(2000, 1, 1), final_wake) + timedelta(
                minutes=offset
            )
            return value.strftime("%H:%M")

        for entry in scheduled:
            item = entry["item"]
            start = parse_clock(item["start"])
            # Keep every activity in the same wake-relative coordinate system,
            # including activities that were already outside the old bounds.
            # A pre-wake clock value is negative only for a non-wrapping day;
            # on an overnight day it is the following morning.
            if final_wraps_midnight:
                entry["offset"] = minutes_since_wake(start, wake=final_wake)
            else:
                entry["offset"] = (
                    minutes_since_midnight(start)
                    - minutes_since_midnight(final_wake)
                )
                if (
                    final_wake > current_wake
                    and current_wake < start < final_wake
                ):
                    entry["offset"] = (
                        minutes_since_midnight(start)
                        - minutes_since_midnight(current_wake)
                    )
            entry["duration"] = int(item["duration_minutes"])

            if (
                entry["offset"] < 0
                and entry["offset"] + entry["duration"] > day_length
            ):
                raise ValueError(
                    f"{entry['kind']} '{item['name']}' crosses both final day bounds "
                    "and cannot be repaired without changing its duration."
                )

        def overlaps(
            first: dict, first_shift: int, second: dict, second_shift: int
        ) -> bool:
            first_start = first["offset"] + first_shift
            second_start = second["offset"] + second_shift
            return (
                first_start < second_start + second["duration"]
                and second_start < first_start + first["duration"]
            )

        def repair_groups(
            seed_indices: list[int], *, side: str
        ) -> list[tuple[set[int], int]]:
            groups: list[tuple[set[int], int]] = []
            remaining = set(seed_indices)
            while remaining:
                group = {remaining.pop()}
                while True:
                    shift = (
                        -min(scheduled[index]["offset"] for index in group)
                        if side == "wake"
                        else day_length
                        - max(
                            scheduled[index]["offset"] + scheduled[index]["duration"]
                            for index in group
                        )
                    )
                    connected = {
                        index
                        for index in range(len(scheduled))
                        if index not in group
                        and any(
                            overlaps(scheduled[group_index], shift, scheduled[index], 0)
                            for group_index in group
                        )
                    }
                    if not connected:
                        break
                    group.update(connected)
                    remaining.difference_update(connected)
                groups.append((group, shift))
            return groups

        wake_seeds = [
            index
            for index, entry in enumerate(scheduled)
            if entry["offset"] < 0
        ]
        sleep_seeds = [
            index
            for index, entry in enumerate(scheduled)
            if entry["offset"] + entry["duration"] > day_length
        ]
        if set(wake_seeds) & set(sleep_seeds):
            entry = scheduled[next(iter(set(wake_seeds) & set(sleep_seeds)))]
            raise ValueError(
                f"{entry['kind']} '{entry['item']['name']}' crosses both final day bounds "
                "and cannot be repaired without changing its duration."
            )

        groups = repair_groups(wake_seeds, side="wake") + repair_groups(
            sleep_seeds, side="sleep"
        )
        shifts = {index: 0 for index in range(len(scheduled))}
        for group, shift in groups:
            for index in group:
                shifts[index] = shift
        for index, entry in enumerate(scheduled):
            final_offset = entry["offset"] + shifts[index]
            if final_offset < 0 or final_offset + entry["duration"] > day_length:
                raise ValueError(
                    f"{entry['kind']} '{entry['item']['name']}' cannot fit within "
                    "the final day bounds without changing its duration."
                )
            entry["item"]["start"] = clock_at(final_offset)
        current["bounds"]["wake"] = wake or current["bounds"]["wake"]
        current["bounds"]["sleep"] = sleep or current["bounds"]["sleep"]
        current["anchors"] = repaired_anchors
        current["flexes"] = repaired_flexes

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


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
            activity_template_id=item.get("activity_template_id"),
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


# The reminder default duration when a name gives neither a range nor a
# duration. Mirrored in tomorrow/static/session.html's `sheetPromote` (the
# Promote sheet's own fallback when a Draft has no parsed suggestion at
# all); keep the two in sync if this ever changes.
DEFAULT_SUGGESTED_DURATION_MINUTES = 30


def _suggested_span_minutes(parsed: NameTimeResult) -> int:
    """The span (in minutes) a parsed name-time suggestion should be tested
    against for a clash: a range's real length, else a bare duration parsed
    alongside a start, else the default reminder duration.
    """

    if parsed.end is not None:
        return minutes_between(parse_clock(parsed.start), parse_clock(parsed.end))
    if parsed.duration_minutes is not None:
        return parsed.duration_minutes
    return DEFAULT_SUGGESTED_DURATION_MINUTES


def _clashing_anchor(
    parsed: NameTimeResult, anchors: Sequence[Anchor], *, wake: time
) -> Anchor | None:
    """The Anchor (if any) a suggested start would overlap.

    Tested against Anchors only -- a placed Flex occupies real time too but
    can be moved, and letting it suppress a good suggestion would be wrong.
    """

    if parsed.start is None:
        return None
    span_minutes = _suggested_span_minutes(parsed)
    start_minutes = minutes_since_wake(parse_clock(parsed.start), wake=wake)
    end_minutes = start_minutes + span_minutes
    for anchor in anchors:
        anchor_start = minutes_since_wake(anchor.start, wake=wake)
        anchor_end = anchor_start + int(anchor.duration.total_seconds() // 60)
        if start_minutes < anchor_end and end_minutes > anchor_start:
            return anchor
    return None


def _draft_view(item: dict, *, anchors: Sequence[Anchor], wake: time) -> dict:
    """Shape a raw Draft for the frontend: drop `checklist`, add the parsed name/time.

    The Draft's own `name` is left untouched (the tray always shows the
    full original name). The parse result is shipped alongside it under
    `stripped_name` (used for Anchor/Flex), `suggested_start` (absent
    when no time was found, or when a clash withholds it), `suggested_end`
    (absent unless a valid range was found), and
    `suggested_duration_minutes` (absent when no duration was found), so
    the Promote sheet can pre-fill without any parsing in the browser.

    Also ships `default_kind` ("anchor" or "flex"), the kind the Promote
    sheet should open on: a parsed start or range defaults to anchor (even
    when a clash withholds the start itself -- the name still describes a
    fixed commitment); a duration with no start, or nothing detected at
    all, defaults to flex. This is decided here so the browser doesn't
    re-derive it.

    When the suggested start would overlap an existing Anchor, it is
    withheld (`suggested_start` is None) and a `clash_caption` key is added
    naming the clashing Anchor and its span, worded exactly like a Submit
    blocker (`describe_blocker` is reused against a synthetic
    `AnchorOverlapBlocker` built from the candidate). This decision is made
    once, here, and is not re-evaluated as the Start field is edited.
    """

    view = {key: value for key, value in item.items() if key != "checklist"}
    parsed = parse_name_time(item["name"])
    view["stripped_name"] = parsed.stripped_name
    view["suggested_end"] = parsed.end
    view["suggested_duration_minutes"] = parsed.duration_minutes
    view["default_kind"] = "anchor" if parsed.start is not None else "flex"

    clashing = _clashing_anchor(parsed, anchors, wake=wake)
    if clashing is not None:
        candidate = Anchor(
            name=parsed.stripped_name,
            start=parse_clock(parsed.start),
            duration=timedelta(minutes=_suggested_span_minutes(parsed)),
        )
        view["suggested_start"] = None
        view["clash_caption"] = describe_blocker(
            AnchorOverlapBlocker(first=candidate, second=clashing)
        )
    else:
        view["suggested_start"] = parsed.start
    return view


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
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)
    bounds, drafts, anchors, flexes, todos = _unpack(document)
    result = finalize_plan(
        bounds=bounds, drafts=drafts, anchors=anchors, flexes=flexes, todos=todos
    )
    desktop_conflict = describe_foreign_plan_file(output_dir=output_dir)
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
    weather_forecast = try_fetch_weather_forecast(
        data_dir, plan_date, bounds=bounds, opener=opener
    )
    if weather_forecast is not None:
        document["weather"] = weather_forecast
        save_session(repo_root, document)
    else:
        weather_forecast = document.get("weather")

    weather_one_liner = (
        format_weather_one_liner(
            low_c=weather_forecast["low_c"],
            high_c=weather_forecast["high_c"],
            weather_code=weather_forecast["weather_code"],
        )
        if weather_forecast is not None
        else None
    )
    weather_name = (
        weather_forecast.get("location_name")
        if weather_forecast
        else load_weather_name(data_dir)
    )

    return {
        "plan_date": document["plan_date"],
        "plan_date_label": format_plan_date(plan_date),
        "bounds": bounds_view,
        "template_offer": document["template_offer"],
        "show_template_offer": _show_template_offer(repo_root, document),
        "drafts": [
            _draft_view(item, anchors=anchors, wake=wake_time)
            for item in document["drafts"]
        ],
        "anchors": [_with_checklist_kind(item) for item in document["anchors"]],
        "flexes": [_with_checklist_kind(item) for item in document["flexes"]],
        "todos": document.get("todos", []),
        "gaps": gaps,
        "blockers": [describe_blocker(blocker) for blocker in result.blockers]
        + ([desktop_conflict] if desktop_conflict else []),
        "can_undo": bool(undo.get("past")),
        "can_redo": bool(undo.get("future")),
        "weather": weather_forecast,
        "weather_name": weather_name,
        "weather_one_liner": weather_one_liner,
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
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)
    undo = document.get("undo", {"past": [], "future": []})
    past = list(undo.get("past", []))
    if not past:
        return session_view(repo_root, output_dir=output_dir, now=now, opener=opener)
    future = list(undo.get("future", []))
    snapshot = past.pop()
    future.append(_snapshot_without_undo(document))
    restored = copy.deepcopy(snapshot)
    restored["undo"] = {"past": past, "future": future}
    save_session(repo_root, restored)
    return session_view(repo_root, output_dir=output_dir, now=now, opener=opener)


def redo_session(
    repo_root: Path,
    *,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)
    undo = document.get("undo", {"past": [], "future": []})
    future = list(undo.get("future", []))
    if not future:
        return session_view(repo_root, output_dir=output_dir, now=now, opener=opener)
    past = list(undo.get("past", []))
    snapshot = future.pop()
    past.append(_snapshot_without_undo(document))
    restored = copy.deepcopy(snapshot)
    restored["undo"] = {"past": past[-20:], "future": future}
    save_session(repo_root, restored)
    return session_view(repo_root, output_dir=output_dir, now=now, opener=opener)


def reset_session(
    repo_root: Path,
    *,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> dict:
    document = load_session(repo_root, output_dir=output_dir, now=now)
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

    return _commit(repo_root, document, mutate, output_dir=output_dir, now=now, opener=opener)


def submit_session(
    repo_root: Path,
    *,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
) -> Path:
    ensure_plan_file_not_foreign(output_dir=output_dir)
    document = load_session(repo_root, output_dir=output_dir, now=now)
    result = _finalize_document(document)
    if not result.ok:
        raise PlanBlockedError(result.blockers)
    assert result.plan is not None
    plan_date = date.fromisoformat(document["plan_date"])
    bounds = DayBounds(wake=document["bounds"]["wake"], sleep=document["bounds"]["sleep"])
    try:
        fresh_weather = try_fetch_weather_forecast(
            repo_root / "data", plan_date, bounds=bounds, opener=opener
        )
    except Exception:
        fresh_weather = None
    if fresh_weather is not None:
        weather = fresh_weather
        document["weather"] = fresh_weather
        save_session(repo_root, document)
    else:
        weather = document.get("weather")
    return write_finalized_plan(
        repo_root=repo_root,
        output_dir=output_dir,
        plan_date=plan_date,
        plan=result.plan,
        weather=weather,
    )


def _list_checklists(data_dir: Path) -> list[dict]:
    return [
        {"id": checklist_id, "name": checklist.name, "items": list(checklist.items)}
        for checklist_id, checklist in load_checklist_library(data_dir).items()
    ]


def _list_activity_templates(data_dir: Path) -> list[dict]:
    return [
        {
            "id": activity_id,
            "name": activity.name,
            "is_anchor_shaped": activity.start is not None,
            "daily": activity.daily,
            "start": activity.start.strftime("%H:%M") if activity.start is not None else None,
            "end": activity.end,
            "duration_minutes": (
                None if activity.end is not None else int(activity.duration.total_seconds() // 60)
            ),
            "checklist": activity.checklist,
        }
        for activity_id, activity in load_activity_template_library(data_dir).items()
    ]


def _list_day_templates(data_dir: Path) -> list[dict]:
    templates_dir = data_dir / "templates"
    paths = [
        templates_dir / f"{template_id}.toml"
        for template_id in day_template_order(templates_dir)
    ]
    return [
        {
            "id": path.stem,
            "name": load_day_template_name(path),
            **load_day_template_entries(path),
        }
        for path in paths
    ]



def bind_session_server(
    repo_root: Path,
    *,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
    host: str = SESSION_HOST,
    port: int = SESSION_PORT,
):
    """Create the browser-facing server for the current Session."""
    from tomorrow.session_http import bind_session_server as bind_http_server

    return bind_http_server(
        repo_root, output_dir=output_dir, now=now, opener=opener, host=host, port=port
    )


def run_session(
    repo_root: Path,
    *,
    output_dir: Path,
    now: datetime | None = None,
    opener: Callable[[Request], object] = _default_opener,
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
    opener: Callable[[Request], object] = _default_opener,
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
