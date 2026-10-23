"""In-app CRUD, template loading, validation, and seeding for the Library subsystem.

Consolidates Checklist, Activity Template, and Day Template storage, TOML
serialization, slug derivation, uniqueness validation, suggestion/autocomplete
matching, and Day Template seeding into a single deep module.

Every entry is identified by its name: two entries of the same kind may not
share a name once letter case and punctuation are ignored (see `normalize`).
An entry's filename (its id) is derived from its name once, on create, via
`_slugify` (with a numeric suffix if that slug is already taken); renaming
an entry never renames its file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
import json
from pathlib import Path
from typing import Callable, Mapping, Sequence, TypeVar
import tomllib

from tomorrow.domain import Anchor, Flex, minutes_from_bound, parse_clock

T = TypeVar("T")


@dataclass(frozen=True)
class Checklist:
    """A reusable named list of things to bring or do."""

    name: str
    items: tuple[str, ...]


@dataclass(frozen=True)
class ActivityTemplate:
    """A single reusable Anchor-shaped or Flex-shaped item."""

    name: str
    duration: timedelta
    start: time | None = None
    checklist: str | None = None
    daily: bool = False
    # Raw "HH:MM" end time as typed, when saved with an end rather than a
    # duration; `duration` above is always the resolved value either way.
    end: str | None = None


@dataclass(frozen=True)
class TemplateSeed:
    """Anchors and unplaced Flex copied from a Day Template."""

    anchors: tuple[Anchor, ...]
    flexes: tuple[Flex, ...]
    wake: str | None = None
    sleep: str | None = None


# --- Directory Path Resolution -----------------------------------------------


def _resolve_data_dir(data_dir_or_repo_root: Path) -> Path:
    if data_dir_or_repo_root.name == "data":
        return data_dir_or_repo_root
    if (
        (data_dir_or_repo_root / "checklists").is_dir()
        or (data_dir_or_repo_root / "activity-templates").is_dir()
        or (data_dir_or_repo_root / "templates").is_dir()
    ):
        return data_dir_or_repo_root
    return data_dir_or_repo_root / "data"


def checklists_dir(data_dir_or_repo_root: Path) -> Path:
    return _resolve_data_dir(data_dir_or_repo_root) / "checklists"


def activity_templates_dir(data_dir_or_repo_root: Path) -> Path:
    return _resolve_data_dir(data_dir_or_repo_root) / "activity-templates"


def day_templates_dir(data_dir_or_repo_root: Path) -> Path:
    return _resolve_data_dir(data_dir_or_repo_root) / "templates"


def day_template_path(data_dir_or_repo_root: Path, plan_date: date) -> Path:
    weekday = plan_date.strftime("%A").lower()
    return day_templates_dir(data_dir_or_repo_root) / f"{weekday}.toml"


def default_day_template_path(data_dir_or_repo_root: Path, plan_date: date) -> Path:
    """Return the Day Template file that is the default for `plan_date`'s weekday.

    Scans for a Day Template whose `weekday` field names this weekday; falls
    back to the legacy `<weekday>.toml` filename convention for backward
    compatibility with hand-authored files that predate the `weekday` field.
    """
    weekday = plan_date.strftime("%A").lower()
    directory = day_templates_dir(data_dir_or_repo_root)
    legacy_path = directory / f"{weekday}.toml"
    if directory.is_dir():
        for path in sorted(directory.glob("*.toml")):
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except (tomllib.TOMLDecodeError, OSError):
                continue
            if data.get("weekday") == weekday:
                return path
    return legacy_path


def named_day_template_path(data_dir_or_repo_root: Path, template_id: str) -> Path:
    return day_templates_dir(data_dir_or_repo_root) / f"{template_id}.toml"


# --- Normalization & Serialization Helpers -----------------------------------


def normalize(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _load_toml_library(directory: Path, parse: Callable[[Path], T]) -> dict[str, T]:
    """Load every *.toml file in `directory`, keyed by filename stem."""
    if not directory.is_dir():
        return {}
    return {path.stem: parse(path) for path in sorted(directory.glob("*.toml"))}


def _slugify(name: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in name.strip().lower())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "untitled"


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _write_toml_lines(directory: Path, slug: str, lines: list[str]) -> None:
    """Create `directory` if needed and write `lines` to `directory/{slug}.toml`."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{slug}.toml").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _read_name(path: Path) -> str | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return None
    name = data.get("name")
    return str(name) if name is not None else None


