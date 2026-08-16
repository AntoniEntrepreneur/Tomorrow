import json
from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.error import URLError

from tomorrow.weather import (
    WeatherLocation,
    fetch_weather_one_liner,
    format_weather_one_liner,
    load_weather_location,
    load_weather_name,
    try_fetch_weather,
)


def test_load_weather_location_reads_latitude_and_longitude(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "weather.toml").write_text(
        'latitude = 52.23\nlongitude = 21.01\n', encoding="utf-8"
    )

    location = load_weather_location(data_dir)

    assert location == WeatherLocation(latitude=52.23, longitude=21.01)


def test_load_weather_location_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert load_weather_location(tmp_path / "data") is None


def test_load_weather_location_returns_none_for_invalid_toml(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "weather.toml").write_text("not valid toml [[[\n", encoding="utf-8")

    assert load_weather_location(data_dir) is None


def test_format_weather_one_liner_uses_high_low_and_short_condition() -> None:
    one_liner = format_weather_one_liner(low_c=18.2, high_c=24.6, weather_code=2)

    assert one_liner == "18° / 25° · partly cloudy"


def test_fetch_weather_one_liner_parses_open_meteo_daily_payload() -> None:
    payload = {
        "daily": {
            "time": ["2026-08-11"],
            "temperature_2m_min": [17.8],
            "temperature_2m_max": [24.1],
            "weathercode": [0],
        }
    }

    def fake_opener(_request):
        return BytesIO(json.dumps(payload).encode("utf-8"))

    location = WeatherLocation(latitude=52.23, longitude=21.01)
    one_liner = fetch_weather_one_liner(
        location, date(2026, 8, 11), opener=fake_opener
    )

    assert one_liner == "18° / 24° · clear"


def test_fetch_weather_one_liner_returns_none_on_network_error() -> None:
    def failing_opener(_request):
        raise URLError("offline")

    location = WeatherLocation(latitude=52.23, longitude=21.01)

    assert (
        fetch_weather_one_liner(location, date(2026, 8, 11), opener=failing_opener)
        is None
    )


def test_fetch_weather_one_liner_returns_none_on_timeout() -> None:
    def timed_out_opener(_request):
        raise TimeoutError("slow")

    location = WeatherLocation(latitude=52.23, longitude=21.01)

    assert (
        fetch_weather_one_liner(location, date(2026, 8, 11), opener=timed_out_opener)
        is None
    )


def test_try_fetch_weather_skips_network_when_location_missing(tmp_path: Path) -> None:
    called = False

    def fake_opener(_request):
        nonlocal called
        called = True
        raise AssertionError("should not fetch without location")

    assert try_fetch_weather(tmp_path / "data", date(2026, 8, 11), opener=fake_opener) is None
    assert not called


def test_try_fetch_weather_loads_location_and_fetches(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "weather.toml").write_text(
        'latitude = 52.23\nlongitude = 21.01\n', encoding="utf-8"
    )
    payload = {
        "daily": {
            "time": ["2026-08-11"],
            "temperature_2m_min": [16.0],
            "temperature_2m_max": [22.0],
            "weathercode": [61],
        }
    }

    def fake_opener(_request):
        return BytesIO(json.dumps(payload).encode("utf-8"))

    one_liner = try_fetch_weather(data_dir, date(2026, 8, 11), opener=fake_opener)

    assert one_liner == "16° / 22° · rain"


def test_load_weather_name_reads_optional_display_name(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "weather.toml").write_text(
        'name = "Warsaw"\nlatitude = 52.23\nlongitude = 21.01\n',
        encoding="utf-8",
    )

    assert load_weather_name(data_dir) == "Warsaw"
