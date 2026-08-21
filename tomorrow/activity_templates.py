"""Load named Activity Templates from editable files under data/activity-templates/."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta
from pathlib import Path
import tomllib

from tomorrow.domain import parse_clock


@dataclass(frozen=True)
class ActivityTemplate:
    """A single reusable Anchor-shaped or Flex-shaped item."""

    name: str
    duration: timedelta
    start: time | None = None
    checklist: str | None = None


def activity_templates_dir(data_dir: Path) -> Path:
    return data_dir / "activity-templates"


def load_activity_template_library(data_dir: Path) -> dict[str, ActivityTemplate]:
    """Load every *.toml file in data/activity-templates/, keyed by filename stem."""

    directory = activity_templates_dir(data_dir)
    if not directory.is_dir():
        return {}

    library: dict[str, ActivityTemplate] = {}
    for path in sorted(directory.glob("*.toml")):
        library[path.stem] = _parse_activity_template(path)
    return library


def _parse_activity_template(path: Path) -> ActivityTemplate:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    start_value = data.get("start")
    duration = timedelta(minutes=int(data["duration"]))
    checklist = data.get("checklist")
    return ActivityTemplate(
        name=str(data["name"]),
        duration=duration,
        start=parse_clock(str(start_value)) if start_value is not None else None,
        checklist=str(checklist) if checklist is not None else None,
    )


def _normalize(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def suggest_activity_template(
    item_name: str, library: dict[str, ActivityTemplate]
) -> str | None:
    """Return a library key when the item name resembles an Activity Template id or name."""

    needle = _normalize(item_name)
    if not needle:
        return None

    matches: list[str] = []
    for template_id, template in library.items():
        candidates = (_normalize(template_id), _normalize(template.name))
        if any(needle in candidate or candidate in needle for candidate in candidates if candidate):
            matches.append(template_id)

    if len(matches) == 1:
        return matches[0]
    return None
