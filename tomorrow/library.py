"""In-app CRUD for the Checklist, Day Template, and Activity Template libraries."""

from __future__ import annotations

from pathlib import Path
import tomllib

from tomorrow.activity_templates import activity_templates_dir
from tomorrow.checklists import checklists_dir
from tomorrow.day_templates import day_templates_dir


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


# --- Checklists -----------------------------------------------------------


def save_checklist(repo_root: Path, *, checklist_id: str, name: str, items: list[str]) -> str:
    """Write a Checklist TOML file, creating or overwriting `checklist_id`."""

    slug = checklist_id or _slugify(name)
    lines = [f"name = {_toml_string(name)}"]
    items_repr = ", ".join(_toml_string(item) for item in items)
    lines.append(f"items = [{items_repr}]")
    _write_toml_lines(checklists_dir(repo_root / "data"), slug, lines)
    return slug


def delete_checklist(repo_root: Path, *, checklist_id: str) -> None:
    path = checklists_dir(repo_root / "data") / f"{checklist_id}.toml"
    path.unlink(missing_ok=True)


# --- Activity Templates -----------------------------------------------------


def save_activity_template(
    repo_root: Path,
    *,
    activity_id: str,
    name: str,
    duration_minutes: int,
    start: str | None = None,
    checklist: str | None = None,
) -> str:
    slug = activity_id or _slugify(name)
    lines = [f"name = {_toml_string(name)}", f"duration = {int(duration_minutes)}"]
    if start is not None:
        lines.append(f"start = {_toml_string(start)}")
    if checklist is not None:
        lines.append(f"checklist = {_toml_string(checklist)}")
    _write_toml_lines(activity_templates_dir(repo_root / "data"), slug, lines)
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


def save_day_template(
    repo_root: Path,
    *,
    template_id: str,
    name: str,
    anchors: list[dict[str, object]] | None = None,
    flexes: list[dict[str, object]] | None = None,
    weekday: str | None = None,
) -> str:
    """Write a Day Template TOML file, enforcing one weekday default at a time.

    `anchors`/`flexes` entries are dicts matching the TOML entry shape, e.g.
    {"name": ..., "start": ..., "duration": ..., "checklist": ...} or
    {"activity": "<activity_id>"}.
    """

    directory = day_templates_dir(repo_root / "data")
    directory.mkdir(parents=True, exist_ok=True)
    slug = template_id or _slugify(name)

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
    if entry.get("duration") is not None:
        lines.append(f"duration = {int(entry['duration'])}")  # type: ignore[arg-type]
    if entry.get("checklist") is not None:
        lines.append(f"checklist = {_toml_string(str(entry['checklist']))}")
    return lines


def delete_day_template(repo_root: Path, *, template_id: str) -> None:
    path = day_templates_dir(repo_root / "data") / f"{template_id}.toml"
    path.unlink(missing_ok=True)
