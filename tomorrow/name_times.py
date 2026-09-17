"""Pure grammar for detecting a time written inside an item's name.

Given a name such as ``"Tutoring 16:30"``, `parse_name_time` finds the first
whole-token time, reports it, and returns the name with that token (and any
leftover whitespace/punctuation around it) removed.

This ticket (#78) only detects a single start time. Later tickets extend the
same result shape with a range end and a duration, which is why the result
is a shaped dataclass rather than a bare tuple. No filesystem, no clock, no
Session: this module knows nothing about `tomorrow/domain.py` (see ADR
0002) and is exercised entirely by `tests/test_name_times.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NameTimeResult:
    """What was found in a name, and the name with it removed.

    `stripped_name` equals the original name when nothing matched. `start`
    is a "HH:MM" 24-hour string, or None when no start was found. Later
    tickets add `end` and `duration_minutes` fields alongside `start` for
    ranges and durations; this ticket only ever populates `start`.
    """

    stripped_name: str
    start: str | None = None

    @property
    def matched(self) -> bool:
        return self.start is not None


_HOUR_MIN = r"(?P<h24>[01]?\d|2[0-3]):(?P<m24>[0-5]\d)"
_TWELVE_HOUR = r"(?P<h12>1[0-2]|[1-9])(?::(?P<m12>[0-5]\d))? ?(?P<mer>[AaPp][Mm])"

_TIME_TOKEN = re.compile(rf"(?<!\w)(?:{_TWELVE_HOUR}|{_HOUR_MIN})(?!\w)")

_TRAILING_PUNCT = re.compile(r"[-–—:,]+$")
_LEADING_PUNCT = re.compile(r"^[-–—:,]+")


def _to_24h(match: re.Match) -> str | None:
    if match.group("h24") is not None:
        hour = int(match.group("h24"))
        minute = int(match.group("m24"))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
        return None
    hour = int(match.group("h12"))
    minute = int(match.group("m12")) if match.group("m12") else 0
    meridiem = match.group("mer").lower()
    if meridiem == "am":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    return f"{hour:02d}:{minute:02d}"


def _clean(text: str) -> str:
    text = re.sub(r"\s{2,}", " ", text)
    text = text.strip()
    text = _TRAILING_PUNCT.sub("", text).strip()
    text = _LEADING_PUNCT.sub("", text).strip()
    return text


def parse_name_time(name: str) -> NameTimeResult:
    """Find the first whole-token start time in `name`.

    Returns a `NameTimeResult` with the matched token removed from the
    name (whitespace/punctuation cleaned up) and `start` set to the
    "HH:MM" 24-hour form. When no valid token is found, returns the name
    unchanged with `start` set to None.
    """
    for match in _TIME_TOKEN.finditer(name):
        start = _to_24h(match)
        if start is None:
            continue
        stripped = name[: match.start()] + name[match.end() :]
        return NameTimeResult(stripped_name=_clean(stripped), start=start)
    return NameTimeResult(stripped_name=name, start=None)