def _check_name_available(directory: Path, kind: str, name: str, *, exclude_id: str | None) -> None:
    """Raise if another entry of this kind already has `name`, ignoring case/punctuation."""
    if not directory.is_dir():
        return
    target = normalize(name)
    for path in sorted(directory.glob("*.toml")):
        if exclude_id is not None and path.stem == exclude_id:
            continue
        existing_name = _read_name(path)
        if existing_name is not None and normalize(existing_name) == target:
            raise ValueError(
                f'A {kind} named "{existing_name}" already exists. Use Edit instead.'
            )


def _unique_slug(directory: Path, name: str) -> str:
    base = _slugify(name)
    slug = base
    suffix = 2
    while directory.is_dir() and (directory / f"{slug}.toml").exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _resolve_slug(directory: Path, kind: str, *, id: str | None, name: str) -> str:
    """Create-vs-update dance shared by all three save functions.

    Validates name uniqueness (excluding the entry's own current id on
    update) and returns the filename slug to write to.
    """
    if id is None:
        _check_name_available(directory, kind, name, exclude_id=None)
        return _unique_slug(directory, name)
    if not (directory / f"{id}.toml").exists():
        raise ValueError(f'No {kind} with id "{id}" exists.')
    _check_name_available(directory, kind, name, exclude_id=id)
    return id


def suggest_by_name(
    item_name: str, library: dict[str, T], *, name_of: Callable[[T], str]
) -> str | None:
    """Return the single library key whose id or name resembles `item_name`, if unambiguous."""
    needle = normalize(item_name)
    if not needle:
        return None

    matches: list[str] = []
    for key, entry in library.items():
        candidates = (normalize(key), normalize(name_of(entry)))
        if any(needle in candidate or candidate in needle for candidate in candidates if candidate):
            matches.append(key)

    if len(matches) == 1:
        return matches[0]
    return None


# --- Checklists -------------------------------------------------------------


def _parse_checklist(path: Path) -> Checklist:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    items = tuple(str(item) for item in data.get("items", ()))
    return Checklist(name=str(data["name"]), items=items)


def load_checklist_library(data_dir_or_repo_root: Path) -> dict[str, Checklist]:
    """Load every *.toml file in data/checklists/, keyed by filename stem."""
    return _load_toml_library(checklists_dir(data_dir_or_repo_root), _parse_checklist)


def suggest_checklist(item_name: str, library: dict[str, Checklist]) -> str | None:
    """Return a library key when the item name resembles a Checklist id or name."""
    return suggest_by_name(item_name, library, name_of=lambda checklist: checklist.name)


def list_checklists(data_dir_or_repo_root: Path) -> list[dict]:
    return [
        {"id": checklist_id, "name": checklist.name, "items": list(checklist.items)}
        for checklist_id, checklist in load_checklist_library(data_dir_or_repo_root).items()
    ]


def save_checklist(
    repo_root: Path, *, id: str | None = None, name: str, items: list[str]
) -> str:
    """Create (id=None) or update (existing id) a Checklist TOML file."""
    directory = checklists_dir(repo_root)
    slug = _resolve_slug(directory, "Checklist", id=id, name=name)

    lines = [f"name = {_toml_string(name)}"]
    items_repr = ", ".join(_toml_string(item) for item in items)
    lines.append(f"items = [{items_repr}]")
    _write_toml_lines(directory, slug, lines)
    return slug


def delete_checklist(repo_root: Path, *, checklist_id: str) -> None:
    path = checklists_dir(repo_root) / f"{checklist_id}.toml"
    path.unlink(missing_ok=True)


# --- Activity Templates -----------------------------------------------------


def _parse_activity_template(path: Path) -> ActivityTemplate:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    start_value = data.get("start")
    start = parse_clock(str(start_value)) if start_value is not None else None
    end_value = data.get("end")
    if end_value is not None:
        assert start is not None
        duration = timedelta(minutes=minutes_from_bound(start, parse_clock(str(end_value))))
    else:
        duration = timedelta(minutes=int(data["duration"]))
    checklist = data.get("checklist")
    return ActivityTemplate(
        name=str(data["name"]),
        duration=duration,
        start=start,
        checklist=str(checklist) if checklist is not None else None,
        daily=bool(data.get("daily", False)),
        end=str(end_value) if end_value is not None else None,
    )


def load_activity_template_library(data_dir_or_repo_root: Path) -> dict[str, ActivityTemplate]:
    """Load every *.toml file in data/activity-templates/, keyed by filename stem."""
    return _load_toml_library(activity_templates_dir(data_dir_or_repo_root), _parse_activity_template)


