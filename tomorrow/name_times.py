"""Pure grammar for detecting a time (or a time range, or a duration)
written inside an item's name.

Given a name such as ``"Tutoring 16:30"``, `parse_name_time` finds the first
whole-token time, reports it, and returns the name with that token (and any
leftover whitespace/punctuation around it) removed. Given a name such as
``"Tutoring 16:30-18:00"``, it finds the range instead and reports both
ends, stripping the whole range token from the name. Given a name such as
``"Gym 45m"`` or ``"Tutoring 16:30 (90 min)"``, it also finds a duration
alongside (or instead of) a start.

Ticket #78 detected a single start time. Ticket #79 added range detection:
two start-forms joined by ``-``, an en dash ``–``, or the spaced word
`` to ``, with a single trailing meridiem allowed to govern both ends
(``Squash 4-6pm`` -> 16:00-18:00). A range whose end is not after its start
is discarded -- the token is still stripped from the name (it was still
recognized as range-shaped), but only `start` survives; no midnight
crossing is ever assumed. Ticket #80 added duration detection (`90m`,
`90min`, `1h`, `1h30`, `1.5h`, optionally parenthesised), which can appear
alongside a plain start (`Tutoring 16:30 (90 min)`) or on its own
(`Gym 45m`). A range and a duration are mutually exclusive shapes: a range
token, once matched, is the whole answer. No filesystem, no clock, no
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
    is a "HH:MM" 24-hour string, or None when no start was found. `end` is
    likewise a "HH:MM" string when a valid range was found (end strictly
    after start), or None otherwise -- including when a range-shaped token
    was found but discarded because its end did not follow its start.
    `duration_minutes` is an int, or None when no duration was found (a
    range never carries a duration alongside it).
    """

    stripped_name: str
    start: str | None = None
    end: str | None = None
    duration_minutes: int | None = None

    @property
    def matched(self) -> bool:
        return (
            self.start is not None
            or self.end is not None
            or self.duration_minutes is not None
        )


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
    """Find the first whole-token time (or range, or duration) in `name`.

    Tries a range first (two start-forms joined by ``-``, ``–``, or ``
    to ``); a range, once found, is the whole answer (no duration is
    looked for alongside it). Otherwise looks for a single start time and,
    independently, a duration, either or both of which may be present.
    Returns a `NameTimeResult` with the matched token(s) removed from the
    name (whitespace/punctuation cleaned up). When nothing is found,
    returns the name unchanged with everything set to None.
    """
    for match in _RANGE_TOKEN.finditer(name):
        resolved = _resolve_range(match)
        if resolved is None:
            continue
        start, end = resolved
        stripped = name[: match.start()] + name[match.end() :]
        return NameTimeResult(stripped_name=_clean(stripped), start=start, end=end)

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
