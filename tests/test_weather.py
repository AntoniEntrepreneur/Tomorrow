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


def test_weather_code_emoji_maps_wmo_codes() -> None:
    from tomorrow.weather import weather_code_emoji

    assert weather_code_emoji(0) == "☀️"
    assert weather_code_emoji(1) == "☀️"
    assert weather_code_emoji(2) == "⛅"
    assert weather_code_emoji(3) == "☁️"
    assert weather_code_emoji(45) == "🌫️"
    assert weather_code_emoji(61) == "🌧️"
    assert weather_code_emoji(71) == "🌨️"
    assert weather_code_emoji(95) == "⛈️"


def test_filter_waking_hourly_same_day() -> None:
    from tomorrow.defaults import DayBounds
    from tomorrow.weather import filter_waking_hourly

    bounds = DayBounds(wake="06:30", sleep="23:00")
    plan_date = date(2026, 8, 11)
    raw_hourly = {
        "time": [f"2026-08-11T{h:02d}:00" for h in range(24)],
        "temperature_2m": [float(h + 10) for h in range(24)],
        "precipitation_probability": [h * 2 for h in range(24)],
        "weathercode": [2 if h % 2 == 0 else 61 for h in range(24)],
    }
    cards = filter_waking_hourly(raw_hourly, bounds=bounds, plan_date=plan_date)

    assert len(cards) == 18  # 06:00 to 23:00
    assert cards[0]["hour"] == "06:00"
    assert cards[0]["temperature_c"] == 16
    assert cards[0]["emoji"] == "⛅"
    assert cards[-1]["hour"] == "23:00"
    assert cards[-1]["temperature_c"] == 33


def test_filter_waking_hourly_overnight_midnight_wrap() -> None:
    from tomorrow.defaults import DayBounds
    from tomorrow.weather import filter_waking_hourly

    bounds = DayBounds(wake="08:00", sleep="01:30")
    plan_date = date(2026, 8, 11)
    raw_hourly = {
        "time": [f"2026-08-11T{h:02d}:00" for h in range(24)]
        + [f"2026-08-12T{h:02d}:00" for h in range(24)],
        "temperature_2m": [20.0] * 48,
        "precipitation_probability": [0] * 48,
        "weathercode": [0] * 48,
    }
    cards = filter_waking_hourly(raw_hourly, bounds=bounds, plan_date=plan_date)

    # 08:00 through 23:00 on 8-11 (16 hours) + 00:00 and 01:00 on 8-12 (2 hours) = 18 hours
    assert len(cards) == 18
    assert cards[0]["hour"] == "08:00"
    assert cards[-2]["hour"] == "00:00 +1"
    assert cards[-1]["hour"] == "01:00 +1"


def test_fetch_weather_forecast_builds_structured_payload() -> None:
    from tomorrow.defaults import DayBounds
    from tomorrow.weather import fetch_weather_forecast

    bounds = DayBounds(wake="07:00", sleep="22:00")
    plan_date = date(2026, 8, 11)
    payload = {
        "daily": {
            "time": ["2026-08-11"],
            "temperature_2m_min": [12.4],
            "temperature_2m_max": [21.8],
            "weathercode": [61],
        },
        "hourly": {
            "time": [f"2026-08-11T{h:02d}:00" for h in range(24)],
            "temperature_2m": [15.0] * 24,
            "precipitation_probability": [40] * 24,
            "weathercode": [61] * 24,
        },
    }

    def fake_opener(_request):
        return BytesIO(json.dumps(payload).encode("utf-8"))

    location = WeatherLocation(latitude=52.23, longitude=21.01)
    forecast = fetch_weather_forecast(
        location,
        plan_date,
        bounds=bounds,
        location_name="Warsaw",
        opener=fake_opener,
    )

    assert forecast is not None
    assert forecast["location_name"] == "Warsaw"
    assert forecast["low_c"] == 12
    assert forecast["high_c"] == 22
    assert forecast["weather_code"] == 61
    assert forecast["condition"] == "rain"
    assert forecast["emoji"] == "🌧️"
    assert forecast["summary"] == "Warsaw · 12° / 22° · 🌧️ rain"
    assert len(forecast["hourly"]) == 16  # 07:00 to 22:00


def test_reverse_geocode_resolves_city_name() -> None:
    from tomorrow.weather import reverse_geocode

    payload = {"address": {"city": "Warsaw"}}

    def fake_opener(_request):
        return BytesIO(json.dumps(payload).encode("utf-8"))

    name = reverse_geocode(52.23, 21.01, opener=fake_opener)
    assert name == "Warsaw"


def test_reverse_geocode_returns_none_on_error() -> None:
    from tomorrow.weather import reverse_geocode

    def failing_opener(_request):
        raise URLError("offline")

    assert reverse_geocode(52.23, 21.01, opener=failing_opener) is None


def test_save_weather_location_persists_toml(tmp_path: Path) -> None:
    from tomorrow.weather import save_weather_location

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    save_weather_location(data_dir, latitude=52.23, longitude=21.01, name="Warsaw")

    assert (data_dir / "weather.local.toml").exists()
    assert not (data_dir / "weather.toml").exists()
    assert load_weather_location(data_dir) == WeatherLocation(latitude=52.23, longitude=21.01)
    assert load_weather_name(data_dir) == "Warsaw"


def test_load_weather_location_prefers_local_toml_over_default(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "weather.toml").write_text(
        'name = "Warsaw"\nlatitude = 52.23\nlongitude = 21.01\n', encoding="utf-8"
    )
    (data_dir / "weather.local.toml").write_text(
        'name = "Berlin"\nlatitude = 52.52\nlongitude = 13.40\n', encoding="utf-8"
    )

    assert load_weather_location(data_dir) == WeatherLocation(latitude=52.52, longitude=13.40)
    assert load_weather_name(data_dir) == "Berlin"


def test_load_weather_location_local_invalid_falls_back_to_default(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "weather.toml").write_text(
        'name = "Warsaw"\nlatitude = 52.23\nlongitude = 21.01\n', encoding="utf-8"
    )
    (data_dir / "weather.local.toml").write_text(
        "invalid toml [[[\n", encoding="utf-8"
    )

    assert load_weather_location(data_dir) == WeatherLocation(latitude=52.23, longitude=21.01)
    assert load_weather_name(data_dir) == "Warsaw"


