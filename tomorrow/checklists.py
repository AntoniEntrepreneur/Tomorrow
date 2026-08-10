"""Load named Checklists from editable files under data/checklists/."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class Checklist:
    """A reusable named list of things to bring or do."""

    name: str
    items: tuple[str, ...]


def checklists_dir(data_dir: Path) -> Path:
    return data_dir / "checklists"


def load_checklist_library(data_dir: Path) -> dict[str, Checklist]:
    """Load every *.toml file in data/checklists/, keyed by filename stem."""

    directory = checklists_dir(data_dir)
    if not directory.is_dir():
        return {}

    library: dict[str, Checklist] = {}
    for path in sorted(directory.glob("*.toml")):
        library[path.stem] = _parse_checklist(path)
    return library


def _parse_checklist(path: Path) -> Checklist:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    items = tuple(str(item) for item in data.get("items", ()))
    return Checklist(name=str(data["name"]), items=items)


def _normalize(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def suggest_checklist(item_name: str, library: dict[str, Checklist]) -> str | None:
    """Return a library key when the item name resembles a Checklist id or name."""

    needle = _normalize(item_name)
    if not needle:
        return None

    matches: list[str] = []
    for checklist_id, checklist in library.items():
        candidates = (_normalize(checklist_id), _normalize(checklist.name))
        if any(needle in candidate or candidate in needle for candidate in candidates if candidate):
            matches.append(checklist_id)

    if len(matches) == 1:
        return matches[0]
    return None
