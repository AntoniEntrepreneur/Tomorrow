"""Load named Activity Templates from editable files under data/activity-templates/."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta
from pathlib import Path
import tomllib

from tomorrow.domain import minutes_from_bound, parse_clock
from tomorrow.library_base import load_toml_library, suggest_by_name


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


def activity_templates_dir(data_dir: Path) -> Path:
    return data_dir / "activity-templates"


def load_activity_template_library(data_dir: Path) -> dict[str, ActivityTemplate]:
    """Load every *.toml file in data/activity-templates/, keyed by filename stem."""

    return load_toml_library(activity_templates_dir(data_dir), _parse_activity_template)


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


def suggest_activity_template(
    item_name: str, library: dict[str, ActivityTemplate]
) -> str | None:
    """Return a library key when the item name resembles an Activity Template id or name."""

    return suggest_by_name(item_name, library, name_of=lambda template: template.name)
