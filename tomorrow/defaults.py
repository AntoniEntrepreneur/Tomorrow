from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class DayBounds:
    wake: str
    sleep: str


def load_defaults(path: Path) -> DayBounds:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return DayBounds(wake=str(data["wake"]), sleep=str(data["sleep"]))


def load_anchor_default_minutes(path: Path) -> dict[str, int]:
    """Optional library of default occupied-time minutes, keyed by lowercase name.

    Missing file means no library exists yet — that's not an error, promotion just falls through to the next source.
    """
    if not path.exists():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {str(name).lower(): int(minutes) for name, minutes in data.items()}
