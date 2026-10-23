from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
import tomllib
from typing import Callable

from tomorrow.domain import Anchor

ICLOUD_SOURCE = "icloud"

# A reminder carries no duration, so a timed one is anchored at this length.
REMINDER_ANCHOR_MINUTES = 30


@dataclass(frozen=True)
class IcloudConfig:
    calendars: tuple[str, ...]
    reminder_lists: tuple[str, ...]


@dataclass(frozen=True)
class RawEvent:
    """A plain-data timed or all-day calendar event, as returned by the fetch wrapper."""

    title: str
    calendar: str
    start: datetime
    duration_minutes: int
    all_day: bool = False


@dataclass(frozen=True)
class RawReminder:
    """A plain-data reminder, as returned by the fetch wrapper."""

    title: str
    list_name: str
    due_date: date | None
    due_time: time | None = None
    completed: bool = False
    note: str | None = None


@dataclass(frozen=True)
class ImportedItem:
    """A calendar/reminder item classified as ready to become an Anchor or Draft."""

    name: str
    start: time | None = None
    duration_minutes: int | None = None
    source: str = ICLOUD_SOURCE
    note: str | None = None
    overdue: bool = False


@dataclass(frozen=True)
class ClassifiedIcloudItems:
    anchors: list[ImportedItem] = field(default_factory=list)
    drafts: list[ImportedItem] = field(default_factory=list)


FetchFn = Callable[[IcloudConfig, date], tuple[list[RawEvent], list[RawReminder]]]


def load_icloud_config(data_dir: Path) -> IcloudConfig | None:
    path = data_dir / "icloud.toml"
    if not path.exists():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return None
    calendars = data.get("calendars")
    reminder_lists = data.get("reminder_lists")
    if not isinstance(calendars, list) or not isinstance(reminder_lists, list):
        return None
    try:
        return IcloudConfig(
            calendars=tuple(str(name) for name in calendars),
            reminder_lists=tuple(str(name) for name in reminder_lists),
        )
    except (TypeError, ValueError):
        return None


def _anchor_end(start: time, duration_minutes: int) -> time:
    combined = datetime.combine(date(2000, 1, 1), start) + timedelta(minutes=duration_minutes)
    return combined.time()


def _overlaps_any(start: time, end: time, anchors: list[Anchor]) -> bool:
    return any(start < anchor.end and anchor.start < end for anchor in anchors)


def classify_icloud_items(
    *,
    existing_anchors: list[Anchor],
    events: list[RawEvent],
    reminders: list[RawReminder],
    plan_date: date,
    config: IcloudConfig,
) -> ClassifiedIcloudItems:
    # `events` is already scoped to occurrences starting on `plan_date` by the
    # fetch wrapper's date-bounded predicate, so a recurring event's other
    # occurrences never reach this function.
    anchors: list[ImportedItem] = []
    day_of_drafts: list[ImportedItem] = []
    overdue_draft_entries: list[tuple[tuple[date, time], ImportedItem]] = []
    placed_anchors = list(existing_anchors)

    for event in events:
        if event.calendar not in config.calendars:
            continue
        if event.all_day:
            continue
        if event.start.date() != plan_date:
            continue
        start_time = event.start.time()
        end_time = _anchor_end(start_time, event.duration_minutes)
        # A calendar-derived Draft never carries a note: invite noise and
        # meeting links must not reach the Plan.
        if _overlaps_any(start_time, end_time, placed_anchors):
            day_of_drafts.append(ImportedItem(name=event.title))
            continue
        item = ImportedItem(
            name=event.title, start=start_time, duration_minutes=event.duration_minutes
        )
        anchors.append(item)
        placed_anchors.append(
            Anchor(
                name=event.title,
                start=start_time,
                duration=timedelta(minutes=event.duration_minutes),
            )
        )

    for reminder in reminders:
        if reminder.list_name not in config.reminder_lists:
            continue
        if reminder.completed:
            continue
        if reminder.due_date is None:
            continue
        if reminder.due_date > plan_date:
            continue
        if reminder.due_date < plan_date:
            item = ImportedItem(
                name=reminder.title,
                note=reminder.note,
                overdue=True,
            )
            sort_key = (reminder.due_date, reminder.due_time or time.min)
            overdue_draft_entries.append((sort_key, item))
            continue
        # A reminder scheduled at a time of day is an Anchor, the same as a
        # timed event; a date-only reminder has no place to sit, so it is a
        # Draft. A timed reminder that collides with something already placed
        # falls back to a Draft, again matching how events are handled.
        if reminder.due_time is None:
            day_of_drafts.append(ImportedItem(name=reminder.title, note=reminder.note))
            continue
        end_time = _anchor_end(reminder.due_time, REMINDER_ANCHOR_MINUTES)
        if _overlaps_any(reminder.due_time, end_time, placed_anchors):
            day_of_drafts.append(ImportedItem(name=reminder.title, note=reminder.note))
            continue
        anchors.append(
            ImportedItem(
                name=reminder.title,
                start=reminder.due_time,
                duration_minutes=REMINDER_ANCHOR_MINUTES,
            )
        )
        placed_anchors.append(
            Anchor(
                name=reminder.title,
                start=reminder.due_time,
                duration=timedelta(minutes=REMINDER_ANCHOR_MINUTES),
            )
        )

    overdue_draft_entries.sort(key=lambda entry: entry[0])
    drafts = [item for _, item in overdue_draft_entries] + day_of_drafts
    return ClassifiedIcloudItems(anchors=anchors, drafts=drafts)


def try_import_icloud_items(
    data_dir: Path,
    plan_date: date,
    *,
    existing_anchors: list[Anchor] | None = None,
    fetch: FetchFn | None = None,
) -> ClassifiedIcloudItems:
    empty = ClassifiedIcloudItems(anchors=[], drafts=[])
    config = load_icloud_config(data_dir)
    if config is None:
        return empty
    try:
        if fetch is None:
            from tomorrow.eventkit_adapter import fetch_eventkit_records

            fetch = fetch_eventkit_records
        events, reminders = fetch(config, plan_date)
        return classify_icloud_items(
            existing_anchors=existing_anchors or [],
            events=events,
            reminders=reminders,
            plan_date=plan_date,
            config=config,
        )
    except Exception:
        return empty
