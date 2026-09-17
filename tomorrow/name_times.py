"""Pure grammar for detecting a time (or a time range) written inside an
item's name.

Given a name such as ``"Tutoring 16:30"``, `parse_name_time` finds the first
whole-token time, reports it, and returns the name with that token (and any
leftover whitespace/punctuation around it) removed. Given a name such as
``"Tutoring 16:30-18:00"``, it finds the range instead and reports both
ends, stripping the whole range token from the name.

Ticket #78 only detected a single start time. Ticket #79 (this file, now)
adds range detection: two start-forms joined by ``-``, an en dash ``–``, or
the spaced word `` to ``, with a single trailing meridiem allowed to govern
both ends (``Squash 4-6pm`` -> 16:00-18:00). A range whose end is not after
its start is discarded -- the token is still stripped from the name (it was
still recognized as range-shaped), but only `start` survives; no midnight
crossing is ever assumed. A later ticket adds `duration_minutes` alongside
these for duration detection, which is why the result is a shaped
dataclass rather than a bare tuple. No filesystem, no clock, no Session:
this module knows nothing about `tomorrow/domain.py` (see ADR 0002) and is
exercised entirely by `tests/test_name_times.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NameTimeResult:
    """What was found in a name, and the name with it removed.

    `stripped_name` equals the original name when nothing matched. `start`
    is a "HH:MM" 24-hour string, or None when no start was found. `end` is
    likewise a "HH:MM" string when a valid range was found (end strictly
    after start), or None otherwise -- including when a range-shaped token
    was found but discarded because its end did not follow its start. A
    later ticket adds `duration_minutes` alongside these for duration
    detection.
    """

    stripped_name: str
    start: str | None = None
    end: str | None = None

    @property
    def matched(self) -> bool:
        return self.start is not None


_HOUR_MIN = r"(?P<h24>[01]?\d|2[0-3]):(?P<m24>[0-5]\d)"
_TWELVE_HOUR = r"(?P<h12>1[0-2]|[1-9])(?::(?P<m12>[0-5]\d))? ?(?P<mer>[AaPp][Mm])"

_TIME_TOKEN = re.compile(rf"(?<!\w)(?:{_TWELVE_HOUR}|{_HOUR_MIN})(?!\w)")

_TRAILING_PUNCT = re.compile(r"[-–—:,]+$")
_LEADING_PUNCT = re.compile(r"^[-–—:,]+")

# A range side is intentionally loose (hour 0-23, optional minutes, optional
# own meridiem) -- whether it means 24h or 12h is resolved after matching,
# once we know if it (or the far side, for a trailing meridiem) carries an
# am/pm marker.
_RANGE_SIDE = r"(?P<h{n}>[01]?\d|2[0-3])(?::(?P<m{n}>[0-5]\d))?(?P<mer{n}>\s?[AaPp][Mm])?"
_RANGE_SEP = r"(?:\s*[-–—]\s*|\s+to\s+)"

_RANGE_TOKEN = re.compile(
    r"(?<!\w)"
    + _RANGE_SIDE.format(n=1)
    + _RANGE_SEP
    + _RANGE_SIDE.format(n=2)
    + r"(?!\w)"
)


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


def _resolve_side(hour_str: str, minute_str: str | None, meridiem: str | None) -> str | None:
    hour = int(hour_str)
    minute = int(minute_str) if minute_str else 0
    if not (0 <= minute <= 59):
        return None
    if meridiem is not None:
        if not (1 <= hour <= 12):
            return None
        meridiem = meridiem.strip().lower()
        if meridiem == "am":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12
    else:
        if not (0 <= hour <= 23):
            return None
    return f"{hour:02d}:{minute:02d}"


def _resolve_range(match: re.Match) -> tuple[str, str | None] | None:
    """Resolve a `_RANGE_TOKEN` match to (start, end).

    `end` is None when the token was range-shaped but its end did not
    follow its start (no midnight crossing is ever assumed); `start` is
    still returned so the caller can fall back to a start-only result.
    Returns None only when neither side can be resolved as a time at all.
    """

    mer1 = match.group("mer1")
    mer2 = match.group("mer2")
    # A single trailing meridiem governs both ends when the first side has
    # none of its own.
    eff_mer1 = mer2 if mer1 is None and mer2 is not None else mer1

    start = _resolve_side(match.group("h1"), match.group("m1"), eff_mer1)
    end = _resolve_side(match.group("h2"), match.group("m2"), mer2)
    if start is None or end is None:
        return None
    if end <= start:
        return (start, None)
    return (start, end)


def _clean(text: str) -> str:
    text = re.sub(r"\s{2,}", " ", text)
    text = text.strip()
    text = _TRAILING_PUNCT.sub("", text).strip()
    text = _LEADING_PUNCT.sub("", text).strip()
    return text


def parse_name_time(name: str) -> NameTimeResult:
    """Find the first whole-token time (or time range) in `name`.

    Tries a range first (two start-forms joined by ``-``, ``–``, or ``
    to ``), falling back to a single start time when no range is found.
    Returns a `NameTimeResult` with the matched token removed from the
    name (whitespace/punctuation cleaned up). When no valid token is
    found, returns the name unchanged with `start` and `end` set to None.
    """
    for match in _RANGE_TOKEN.finditer(name):
        resolved = _resolve_range(match)
        if resolved is None:
            continue
        start, end = resolved
        stripped = name[: match.start()] + name[match.end() :]
        return NameTimeResult(stripped_name=_clean(stripped), start=start, end=end)

    for match in _TIME_TOKEN.finditer(name):
        start = _to_24h(match)
        if start is None:
            continue
        stripped = name[: match.start()] + name[match.end() :]
        return NameTimeResult(stripped_name=_clean(stripped), start=start)

    return NameTimeResult(stripped_name=name, start=None)
