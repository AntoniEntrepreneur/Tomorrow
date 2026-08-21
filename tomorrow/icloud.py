from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable
import threading
import tomllib

from tomorrow.domain import Anchor

ICLOUD_SOURCE = "icloud"


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


@dataclass(frozen=True)
class ImportedItem:
    """A calendar/reminder item classified as ready to become an Anchor or Draft."""

    name: str
    start: time | None = None
    duration_minutes: int | None = None
    source: str = ICLOUD_SOURCE


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
    drafts: list[ImportedItem] = []
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
        if _overlaps_any(start_time, end_time, placed_anchors):
            drafts.append(ImportedItem(name=event.title))
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
        if reminder.due_date is None:
            continue
        if reminder.due_date != plan_date:
            continue
        drafts.append(ImportedItem(name=reminder.title))

    return ClassifiedIcloudItems(anchors=anchors, drafts=drafts)


def _calendars_of_type(store: object, entity_type: object) -> list:
    return list(store.calendarsForEntityType_(entity_type))


def _request_access(store: object) -> None:
    """Trigger the macOS permission prompts for Calendar and Reminders access.

    EventKit only shows the system dialog the first time these are called; it
    never appears just from enumerating calendars. Blocks until the user
    responds (or times out), since callers need calendars to be readable
    immediately after.
    """

    for request in (
        getattr(store, "requestFullAccessToEventsWithCompletion_", None),
        getattr(store, "requestFullAccessToRemindersWithCompletion_", None),
    ):
        if request is None:
            continue
        done = threading.Event()
        request(lambda granted, error, done=done: done.set())
        done.wait(timeout=30)


def _fetch_from_eventkit(config: IcloudConfig, plan_date: date) -> tuple[list[RawEvent], list[RawReminder]]:
    """Talk to macOS EventKit for the given Plan date. Not itself under test."""

    from EventKit import (  # type: ignore[import-not-found]
        EKEntityTypeEvent,
        EKEntityTypeReminder,
        EKEventStore,
    )

    store = EKEventStore.alloc().init()
    _request_access(store)

    calendars = [
        calendar
        for calendar in _calendars_of_type(store, EKEntityTypeEvent)
        if calendar.title() in config.calendars
    ]
    reminder_calendars = [
        calendar
        for calendar in _calendars_of_type(store, EKEntityTypeReminder)
        if calendar.title() in config.reminder_lists
    ]

    start_of_day = datetime.combine(plan_date, time.min)
    end_of_day = start_of_day + timedelta(days=1)
    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        start_of_day, end_of_day, calendars
    )
    ek_events = store.eventsMatchingPredicate_(predicate)
    events = [
        RawEvent(
            title=str(ek_event.title()),
            calendar=str(ek_event.calendar().title()),
            start=ek_event.startDate(),
            duration_minutes=int((ek_event.endDate() - ek_event.startDate()) / 60),
            all_day=bool(ek_event.isAllDay()),
        )
        for ek_event in ek_events
    ]

    reminders: list[RawReminder] = []
    if reminder_calendars:
        reminder_predicate = store.predicateForRemindersInCalendars_(reminder_calendars)
        completion_event = threading.Event()

        def _handle(ek_reminders: object) -> None:
            for ek_reminder in ek_reminders or []:
                due = ek_reminder.dueDateComponents()
                due_date = None
                if due is not None and due.year() and due.month() and due.day():
                    due_date = date(due.year(), due.month(), due.day())
                reminders.append(
                    RawReminder(
                        title=str(ek_reminder.title()),
                        list_name=str(ek_reminder.calendar().title()),
                        due_date=due_date,
                    )
                )
            completion_event.set()

        store.fetchRemindersMatchingPredicate_completion_(reminder_predicate, _handle)
        completion_event.wait(timeout=10)

    return events, reminders


def try_import_icloud_items(
    data_dir: Path,
    plan_date: date,
    *,
    existing_anchors: list[Anchor] | None = None,
    fetch: FetchFn = _fetch_from_eventkit,
) -> ClassifiedIcloudItems:
    empty = ClassifiedIcloudItems(anchors=[], drafts=[])
    config = load_icloud_config(data_dir)
    if config is None:
        return empty
    try:
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


def list_available_calendars(
    *, fetcher: Callable[[], tuple[list[str], list[str]]] | None = None
) -> tuple[list[str], list[str]] | None:
    """List the calendar and reminder-list names EventKit currently has access to."""

    try:
        if fetcher is not None:
            return fetcher()
        from EventKit import (  # type: ignore[import-not-found]
            EKEntityTypeEvent,
            EKEntityTypeReminder,
            EKEventStore,
        )

        store = EKEventStore.alloc().init()
        _request_access(store)
        calendars = sorted(
            str(calendar.title()) for calendar in _calendars_of_type(store, EKEntityTypeEvent)
        )
        reminder_lists = sorted(
            str(calendar.title())
            for calendar in _calendars_of_type(store, EKEntityTypeReminder)
        )
        return calendars, reminder_lists
    except Exception:
        return None
