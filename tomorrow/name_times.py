"""Pure grammar for detecting a time written inside an item's name.

Given a name such as ``"Tutoring 16:30"``, `parse_name_time` finds the first
whole-token time, reports it, and returns the name with that token (and any
leftover whitespace/punctuation around it) removed.

This ticket (#78) started with a single start time; #80 adds duration
detection alongside it. A later ticket extends the same result shape with
a range end, which is why the result is a shaped dataclass rather than a
bare tuple. No filesystem, no clock, no Session: this module knows
nothing about `tomorrow/domain.py` (see ADR 0002) and is exercised
entirely by `tests/test_name_times.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NameTimeResult:
    """What was found in a name, and the name with it removed.

    `stripped_name` equals the original name when nothing matched. `start`
    is a "HH:MM" 24-hour string, or None when no start was found.
    `duration_minutes` is an int, or None when no duration was found. A
    later ticket adds an `end` field alongside these for ranges.
    """

    stripped_name: str
    start: str | None = None
    duration_minutes: int | None = None

    @property
    def matched(self) -> bool:
        return self.start is not None or self.duration_minutes is not None


_HOUR_MIN = r"(?P<h24>[01]?\d|2[0-3]):(?P<m24>[0-5]\d)"
_TWELVE_HOUR = r"(?P<h12>1[0-2]|[1-9])(?::(?P<m12>[0-5]\d))? ?(?P<mer>[AaPp][Mm])"

_TIME_TOKEN = re.compile(rf"(?<!\w)(?:{_TWELVE_HOUR}|{_HOUR_MIN})(?!\w)")

_DURATION_CORE = (
    r"(?:(?P<dh>\d+(?:\.\d+)?)h(?P<dhm>[0-5]\d)?|(?P<dm>\d+) ?(?:min|m))"
)
_DURATION_TOKEN = re.compile(
    rf"(?<!\w)\(?{_DURATION_CORE}\)?(?!\w)"
)

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


def _duration_minutes(match: re.Match) -> int | None:
    if match.group("dh") is not None:
        total = round(float(match.group("dh")) * 60)
        if match.group("dhm"):
            total += int(match.group("dhm"))
        return total
    if match.group("dm") is not None:
        return int(match.group("dm"))
    return None


def _clean(text: str) -> str:
    text = re.sub(r"\s{2,}", " ", text)
    text = text.strip()
    text = _TRAILING_PUNCT.sub("", text).strip()
    text = _LEADING_PUNCT.sub("", text).strip()
    return text


def parse_name_time(name: str) -> NameTimeResult:
    """Find the first whole-token start time and/or duration in `name`.

    Returns a `NameTimeResult` with the matched token(s) removed from the
    name (whitespace/punctuation cleaned up), `start` set to the "HH:MM"
    24-hour form when a start was found, and `duration_minutes` set to an
    int when a duration was found. Either, both, or neither may be
    present. When nothing is found, returns the name unchanged.
    """
    start: str | None = None
    start_span: tuple[int, int] | None = None
    for match in _TIME_TOKEN.finditer(name):
        candidate = _to_24h(match)
        if candidate is None:
            continue
        start = candidate
        start_span = match.span()
        break

    duration: int | None = None
    duration_span: tuple[int, int] | None = None
    for match in _DURATION_TOKEN.finditer(name):
        candidate = _duration_minutes(match)
        if candidate is None:
            continue
        duration = candidate
        duration_span = match.span()
        break

    if start is None and duration is None:
        return NameTimeResult(stripped_name=name)

    spans = sorted(
        (span for span in (start_span, duration_span) if span is not None),
        key=lambda span: span[0],
        reverse=True,
    )
    stripped = name
    for span_start, span_end in spans:
        stripped = stripped[:span_start] + stripped[span_end:]
    return NameTimeResult(
        stripped_name=_clean(stripped), start=start, duration_minutes=duration
    )
