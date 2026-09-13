from dataclasses import dataclass
from pathlib import Path
import re
import tomllib


@dataclass(frozen=True)
class DayBounds:
    wake: str
    sleep: str


class DefaultsError(ValueError):
    """Raised for an invalid time string or an invalid Defaults value."""


_TIME_OF_DAY = re.compile(r"^(\d{1,2}):([0-5]\d)$")


def parse_time_of_day(value: str) -> str:
    """Parse an `H:MM` or `HH:MM` time (hours 0-23, minutes 00-59) into `HH:MM`."""

    match = _TIME_OF_DAY.match(value)
    if match is None:
        raise DefaultsError(f"Not a valid time: {value!r}. Use H:MM or HH:MM.")
    hours = int(match.group(1))
    if hours > 23:
        raise DefaultsError(f"Not a valid time: {value!r}. Use H:MM or HH:MM.")
    return f"{hours:02d}:{match.group(2)}"


def load_defaults(path: Path) -> DayBounds:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return DayBounds(wake=str(data["wake"]), sleep=str(data["sleep"]))


def save_defaults(path: Path, bounds: DayBounds) -> None:
    if bounds.wake == bounds.sleep:
        raise DefaultsError("Wake and sleep cannot be the same time — that's a zero-length day.")
    path.write_text(
        f'wake = "{bounds.wake}"\nsleep = "{bounds.sleep}"\n', encoding="utf-8"
    )


def load_anchor_default_minutes(path: Path) -> dict[str, int]:
    """Optional library of default occupied-time minutes, keyed by lowercase name.

    Missing file means no library exists yet — that's not an error, promotion just falls through to the next source.
    """
    if not path.exists():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {str(name).lower(): int(minutes) for name, minutes in data.items()}
