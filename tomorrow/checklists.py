"""Load named Checklists from editable files under data/checklists/."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from tomorrow.library_base import load_toml_library, suggest_by_name


@dataclass(frozen=True)
class Checklist:
    """A reusable named list of things to bring or do."""

    name: str
    items: tuple[str, ...]


def checklists_dir(data_dir: Path) -> Path:
    return data_dir / "checklists"


def load_checklist_library(data_dir: Path) -> dict[str, Checklist]:
    """Load every *.toml file in data/checklists/, keyed by filename stem."""

    return load_toml_library(checklists_dir(data_dir), _parse_checklist)


def _parse_checklist(path: Path) -> Checklist:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    items = tuple(str(item) for item in data.get("items", ()))
    return Checklist(name=str(data["name"]), items=items)


def suggest_checklist(item_name: str, library: dict[str, Checklist]) -> str | None:
    """Return a library key when the item name resembles a Checklist id or name."""

    return suggest_by_name(item_name, library, name_of=lambda checklist: checklist.name)
