from datetime import date, datetime, time, timedelta
import inspect
from pathlib import Path
import sys
import pytest

from tomorrow.icloud import IcloudConfig, RawEvent, RawReminder
import tomorrow.icloud as icloud_mod


def test_icloud_module_is_completely_free_of_eventkit_and_pyobjc() -> None:
    source = inspect.getsource(icloud_mod)
    assert "EventKit" not in source
    assert "objc" not in source
    assert "PyObjC" not in source
    assert "threading" not in source


def test_components_time_parses_valid_hour_and_minute() -> None:
    from tomorrow.eventkit_adapter import _components_time

    class DummyComponents:
        def hour(self):
            return 14

        def minute(self):
            return 30

    assert _components_time(DummyComponents()) == time(14, 30)


def test_components_time_returns_none_for_sentinel_or_invalid_values() -> None:
    from tomorrow.eventkit_adapter import _components_time

    class DummyComponents:
        def hour(self):
            return 9223372036854775807  # NSNotFound

        def minute(self):
            return 0

    assert _components_time(DummyComponents()) is None


def test_list_available_calendars_uses_fetcher_when_provided() -> None:
    from tomorrow.eventkit_adapter import list_available_calendars

    calendars, reminders = list_available_calendars(
        fetcher=lambda: (["Work", "Personal"], ["Errands"])
    )
    assert calendars == ["Work", "Personal"]
    assert reminders == ["Errands"]


def test_list_available_calendars_returns_none_when_eventkit_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tomorrow.eventkit_adapter import list_available_calendars

    monkeypatch.setitem(sys.modules, "EventKit", None)
    assert list_available_calendars() is None


def test_list_available_calendars_with_mock_store() -> None:
    from tomorrow.eventkit_adapter import list_available_calendars

    class DummyCalendar:
        def __init__(self, title: str):
            self._title = title

        def title(self):
            return self._title

    class DummyStore:
        def calendarsForEntityType_(self, entity_type: int):
            if entity_type == 0:  # Event
                return [DummyCalendar("Work"), DummyCalendar("Personal")]
            return [DummyCalendar("Errands")]

    result = list_available_calendars(store=DummyStore())
    assert result == (["Personal", "Work"], ["Errands"])


def test_fetch_eventkit_records_returns_empty_when_eventkit_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tomorrow.eventkit_adapter import fetch_eventkit_records

    monkeypatch.setitem(sys.modules, "EventKit", None)
    config = IcloudConfig(calendars=("Work",), reminder_lists=("Errands",))
    events, reminders = fetch_eventkit_records(config, date(2026, 8, 11))
    assert events == []
    assert reminders == []


def test_fetch_eventkit_records_with_mock_store() -> None:
    from tomorrow.eventkit_adapter import fetch_eventkit_records

    plan_date = date(2026, 8, 11)

    class DummyCalendar:
        def __init__(self, title: str):
            self._title = title

        def title(self):
            return self._title

    class DummyEvent:
        def title(self):
            return "Team Sync"

        def calendar(self):
            return DummyCalendar("Work")

        def startDate(self):
            return datetime(2026, 8, 11, 10, 0)

        def endDate(self):
            return datetime(2026, 8, 11, 10, 30)

        def isAllDay(self):
            return False

    class DummyComponents:
        def year(self):
            return 2026

        def month(self):
            return 8

        def day(self):
            return 11

        def hour(self):
            return 15

        def minute(self):
            return 0

    class DummyReminder:
        def title(self):
            return "Call dentist"

        def calendar(self):
            return DummyCalendar("Errands")

        def dueDateComponents(self):
            return DummyComponents()

        def notes(self):
            return "Dentist note"

        def isCompleted(self):
            return False

    class DummyStore:
        def calendarsForEntityType_(self, entity_type: int):
            if entity_type == 0:
                return [DummyCalendar("Work")]
            return [DummyCalendar("Errands")]

        def predicateForEventsWithStartDate_endDate_calendars_(self, start, end, calendars):
            return "dummy-predicate"

        def eventsMatchingPredicate_(self, predicate):
            return [DummyEvent()]

        def predicateForRemindersInCalendars_(self, calendars):
            return "dummy-reminders-predicate"

        def fetchRemindersMatchingPredicate_completion_(self, predicate, callback):
            callback([DummyReminder()])

    config = IcloudConfig(calendars=("Work",), reminder_lists=("Errands",))
    events, reminders = fetch_eventkit_records(config, plan_date, store=DummyStore())

    assert len(events) == 1
    assert events[0] == RawEvent(
        title="Team Sync",
        calendar="Work",
        start=datetime(2026, 8, 11, 10, 0),
        duration_minutes=30,
        all_day=False,
    )

    assert len(reminders) == 1
    assert reminders[0] == RawReminder(
        title="Call dentist",
        list_name="Errands",
        due_date=date(2026, 8, 11),
        due_time=time(15, 0),
        completed=False,
        note="Dentist note",
    )
