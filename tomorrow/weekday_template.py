"""Load weekday Templates from editable files under data/templates/."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import tomllib

from tomorrow.domain import Anchor, Flex, parse_clock


@dataclass(frozen=True)
class TemplateSeed:
    """Anchors and unplaced Flex copied from a weekday Template."""

    anchors: tuple[Anchor, ...]
    flexes: tuple[Flex, ...]


def weekday_template_path(data_dir: Path, plan_date: date) -> Path:
    weekday = plan_date.strftime("%A").lower()
    return data_dir / "templates" / f"{weekday}.toml"


def load_weekday_template(path: Path) -> TemplateSeed | None:
    if not path.exists():
        return None

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    anchors = tuple(_parse_anchor(entry) for entry in data.get("anchor", ()))
    flexes = tuple(_parse_flex(entry) for entry in data.get("flex", ()))
    return TemplateSeed(anchors=anchors, flexes=flexes)


def _parse_duration_minutes(entry: dict[str, object]) -> int:
    duration = entry.get("duration")
    if duration is None:
        raise ValueError("Template entry requires duration in minutes.")
    return int(duration)


def _parse_checklist(entry: dict[str, object]) -> str | None:
    checklist = entry.get("checklist")
    if checklist is None:
        return None
    return str(checklist)


def _parse_anchor(entry: dict[str, object]) -> Anchor:
    start = parse_clock(str(entry["start"]))
    duration = timedelta(minutes=_parse_duration_minutes(entry))
    return Anchor(
        name=str(entry["name"]),
        start=start,
        duration=duration,
        checklist=_parse_checklist(entry),
    )


def _parse_flex(entry: dict[str, object]) -> Flex:
    return Flex(
        name=str(entry["name"]),
        duration=timedelta(minutes=_parse_duration_minutes(entry)),
        checklist=_parse_checklist(entry),
    )
