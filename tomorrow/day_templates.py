"""Load Day Templates from editable files under data/templates/."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import tomllib

from tomorrow.activity_templates import ActivityTemplate
from tomorrow.domain import Anchor, Flex, parse_clock


@dataclass(frozen=True)
class TemplateSeed:
    """Anchors and unplaced Flex copied from a Day Template."""

    anchors: tuple[Anchor, ...]
    flexes: tuple[Flex, ...]


def day_templates_dir(data_dir: Path) -> Path:
    return data_dir / "templates"


def day_template_path(data_dir: Path, plan_date: date) -> Path:
    weekday = plan_date.strftime("%A").lower()
    return day_templates_dir(data_dir) / f"{weekday}.toml"


def default_day_template_path(data_dir: Path, plan_date: date) -> Path:
    """Return the Day Template file that is the default for `plan_date`'s weekday.

    Scans for a Day Template whose `weekday` field names this weekday; falls
    back to the legacy `<weekday>.toml` filename convention for backward
    compatibility with hand-authored files that predate the `weekday` field.
    """

    weekday = plan_date.strftime("%A").lower()
    directory = day_templates_dir(data_dir)
    legacy_path = directory / f"{weekday}.toml"
    if directory.is_dir():
        for path in sorted(directory.glob("*.toml")):
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError:
                continue
            if data.get("weekday") == weekday:
                return path
    return legacy_path


def named_day_template_path(data_dir: Path, template_id: str) -> Path:
    return day_templates_dir(data_dir) / f"{template_id}.toml"


def load_day_template_name(path: Path) -> str:
    """Return the Day Template's `name` field, falling back to the filename stem."""

    if not path.exists():
        return path.stem
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    name = data.get("name")
    return str(name) if name is not None else path.stem


def load_day_template(
    path: Path,
    activity_library: dict[str, ActivityTemplate] | None = None,
) -> TemplateSeed | None:
    if not path.exists():
        return None

    library = activity_library or {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    anchors = tuple(
        anchor
        for anchor in (_parse_anchor(entry, library) for entry in data.get("anchor", ()))
        if anchor is not None
    )
    flexes = tuple(
        flex
        for flex in (_parse_flex(entry, library) for entry in data.get("flex", ()))
        if flex is not None
    )
    return TemplateSeed(anchors=anchors, flexes=flexes)


def _parse_duration_minutes(entry: dict[str, object]) -> int:
    duration = entry.get("duration")
    if duration is None:
        raise ValueError("Day Template entry requires duration in minutes.")
    return int(duration)


def _parse_checklist(entry: dict[str, object]) -> str | None:
    checklist = entry.get("checklist")
    if checklist is None:
        return None
    return str(checklist)


def _parse_anchor(
    entry: dict[str, object], activity_library: dict[str, ActivityTemplate]
) -> Anchor | None:
    activity_name = entry.get("activity")
    if activity_name is not None:
        activity = activity_library.get(str(activity_name))
        if activity is None or activity.start is None:
            return None
        return Anchor(
            name=activity.name,
            start=activity.start,
            duration=activity.duration,
            checklist=activity.checklist,
        )
    start = parse_clock(str(entry["start"]))
    duration = timedelta(minutes=_parse_duration_minutes(entry))
    return Anchor(
        name=str(entry["name"]),
        start=start,
        duration=duration,
        checklist=_parse_checklist(entry),
    )


def _parse_flex(
    entry: dict[str, object], activity_library: dict[str, ActivityTemplate]
) -> Flex | None:
    activity_name = entry.get("activity")
    if activity_name is not None:
        activity = activity_library.get(str(activity_name))
        if activity is None or activity.start is not None:
            return None
        return Flex(
            name=activity.name,
            duration=activity.duration,
            checklist=activity.checklist,
        )
    return Flex(
        name=str(entry["name"]),
        duration=timedelta(minutes=_parse_duration_minutes(entry)),
        checklist=_parse_checklist(entry),
    )
