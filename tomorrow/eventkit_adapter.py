from __future__ import annotations

from datetime import date, datetime, time, timedelta
import sys
import threading
from typing import Callable

from tomorrow.icloud import IcloudConfig, RawEvent, RawReminder


def _components_time(components: object) -> time | None:
    """Read hour/minute off NSDateComponents, or None for a date-only reminder.

    Unset components come back as NSNotFound (a huge sentinel, not 0), so the
    values have to be range-checked rather than truth-tested.
    """
    try:
        hour = components.hour()
        minute = components.minute()
        if not (0 <= hour <= 23) or not (0 <= minute <= 59):
            return None
        return time(hour, minute)
    except Exception:
        return None


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


def _calculate_duration_minutes(start: object, end: object) -> int:
    diff = end - start  # type: ignore[operator]
    if isinstance(diff, timedelta):
        return int(diff.total_seconds() / 60)
    return int(diff / 60)


def fetch_eventkit_records(
    config: IcloudConfig,
    plan_date: date,
    *,
    store: object | None = None,
) -> tuple[list[RawEvent], list[RawReminder]]:
    """Talk to macOS EventKit for the given Plan date.

    Returns (events, reminders) fetched via EventKit, or ([], []) if unavailable.
    """
    try:
        if sys.platform != "darwin" and store is None:
            return [], []

        try:
            from EventKit import (  # type: ignore[import-not-found]
                EKEntityTypeEvent,
                EKEntityTypeReminder,
                EKEventStore,
            )
        except Exception:
            if store is None:
                return [], []
            EKEntityTypeEvent = 0
            EKEntityTypeReminder = 1
            EKEventStore = None

        if store is None:
            if EKEventStore is None:
                return [], []
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
                duration_minutes=_calculate_duration_minutes(
                    ek_event.startDate(), ek_event.endDate()
                ),
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
                    due_time = None
                    if due is not None and due.year() and due.month() and due.day():
                        due_date = date(due.year(), due.month(), due.day())
                        due_time = _components_time(due)
                    notes = ek_reminder.notes()
                    reminders.append(
                        RawReminder(
                            title=str(ek_reminder.title()),
                            list_name=str(ek_reminder.calendar().title()),
                            due_date=due_date,
                            due_time=due_time,
                            completed=bool(ek_reminder.isCompleted()),
                            note=str(notes) if notes else None,
                        )
                    )
                completion_event.set()

            store.fetchRemindersMatchingPredicate_completion_(reminder_predicate, _handle)
            completion_event.wait(timeout=10)

        return events, reminders
    except Exception:
        return [], []


def list_available_calendars(
    *,
    fetcher: Callable[[], tuple[list[str], list[str]]] | None = None,
    store: object | None = None,
) -> tuple[list[str], list[str]] | None:
    """List the calendar and reminder-list names EventKit currently has access to."""
    try:
        if fetcher is not None:
            return fetcher()

        if sys.platform != "darwin" and store is None:
            return None

        try:
            from EventKit import (  # type: ignore[import-not-found]
                EKEntityTypeEvent,
                EKEntityTypeReminder,
                EKEventStore,
            )
        except Exception:
            if store is None:
                return None
            EKEntityTypeEvent = 0
            EKEntityTypeReminder = 1
            EKEventStore = None

        if store is None:
            if EKEventStore is None:
                return None
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