def suggest_activity_template(
    item_name: str, library: dict[str, ActivityTemplate]
) -> str | None:
    """Return a library key when the item name resembles an Activity Template id or name."""
    return suggest_by_name(item_name, library, name_of=lambda template: template.name)


def list_activity_templates(data_dir_or_repo_root: Path) -> list[dict]:
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
        for activity_id, activity in load_activity_template_library(data_dir_or_repo_root).items()
    ]


def save_activity_template(
    repo_root: Path,
    *,
    id: str | None = None,
    name: str,
    duration_minutes: int | None = None,
    start: str | None = None,
    end: str | None = None,
    checklist: str | None = None,
    daily: bool = False,
) -> str:
    """Create (id=None) or update (existing id) an Activity Template.

    Anchor-shaped (start given) entries take exactly one of duration_minutes
    or end. Flex-shaped entries (no start) always take duration_minutes and
    never take end. A Daily Activity cannot have a fixed start.
    """
    if daily and start is not None:
        raise ValueError("A Daily Activity cannot have a fixed start.")

    if start is not None:
        if (duration_minutes is None) == (end is None):
            raise ValueError("Give either a duration or an end time, not both or neither.")
        if end is not None:
            minutes_from_bound(parse_clock(start), parse_clock(end))
    else:
        if end is not None:
            raise ValueError("Only an Anchor-shaped Activity Template can have an end time.")
        if duration_minutes is None:
            raise ValueError("Duration is required.")

    directory = activity_templates_dir(repo_root)
    slug = _resolve_slug(directory, "Activity Template", id=id, name=name)

    lines = [f"name = {_toml_string(name)}"]
    if start is not None:
        lines.append(f"start = {_toml_string(start)}")
        if end is not None:
            lines.append(f"end = {_toml_string(end)}")
        else:
            lines.append(f"duration = {int(duration_minutes)}")  # type: ignore[arg-type]
    else:
        lines.append(f"duration = {int(duration_minutes)}")  # type: ignore[arg-type]
    if checklist is not None:
        lines.append(f"checklist = {_toml_string(checklist)}")
    if daily:
        lines.append("daily = true")
    _write_toml_lines(directory, slug, lines)
    return slug


def delete_activity_template(repo_root: Path, *, activity_id: str) -> None:
    path = activity_templates_dir(repo_root) / f"{activity_id}.toml"
    path.unlink(missing_ok=True)


# --- Day Templates -----------------------------------------------------------


