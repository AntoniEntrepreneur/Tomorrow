from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import tomllib

if TYPE_CHECKING:
    from tomorrow.defaults import DayBounds


@dataclass(frozen=True)
class WeatherLocation:
    latitude: float
    longitude: float


_OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"


def _load_weather_toml(data_dir: Path) -> dict | None:
    path = data_dir / "weather.toml"
    if not path.exists():
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return None


def load_weather_name(data_dir: Path) -> str | None:
    data = _load_weather_toml(data_dir)
    if data is None:
        return None
    name = data.get("name")
    if not name:
        return None
    return str(name)


def load_weather_location(data_dir: Path) -> WeatherLocation | None:
    data = _load_weather_toml(data_dir)
    if data is None:
        return None
    try:
        return WeatherLocation(
            latitude=float(data["latitude"]),
            longitude=float(data["longitude"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def weather_code_label(code: int) -> str:
    if code in {0, 1}:
        return "clear"
    if code == 2:
        return "partly cloudy"
    if code == 3:
        return "overcast"
    if code in {45, 48}:
        return "fog"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 80, 81, 82}:
        return "rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow"
    if code in {95, 96, 99}:
        return "thunderstorm"
    return "mixed"


def weather_code_emoji(code: int) -> str:
    if code in {0, 1}:
        return "☀️"
    if code == 2:
        return "⛅"
    if code == 3:
        return "☁️"
    if code in {45, 48}:
        return "🌫️"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 80, 81, 82}:
        return "🌧️"
    if code in {71, 73, 75, 77, 85, 86}:
        return "🌨️"
    if code in {95, 96, 99}:
        return "⛈️"
    return "⛅"


def format_weather_one_liner(*, low_c: float, high_c: float, weather_code: int) -> str:
    low = round(low_c)
    high = round(high_c)
    return f"{low}° / {high}° · {weather_code_label(weather_code)}"


def format_weather_summary(
    *,
    low_c: float,
    high_c: float,
    weather_code: int,
    location_name: str | None = None,
) -> str:
    low = round(low_c)
    high = round(high_c)
    emoji = weather_code_emoji(weather_code)
    label = weather_code_label(weather_code)
    bits = []
    if location_name:
        bits.append(location_name)
    bits.append(f"{low}° / {high}°")
    bits.append(f"{emoji} {label}")
    return " · ".join(bits)


def filter_waking_hourly(
    raw_hourly: dict,
    *,
    bounds: DayBounds,
    plan_date: date,
) -> list[dict]:
    from tomorrow.domain import parse_clock

    wake_time = parse_clock(bounds.wake)
    sleep_time = parse_clock(bounds.sleep)

    wake_dt = datetime.combine(plan_date, wake_time.replace(minute=0, second=0))
    if sleep_time <= wake_time:
        sleep_dt = datetime.combine(plan_date + timedelta(days=1), sleep_time)
    else:
        sleep_dt = datetime.combine(plan_date, sleep_time)

    times = raw_hourly.get("time", [])
    temps = raw_hourly.get("temperature_2m", [])
    precips = raw_hourly.get("precipitation_probability", [])
    codes = raw_hourly.get("weathercode", [])

    cards: list[dict] = []
    for i, t_str in enumerate(times):
        try:
            dt = datetime.fromisoformat(t_str)
        except ValueError:
            continue
        if wake_dt <= dt <= sleep_dt:
            is_post_midnight = dt.date() > plan_date
            hour_str = dt.strftime("%H:%M")
            if is_post_midnight:
                hour_str += " +1"
            temp_c = round(float(temps[i])) if i < len(temps) else 0
            precip = round(float(precips[i])) if i < len(precips) else 0
            code = int(codes[i]) if i < len(codes) else 0
            cards.append(
                {
                    "hour": hour_str,
                    "temperature_c": temp_c,
                    "weather_code": code,
                    "condition": weather_code_label(code),
                    "emoji": weather_code_emoji(code),
                    "precipitation_probability": precip,
                }
            )
    return cards


def _forecast_url(
    location: WeatherLocation,
    start_date: date,
    end_date: date,
) -> str:
    return (
        f"{_OPEN_METEO_FORECAST}?latitude={location.latitude}"
        f"&longitude={location.longitude}"
        "&daily=temperature_2m_max,temperature_2m_min,weathercode"
        "&hourly=temperature_2m,precipitation_probability,weathercode"
        "&timezone=auto"
        f"&start_date={start_date.isoformat()}&end_date={end_date.isoformat()}"
    )


def fetch_weather_forecast(
    location: WeatherLocation,
    plan_date: date,
    *,
    bounds: DayBounds,
    location_name: str | None = None,
    opener: Callable[[Request], object] = urlopen,
) -> dict | None:
    from tomorrow.domain import parse_clock

    wake_time = parse_clock(bounds.wake)
    sleep_time = parse_clock(bounds.sleep)
    if sleep_time <= wake_time:
        end_date = plan_date + timedelta(days=1)
    else:
        end_date = plan_date

    try:
        url = _forecast_url(location, plan_date, end_date)
        request = Request(url, headers={"User-Agent": "Tomorrow/0.1"})
        with opener(request) as response:
            payload = json.load(response)
        daily = payload["daily"]
        low_c = round(float(daily["temperature_2m_min"][0]))
        high_c = round(float(daily["temperature_2m_max"][0]))
        weather_code = int(daily["weathercode"][0])
        condition = weather_code_label(weather_code)
        emoji = weather_code_emoji(weather_code)
        summary = format_weather_summary(
            low_c=low_c,
            high_c=high_c,
            weather_code=weather_code,
            location_name=location_name,
        )
        hourly = filter_waking_hourly(
            payload.get("hourly", {}),
            bounds=bounds,
            plan_date=plan_date,
        )
        return {
            "location_name": location_name,
            "low_c": low_c,
            "high_c": high_c,
            "weather_code": weather_code,
            "condition": condition,
            "emoji": emoji,
            "summary": summary,
            "hourly": hourly,
        }
    except (URLError, HTTPError, TimeoutError, KeyError, IndexError, TypeError, ValueError):
        return None


def fetch_weather_one_liner(
    location: WeatherLocation,
    plan_date: date,
    *,
    opener: Callable[[Request], object] = urlopen,
) -> str | None:
    from tomorrow.defaults import DayBounds

    forecast = fetch_weather_forecast(
        location,
        plan_date,
        bounds=DayBounds(wake="06:00", sleep="23:00"),
        opener=opener,
    )
    if forecast is None:
        return None
    return f"{forecast['low_c']}° / {forecast['high_c']}° · {forecast['condition']}"


def try_fetch_weather_forecast(
    data_dir: Path,
    plan_date: date,
    *,
    bounds: DayBounds,
    opener: Callable[[Request], object] = urlopen,
) -> dict | None:
    location = load_weather_location(data_dir)
    if location is None:
        return None
    location_name = load_weather_name(data_dir)
    return fetch_weather_forecast(
        location,
        plan_date,
        bounds=bounds,
        location_name=location_name,
        opener=opener,
    )


def try_fetch_weather(
    data_dir: Path,
    plan_date: date,
    *,
    opener: Callable[[Request], object] = urlopen,
) -> str | None:
    location = load_weather_location(data_dir)
    if location is None:
        return None
    return fetch_weather_one_liner(location, plan_date, opener=opener)

