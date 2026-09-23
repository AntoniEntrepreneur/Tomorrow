"""In-app CRUD for the Checklist, Day Template, and Activity Template libraries.

Every entry is identified by its name: two entries of the same kind may not
share a name once letter case and punctuation are ignored (see
`library_base.normalize`). An entry's filename (its id) is derived from its
name once, on create, via `_slugify` (with a numeric suffix if that slug is
already taken); renaming an entry never renames its file.
"""

from __future__ import annotations

from pathlib import Path
import tomllib

from tomorrow.activity_templates import activity_templates_dir
from tomorrow.checklists import checklists_dir
from tomorrow.day_templates import day_templates_dir
from tomorrow.domain import minutes_from_bound, parse_clock
from tomorrow.library_base import normalize


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


# --- Checklists -----------------------------------------------------------


def save_checklist(
    repo_root: Path, *, id: str | None = None, name: str, items: list[str]
) -> str:
    """Create (id=None) or update (existing id) a Checklist TOML file."""

    directory = checklists_dir(repo_root / "data")
    slug = _resolve_slug(directory, "Checklist", id=id, name=name)

    lines = [f"name = {_toml_string(name)}"]
    items_repr = ", ".join(_toml_string(item) for item in items)
    lines.append(f"items = [{items_repr}]")
    _write_toml_lines(directory, slug, lines)
    return slug


def delete_checklist(repo_root: Path, *, checklist_id: str) -> None:
    path = checklists_dir(repo_root / "data") / f"{checklist_id}.toml"
    path.unlink(missing_ok=True)


# --- Activity Templates -----------------------------------------------------


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

    directory = activity_templates_dir(repo_root / "data")
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
    path = activity_templates_dir(repo_root / "data") / f"{activity_id}.toml"
    path.unlink(missing_ok=True)


# --- Day Templates -----------------------------------------------------


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


def _validate_anchor_entry(entry: dict[str, object]) -> None:
    if "activity" in entry:
        return
    start = entry.get("start")
    if start is None:
        raise ValueError("A Day Template Anchor entry requires a start time.")
    duration = entry.get("duration")
    end = entry.get("end")
    if (duration is None) == (end is None):
        raise ValueError("Give either a duration or an end time, not both or neither.")
    if end is not None:
        minutes_from_bound(parse_clock(str(start)), parse_clock(str(end)))


def save_day_template(
    repo_root: Path,
    *,
    id: str | None = None,
    name: str,
    anchors: list[dict[str, object]] | None = None,
    flexes: list[dict[str, object]] | None = None,
    weekday: str | None = None,
) -> str:
    """Create (id=None) or update (existing id) a Day Template TOML file.

    `anchors`/`flexes` entries are dicts matching the TOML entry shape, e.g.
    {"name": ..., "start": ..., "duration": ...} or {..., "end": ...} or
    {"activity": "<activity_id>"}.
    """

    directory = day_templates_dir(repo_root / "data")
    directory.mkdir(parents=True, exist_ok=True)
    slug = _resolve_slug(directory, "Day Template", id=id, name=name)

    for anchor in anchors or []:
        _validate_anchor_entry(anchor)

    if weekday is not None:
        _unassign_other_weekday_owners(directory, weekday, slug)

    lines = [f"name = {_toml_string(name)}"]
    if weekday is not None:
        lines.append(f"weekday = {_toml_string(weekday)}")
    lines.append("")

    for anchor in anchors or []:
        lines.append("[[anchor]]")
        lines.extend(_entry_lines(anchor))
        lines.append("")
    for flex in flexes or []:
        lines.append("[[flex]]")
        lines.extend(_entry_lines(flex))
        lines.append("")

    _write_toml_lines(directory, slug, lines)
    return slug


def _entry_lines(entry: dict[str, object]) -> list[str]:
    lines: list[str] = []
    if "activity" in entry:
        lines.append(f"activity = {_toml_string(str(entry['activity']))}")
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
    path = day_templates_dir(repo_root / "data") / f"{template_id}.toml"
    path.unlink(missing_ok=True)