def _unassign_other_weekday_owners(directory: Path, weekday: str, keep: str) -> None:
    for path in directory.glob("*.toml"):
        if path.stem == keep:
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            continue
        if data.get("weekday") == weekday:
            lines = [
                line for line in path.read_text(encoding="utf-8").splitlines()
                if not line.startswith("weekday")
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validate_anchor_entry(
    entry: dict[str, object],
    activity_library: dict[str, object] | None = None,
) -> None:
    if "activity" in entry:
        shape = entry.get("shape")
        if shape is not None and shape not in {"anchor", "flex"}:
            raise ValueError("Activity Template shape must be Anchor or Flex.")
        if shape == "flex":
            _validate_flex_entry({**entry, "name": entry.get("name", "reference"), "duration": entry.get("duration", 1)})
            return
        activity = (activity_library or {}).get(str(entry["activity"]))
        if (
            entry.get("start") is None
            and entry.get("shape") == "anchor"
            and getattr(activity, "start", None) is None
        ):
            raise ValueError("An Anchor-shaped Activity Template requires a start time.")
        return
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("A Day Template entry requires a non-blank name.")
    start = entry.get("start")
    if start is None:
        raise ValueError("A Day Template Anchor entry requires a start time.")
    try:
        start_time = parse_clock(str(start))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid Anchor start time: {start!r}.") from exc
    duration = entry.get("duration")
    end = entry.get("end")
    if (duration is None) == (end is None):
        raise ValueError("Give either a duration or an end time, not both or neither.")
    if duration is not None:
        try:
            if int(duration) <= 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError("A Day Template Anchor duration must be a positive number.") from exc
    if end is not None:
        try:
            minutes_from_bound(start_time, parse_clock(str(end)))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid Anchor end time: {end!r}.") from exc


def _validate_flex_entry(
    entry: dict[str, object],
    activity_library: dict[str, object] | None = None,
) -> None:
    if "activity" in entry:
        shape = entry.get("shape")
        if shape is not None and shape not in {"anchor", "flex"}:
            raise ValueError("Activity Template shape must be Anchor or Flex.")
        if shape == "anchor":
            _validate_anchor_entry(
                {**entry, "name": entry.get("name", "reference")},
                activity_library,
            )
        return
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("A Day Template entry requires a non-blank name.")
    if entry.get("start") is not None or entry.get("end") is not None:
        raise ValueError("A Day Template Flex entry cannot have a start or end time.")
    duration = entry.get("duration")
    try:
        if duration is None or int(duration) <= 0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("A Day Template Flex duration must be a positive number.") from exc


def _ordered_anchor_entries(
    anchors: list[dict[str, object]],
    activity_library: dict[str, ActivityTemplate] | None = None,
    wake: str | None = None,
) -> list[dict[str, object]]:
    """Put all anchors in chronological order by wake-relative offset."""
    library = activity_library or {}
    wake_time = parse_clock(wake) if wake is not None else None

    def anchor_start_offset(entry: dict[str, object]) -> tuple[int, int]:
        start_val = entry.get("start")
        if start_val is None and "activity" in entry:
            act = library.get(str(entry["activity"]))
            if act is not None and act.start is not None:
                start_val = act.start.strftime("%H:%M")
        if start_val is None:
            return (1, 0)
        start_clock = parse_clock(str(start_val))
        if wake_time is not None:
            return (0, minutes_from_bound(wake_time, start_clock))
        return (0, start_clock.hour * 60 + start_clock.minute)

    return sorted(anchors, key=anchor_start_offset)


def save_day_template(
    repo_root: Path,
    *,
    id: str | None = None,
    name: str,
    anchors: list[dict[str, object]] | None = None,
    flexes: list[dict[str, object]] | None = None,
    weekday: str | None = None,
    wake: str | None = None,
    sleep: str | None = None,
) -> str:
    """Create (id=None) or update (existing id) a Day Template TOML file.

    `anchors`/`flexes` entries are dicts matching the TOML entry shape, e.g.
    {"name": ..., "start": ..., "duration": ...} or {..., "end": ...} or
    {"activity": "<activity_id>"}.
    """
    if not name.strip():
        raise ValueError("Day Template name cannot be blank.")
    directory = day_templates_dir(repo_root)
    directory.mkdir(parents=True, exist_ok=True)
    slug = _resolve_slug(directory, "Day Template", id=id, name=name)

    anchor_entries = list(anchors or [])
    flex_entries = list(flexes or [])
    activity_library = load_activity_template_library(repo_root)
    for anchor in anchor_entries:
        _validate_anchor_entry(anchor, activity_library)
    for flex in flex_entries:
        _validate_flex_entry(flex, activity_library)
    anchor_entries = _ordered_anchor_entries(anchor_entries, activity_library, wake=wake)

    if (wake is None) != (sleep is None):
        raise ValueError("Give both wake and sleep bounds, or neither.")
    if wake is not None and sleep is not None:
        minutes_from_bound(parse_clock(wake), parse_clock(sleep))

    lines = [f"name = {_toml_string(name)}"]
    if weekday is not None:
        lines.append(f"weekday = {_toml_string(weekday)}")
    if wake is not None:
        lines.append(f"wake = {_toml_string(wake)}")
        lines.append(f"sleep = {_toml_string(sleep)}")
    lines.append("")

    for anchor in anchor_entries:
        lines.append("[[anchor]]")
        lines.extend(_entry_lines(anchor))
        lines.append("")
    for flex in flex_entries:
        lines.append("[[flex]]")
        lines.extend(_entry_lines(flex))
        lines.append("")

    _write_toml_lines(directory, slug, lines)
    if weekday is not None:
        _unassign_other_weekday_owners(directory, weekday, slug)
    return slug


def _entry_lines(entry: dict[str, object]) -> list[str]:
    lines: list[str] = []
    if "activity" in entry:
        lines.append(f"activity = {_toml_string(str(entry['activity']))}")
        for key in ("shape", "name", "start", "end", "checklist"):
            if entry.get(key) is not None:
                lines.append(f"{key} = {_toml_string(str(entry[key]))}")
        if entry.get("duration") is not None:
            lines.append(f"duration = {int(entry['duration'])}")  # type: ignore[arg-type]
        return lines
    lines.append(f"name = {_toml_string(str(entry['name']))}")
    if entry.get("start") is not None:
        lines.append(f"start = {_toml_string(str(entry['start']))}")
    if entry.get("end") is not None:
        lines.append(f"end = {_toml_string(str(entry['end']))}")
    elif entry.get("duration") is not None:
        lines.append(f"duration = {int(entry['duration'])}")  # type: ignore[arg-type]
    if entry.get("checklist") is not None:
        lines.append(f"checklist = {_toml_string(str(entry['checklist']))}")
    return lines


def delete_day_template(repo_root: Path, *, template_id: str) -> None:
    path = day_templates_dir(repo_root) / f"{template_id}.toml"
    path.unlink(missing_ok=True)


def day_template_order(directory_or_repo_root: Path) -> list[str]:
    """Return saved Day Template order, followed by any new templates by id."""
    directory = (
        directory_or_repo_root
        if directory_or_repo_root.name == "templates"
        else day_templates_dir(directory_or_repo_root)
    )
    ids = {path.stem for path in directory.glob("*.toml")} if directory.is_dir() else set()
    order_path = directory / ".order.json"
    try:
        saved = json.loads(order_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        saved = []
    ordered = [item for item in saved if isinstance(item, str) and item in ids]
    ordered.extend(sorted(ids - set(ordered)))
    return ordered


def reorder_day_templates(repo_root: Path, *, ids: list[str]) -> None:
    """Persist a complete Day Template ordering, rejecting stale or partial lists."""
    directory = day_templates_dir(repo_root)
    current = {path.stem for path in directory.glob("*.toml")} if directory.is_dir() else set()
    if len(ids) != len(set(ids)) or set(ids) != current:
        raise ValueError("Day Templates changed. Reload the Library and try again.")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".order.json").write_text(
        json.dumps(ids, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_day_template_name(path: Path) -> str:
    """Return the Day Template's `name` field, falling back to the filename stem."""
    if not path.exists():
        return path.stem
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return path.stem
    name = data.get("name")
    return str(name) if name is not None else path.stem


def load_day_template_entries(path: Path) -> dict[str, object]:
    """Return a Day Template's raw `weekday`/anchor/flex entry dicts, unresolved.

    Unlike `load_day_template`, `activity` references are left as-is (not
    resolved against an Activity Template library) so callers can round-trip
    the entries back through `library.save_day_template` for editing.
    """
    if not path.exists():
        return {"weekday": None, "wake": None, "sleep": None, "anchors": [], "flexes": []}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {"weekday": None, "wake": None, "sleep": None, "anchors": [], "flexes": []}
    return {
        "weekday": data.get("weekday"),
        "wake": data.get("wake"),
        "sleep": data.get("sleep"),
        "anchors": list(data.get("anchor", ())),
        "flexes": list(data.get("flex", ())),
    }


def _parse_entry_duration_minutes(entry: dict[str, object]) -> int:
    duration = entry.get("duration")
    if duration is None:
        raise ValueError("Day Template entry requires duration in minutes.")
    return int(duration)


def _parse_entry_checklist(entry: dict[str, object]) -> str | None:
    checklist = entry.get("checklist")
    if checklist is None:
        return None
    return str(checklist)


def _parse_literal_anchor(entry: dict[str, object]) -> Anchor:
    start = parse_clock(str(entry["start"]))
    end_value = entry.get("end")
    if end_value is not None:
        duration = timedelta(minutes=minutes_from_bound(start, parse_clock(str(end_value))))
    else:
        duration = timedelta(minutes=_parse_entry_duration_minutes(entry))
    return Anchor(
        name=str(entry["name"]),
        start=start,
        duration=duration,
        checklist=_parse_entry_checklist(entry),
    )


def _parse_literal_flex(entry: dict[str, object]) -> Flex:
    return Flex(
        name=str(entry["name"]),
        duration=timedelta(minutes=_parse_entry_duration_minutes(entry)),
        checklist=_parse_entry_checklist(entry),
    )


def load_day_template(
    path: Path,
    activity_library: dict[str, ActivityTemplate] | None = None,
) -> TemplateSeed | None:
    if not path.exists():
        return None

    library = activity_library or {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return None
    anchor_entries = list(data.get("anchor", ()))
    flex_entries = list(data.get("flex", ()))

    anchors: list[Anchor] = []
    flexes: list[Flex] = []

    # An activity reference follows its explicit shape override, or the
    # Activity Template's current shape.  The section is only a legacy hint.
    for entry in anchor_entries + flex_entries:
        activity_name = entry.get("activity")
        if activity_name is None:
            continue
        activity = library.get(str(activity_name))
        if activity is None:
            continue
        shape = str(entry.get("shape") or ("anchor" if activity.start is not None else "flex"))
        name = str(entry.get("name") or activity.name)
        checklist = (
            str(entry["checklist"]) if "checklist" in entry else activity.checklist
        )
        duration = (
            timedelta(minutes=int(entry["duration"]))
            if entry.get("duration") is not None
            else activity.duration
        )
        start_value = entry.get("start") if "start" in entry else activity.start
        end_value = entry.get("end") if "end" in entry else None
        start_time = (
            start_value
            if hasattr(start_value, "hour") and hasattr(start_value, "minute")
            else parse_clock(str(start_value))
            if start_value is not None
            else None
        )
        if end_value is not None and start_time is not None:
            duration = timedelta(
                minutes=minutes_from_bound(start_time, parse_clock(str(end_value)))
            )
        if shape == "anchor" and start_time is not None:
            anchors.append(
                Anchor(
                    name=name,
                    start=start_time,
                    duration=duration,
                    checklist=checklist,
                    activity_template_id=str(activity_name),
                )
            )
        elif shape == "flex":
            flexes.append(
                Flex(
                    name=name,
                    duration=duration,
                    checklist=checklist,
                    activity_template_id=str(activity_name),
                )
            )

    for entry in anchor_entries:
        if "activity" in entry:
            continue
        anchors.append(_parse_literal_anchor(entry))
    for entry in flex_entries:
        if "activity" in entry:
            continue
        flexes.append(_parse_literal_flex(entry))

    wake_value = data.get("wake")
    sleep_value = data.get("sleep")
    return TemplateSeed(
        anchors=tuple(anchors),
        flexes=tuple(flexes),
        wake=str(wake_value) if wake_value is not None else None,
        sleep=str(sleep_value) if sleep_value is not None else None,
    )


def list_day_templates(data_dir_or_repo_root: Path) -> list[dict]:
    templates_dir = day_templates_dir(data_dir_or_repo_root)
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


def seed_day_template(repo_root: Path, template_id: str) -> TemplateSeed | None:
    """Load and resolve a Day Template by its id into a TemplateSeed."""
    activity_library = load_activity_template_library(repo_root)
    path = named_day_template_path(repo_root, template_id)
    return load_day_template(path, activity_library)


def seed_default_day_template(repo_root: Path, plan_date: date) -> TemplateSeed | None:
    """Load and resolve the default Day Template for `plan_date` into a TemplateSeed."""
    activity_library = load_activity_template_library(repo_root)
    path = default_day_template_path(repo_root, plan_date)
    return load_day_template(path, activity_library)


def default_day_template_name(repo_root: Path, plan_date: date) -> str | None:
    """Return the display name of the default Day Template for `plan_date`, if one exists."""
    path = default_day_template_path(repo_root, plan_date)
    if not path.exists():
        return None
    return load_day_template_name(path)


# --- Unified Autocomplete / Suggestion ---------------------------------------


def suggest_activity(data_dir_or_repo_root: Path, item_name: str) -> dict | None:
    """Suggest an Activity Template or Checklist match for `item_name`.

    Checks the Activity Template library first; an Activity Template match
    takes precedence over the bare Checklist match. Falls back to
    `suggest_checklist` when no Activity Template matches.
    """
    activity_library = load_activity_template_library(data_dir_or_repo_root)
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

    checklist_id = suggest_checklist(item_name, load_checklist_library(data_dir_or_repo_root))
    if checklist_id is not None:
        return {"kind": "checklist", "checklist_id": checklist_id}
    return None


__all__ = [
    "ActivityTemplate",
    "Checklist",
    "TemplateSeed",
    "activity_templates_dir",
    "checklists_dir",
    "day_template_order",
    "day_template_path",
    "day_templates_dir",
    "default_day_template_name",
    "default_day_template_path",
    "delete_activity_template",
    "delete_checklist",
    "delete_day_template",
    "list_activity_templates",
    "list_checklists",
    "list_day_templates",
    "load_activity_template_library",
    "load_checklist_library",
    "load_day_template",
    "load_day_template_entries",
    "load_day_template_name",
    "named_day_template_path",
    "normalize",
    "reorder_day_templates",
    "save_activity_template",
    "save_checklist",
    "save_day_template",
    "seed_day_template",
    "seed_default_day_template",
    "suggest_activity",
    "suggest_activity_template",
    "suggest_by_name",
    "suggest_checklist",
]
