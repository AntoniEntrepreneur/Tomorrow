from datetime import date, datetime, time, timedelta
from pathlib import Path

from tomorrow.domain import Anchor
from tomorrow.icloud import (
    ClassifiedIcloudItems,
    IcloudConfig,
    RawEvent,
    RawReminder,
    classify_icloud_items,
    load_icloud_config,
    try_import_icloud_items,
)


def test_load_icloud_config_reads_calendars_and_reminder_lists(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "icloud.toml").write_text(
        'calendars = ["Work", "Personal"]\nreminder_lists = ["Errands"]\n',
        encoding="utf-8",
    )

    config = load_icloud_config(data_dir)

    assert config == IcloudConfig(calendars=("Work", "Personal"), reminder_lists=("Errands",))


def test_load_icloud_config_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert load_icloud_config(tmp_path / "data") is None


def test_load_icloud_config_returns_none_for_invalid_toml(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "icloud.toml").write_text("not valid toml [[[\n", encoding="utf-8")

    assert load_icloud_config(data_dir) is None


def test_load_icloud_config_returns_none_when_fields_missing(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "icloud.toml").write_text('calendars = ["Work"]\n', encoding="utf-8")

    assert load_icloud_config(data_dir) is None


CONFIG = IcloudConfig(calendars=("Work",), reminder_lists=("Errands",))
PLAN_DATE = date(2026, 8, 11)


def test_classify_timed_event_on_plan_date_becomes_an_anchor() -> None:
    events = [
        RawEvent(
            title="Standup",
            calendar="Work",
            start=datetime(2026, 8, 11, 9, 0),
            duration_minutes=30,
        )
    ]

    result = classify_icloud_items(
        existing_anchors=[], events=events, reminders=[], plan_date=PLAN_DATE, config=CONFIG
    )

    assert len(result.anchors) == 1
    assert result.anchors[0].name == "Standup"
    assert result.anchors[0].start == time(9, 0)
    assert result.anchors[0].duration_minutes == 30
    assert result.anchors[0].source == "icloud"
    assert result.drafts == []


def test_classify_ignores_calendars_not_in_config() -> None:
    events = [
        RawEvent(
            title="Birthday",
            calendar="Birthdays",
            start=datetime(2026, 8, 11, 9, 0),
            duration_minutes=1440,
        )
    ]

    result = classify_icloud_items(
        existing_anchors=[], events=events, reminders=[], plan_date=PLAN_DATE, config=CONFIG
    )

    assert result.anchors == []
    assert result.drafts == []


def test_classify_all_day_event_is_skipped() -> None:
    events = [
        RawEvent(
            title="Conference",
            calendar="Work",
            start=datetime(2026, 8, 11, 0, 0),
            duration_minutes=1440,
            all_day=True,
        )
    ]

    result = classify_icloud_items(
        existing_anchors=[], events=events, reminders=[], plan_date=PLAN_DATE, config=CONFIG
    )

    assert result.anchors == []
    assert result.drafts == []


def test_classify_multi_day_event_not_starting_on_plan_date_is_skipped() -> None:
    events = [
        RawEvent(
            title="Trip",
            calendar="Work",
            start=datetime(2026, 8, 10, 9, 0),
            duration_minutes=48 * 60,
        )
    ]

    result = classify_icloud_items(
        existing_anchors=[], events=events, reminders=[], plan_date=PLAN_DATE, config=CONFIG
    )

    assert result.anchors == []
    assert result.drafts == []


def test_classify_event_overlapping_existing_anchor_becomes_a_draft() -> None:
    existing = [Anchor(name="Gym", start=time(9, 0), duration=timedelta(minutes=60))]
    events = [
        RawEvent(
            title="Dentist",
            calendar="Work",
            start=datetime(2026, 8, 11, 9, 30),
            duration_minutes=30,
        )
    ]

    result = classify_icloud_items(
        existing_anchors=existing, events=events, reminders=[], plan_date=PLAN_DATE, config=CONFIG
    )

    assert result.anchors == []
    assert len(result.drafts) == 1
    assert result.drafts[0].name == "Dentist"
    assert result.drafts[0].source == "icloud"


def test_classify_reminder_due_on_plan_date_becomes_a_draft() -> None:
    reminders = [RawReminder(title="Call dentist", list_name="Errands", due_date=PLAN_DATE)]

    result = classify_icloud_items(
        existing_anchors=[], events=[], reminders=reminders, plan_date=PLAN_DATE, config=CONFIG
    )

    assert result.anchors == []
    assert len(result.drafts) == 1
    assert result.drafts[0].name == "Call dentist"
    assert result.drafts[0].start is None


def test_classify_reminder_with_no_due_date_is_excluded() -> None:
    reminders = [RawReminder(title="Someday", list_name="Errands", due_date=None)]

    result = classify_icloud_items(
        existing_anchors=[], events=[], reminders=reminders, plan_date=PLAN_DATE, config=CONFIG
    )

    assert result.drafts == []


def test_classify_reminder_due_on_a_different_date_is_excluded() -> None:
    reminders = [
        RawReminder(title="Later", list_name="Errands", due_date=date(2026, 8, 12))
    ]

    result = classify_icloud_items(
        existing_anchors=[], events=[], reminders=reminders, plan_date=PLAN_DATE, config=CONFIG
    )

    assert result.drafts == []


def test_classify_reminder_list_not_in_config_is_excluded() -> None:
    reminders = [
        RawReminder(title="Off-list", list_name="Someday Maybe", due_date=PLAN_DATE)
    ]

    result = classify_icloud_items(
        existing_anchors=[], events=[], reminders=reminders, plan_date=PLAN_DATE, config=CONFIG
    )

    assert result.drafts == []


def test_try_import_icloud_items_returns_empty_when_config_missing(tmp_path: Path) -> None:
    called = False

    def fake_fetch(_config, _plan_date):
        nonlocal called
        called = True
        return [], []

    result = try_import_icloud_items(
        tmp_path / "data", PLAN_DATE, existing_anchors=[], fetch=fake_fetch
    )

    assert result == ClassifiedIcloudItems(anchors=[], drafts=[])
    assert not called


def test_try_import_icloud_items_returns_empty_when_fetch_raises(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "icloud.toml").write_text(
        'calendars = ["Work"]\nreminder_lists = ["Errands"]\n', encoding="utf-8"
    )

    def failing_fetch(_config, _plan_date):
        raise RuntimeError("EventKit permission denied")

    result = try_import_icloud_items(
        data_dir, PLAN_DATE, existing_anchors=[], fetch=failing_fetch
    )

    assert result == ClassifiedIcloudItems(anchors=[], drafts=[])


def test_try_import_icloud_items_fetches_and_classifies(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "icloud.toml").write_text(
        'calendars = ["Work"]\nreminder_lists = ["Errands"]\n', encoding="utf-8"
    )

    def fake_fetch(config, plan_date):
        assert config == IcloudConfig(calendars=("Work",), reminder_lists=("Errands",))
        assert plan_date == PLAN_DATE
        return (
            [
                RawEvent(
                    title="Standup",
                    calendar="Work",
                    start=datetime(2026, 8, 11, 9, 0),
                    duration_minutes=15,
                )
            ],
            [],
        )

    result = try_import_icloud_items(
        data_dir, PLAN_DATE, existing_anchors=[], fetch=fake_fetch
    )

    assert len(result.anchors) == 1
    assert result.anchors[0].name == "Standup"
