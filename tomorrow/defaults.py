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
