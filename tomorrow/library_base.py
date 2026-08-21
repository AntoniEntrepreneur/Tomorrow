"""Shared normalize / fuzzy-match / TOML-directory-loader helpers for library modules."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


def normalize(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def load_toml_library(directory: Path, parse: Callable[[Path], T]) -> dict[str, T]:
    """Load every *.toml file in `directory`, keyed by filename stem."""

    if not directory.is_dir():
        return {}
    return {path.stem: parse(path) for path in sorted(directory.glob("*.toml"))}


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
