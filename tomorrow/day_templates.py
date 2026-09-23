"""Load Day Templates from editable files under data/templates/."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import tomllib

from tomorrow.activity_templates import ActivityTemplate
from tomorrow.domain import Anchor, Flex, minutes_from_bound, parse_clock


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


def load_day_template_entries(path: Path) -> dict[str, object]:
    """Return a Day Template's raw `weekday`/anchor/flex entry dicts, unresolved.

    Unlike `load_day_template`, `activity` references are left as-is (not
    resolved against an Activity Template library) so callers can round-trip
    the entries back through `library.save_day_template` for editing.
    """

    if not path.exists():
        return {"weekday": None, "anchors": [], "flexes": []}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {
        "weekday": data.get("weekday"),
        "anchors": list(data.get("anchor", ())),
        "flexes": list(data.get("flex", ())),
    }


def load_day_template(
    path: Path,
    activity_library: dict[str, ActivityTemplate] | None = None,
) -> TemplateSeed | None:
    if not path.exists():
        return None

    library = activity_library or {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    anchor_entries = list(data.get("anchor", ()))
    flex_entries = list(data.get("flex", ()))

    anchors: list[Anchor] = []
    flexes: list[Flex] = []

    # An `activity = <id>` entry always follows the Activity Template's
    # *current* shape, regardless of which section it is stored under, so
    # switching an Activity Template between Anchor and Flex never drops it.
    for entry in anchor_entries + flex_entries:
        activity_name = entry.get("activity")
        if activity_name is None:
            continue
        activity = library.get(str(activity_name))
        if activity is None:
            continue
        if activity.start is not None:
            anchors.append(
                Anchor(
                    name=activity.name,
                    start=activity.start,
                    duration=activity.duration,
                    checklist=activity.checklist,
                    activity_template_id=str(activity_name),
                )
            )
        else:
            flexes.append(
                Flex(
                    name=activity.name,
                    duration=activity.duration,
                    checklist=activity.checklist,
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

    return TemplateSeed(anchors=tuple(anchors), flexes=tuple(flexes))


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


def _parse_literal_anchor(entry: dict[str, object]) -> Anchor:
    start = parse_clock(str(entry["start"]))
    end_value = entry.get("end")
    if end_value is not None:
        duration = timedelta(minutes=minutes_from_bound(start, parse_clock(str(end_value))))
    else:
        duration = timedelta(minutes=_parse_duration_minutes(entry))
    return Anchor(
        name=str(entry["name"]),
        start=start,
        duration=duration,
        checklist=_parse_checklist(entry),
    )


def _parse_literal_flex(entry: dict[str, object]) -> Flex:
    return Flex(
        name=str(entry["name"]),
        duration=timedelta(minutes=_parse_duration_minutes(entry)),
        checklist=_parse_checklist(entry),
    )
