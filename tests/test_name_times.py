import pytest

from tomorrow.name_times import NameTimeResult, parse_name_time

ACCEPTED = [
    # (name, expected stripped name, expected start "HH:MM")
    ("Tutoring 16:30", "Tutoring", "16:30"),
    ("Gym 6pm", "Gym", "18:00"),
    ("Gym 6PM", "Gym", "18:00"),
    ("Call 4:30pm", "Call", "16:30"),
    ("Call 4:30 pm", "Call", "16:30"),
    ("Call 4:30PM", "Call", "16:30"),
    ("Lunch 12pm", "Lunch", "12:00"),
    ("Flight 12am", "Flight", "00:00"),
    ("16:30 Tutoring", "Tutoring", "16:30"),
    ("Meet Sam 16:30 at the café", "Meet Sam at the café", "16:30"),
    ("Call Sam 16:30 about the 9:00 handover", "Call Sam about the 9:00 handover", "16:30"),
    ("Tutoring - 16:30", "Tutoring", "16:30"),
    ("Tutoring, 16:30", "Tutoring", "16:30"),
    ("09:00 - Standup", "Standup", "09:00"),
    ("Call 9am", "Call", "09:00"),
]

REJECTED = [
    "Invoice 1630",
    "Sleep 8",
    "Lunch 16.30",
    "Call 4 p.m.",
    "Invoice 25:70",
    "Just a name",
    "",
]


@pytest.mark.parametrize("name,expected_stripped,expected_start", ACCEPTED)
def test_accepted_forms(name: str, expected_stripped: str, expected_start: str) -> None:
    result = parse_name_time(name)
    assert result.start == expected_start
    assert result.stripped_name == expected_stripped
    assert result.matched is True


@pytest.mark.parametrize("name", REJECTED)
def test_rejected_forms_leave_name_untouched(name: str) -> None:
    result = parse_name_time(name)
    assert result.start is None
    assert result.stripped_name == name
    assert result.matched is False


def test_result_is_a_plain_dataclass_with_start_field() -> None:
    result = parse_name_time("Gym 6pm")
    assert isinstance(result, NameTimeResult)
    assert result.start == "18:00"


def test_whole_token_matching_does_not_match_inside_other_tokens() -> None:
    result = parse_name_time("Room16:30A meeting")
    assert result.start is None
    assert result.stripped_name == "Room16:30A meeting"


def test_whitespace_cleanup_collapses_double_spaces() -> None:
    result = parse_name_time("Tutoring  16:30  today")
    assert result.stripped_name == "Tutoring today"
    assert result.start == "16:30"


DURATION_WITH_START = [
    # (name, expected stripped name, expected start, expected duration_minutes)
    ("Tutoring 16:30 (90 min)", "Tutoring", "16:30", 90),
    ("Tutoring 16:30 (90min)", "Tutoring", "16:30", 90),
    ("Tutoring 16:30 (1h30)", "Tutoring", "16:30", 90),
    ("Tutoring 16:30 (1.5h)", "Tutoring", "16:30", 90),
]

DURATION_ONLY = [
    # (name, expected stripped name, expected duration_minutes)
    ("Gym 45m", "Gym", 45),
    ("Gym 45min", "Gym", 45),
    ("Gym 90m", "Gym", 90),
    ("Gym (90m)", "Gym", 90),
    ("Gym 1h", "Gym", 60),
    ("Gym 1h30", "Gym", 90),
    ("Gym 1.5h", "Gym", 90),
    ("Gym (1.5h)", "Gym", 90),
]

DURATION_REJECTED = [
    "Gym 90",
    "Gym 8",
]


@pytest.mark.parametrize(
    "name,expected_stripped,expected_start,expected_duration", DURATION_WITH_START
)
def test_duration_alongside_start(
    name: str, expected_stripped: str, expected_start: str, expected_duration: int
) -> None:
    result = parse_name_time(name)
    assert result.start == expected_start
    assert result.duration_minutes == expected_duration
    assert result.stripped_name == expected_stripped
    assert result.matched is True


@pytest.mark.parametrize("name,expected_stripped,expected_duration", DURATION_ONLY)
def test_duration_without_start(
    name: str, expected_stripped: str, expected_duration: int
) -> None:
    result = parse_name_time(name)
    assert result.start is None
    assert result.duration_minutes == expected_duration
    assert result.stripped_name == expected_stripped
    assert result.matched is True


@pytest.mark.parametrize("name", DURATION_REJECTED)
def test_bare_number_is_not_a_duration(name: str) -> None:
    result = parse_name_time(name)
    assert result.duration_minutes is None
    assert result.start is None
    assert result.stripped_name == name
    assert result.matched is False


def test_result_duration_field_defaults_to_none() -> None:
    result = parse_name_time("Just a name")
    assert result.duration_minutes is None
