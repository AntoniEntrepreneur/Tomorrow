from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import tomllib


@dataclass(frozen=True)
class WeatherLocation:
    latitude: float
    longitude: float


_OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"


def load_weather_location(data_dir: Path) -> WeatherLocation | None:
    path = data_dir / "weather.toml"
    if not path.exists():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return WeatherLocation(
            latitude=float(data["latitude"]),
            longitude=float(data["longitude"]),
        )
    except (KeyError, TypeError, ValueError, tomllib.TOMLDecodeError):
        return None


def weather_code_label(code: int) -> str:
    if code == 0:
        return "clear"
    if code in {1, 2}:
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


def format_weather_one_liner(*, low_c: float, high_c: float, weather_code: int) -> str:
    low = round(low_c)
    high = round(high_c)
    return f"{low}° / {high}° · {weather_code_label(weather_code)}"


def _forecast_url(location: WeatherLocation, plan_date: date) -> str:
    day = plan_date.isoformat()
    return (
        f"{_OPEN_METEO_FORECAST}?latitude={location.latitude}"
        f"&longitude={location.longitude}"
        "&daily=temperature_2m_max,temperature_2m_min,weathercode"
        "&timezone=auto"
        f"&start_date={day}&end_date={day}"
    )


def fetch_weather_one_liner(
    location: WeatherLocation,
    plan_date: date,
    *,
    opener: Callable[[Request], object] = urlopen,
) -> str | None:
    try:
        request = Request(_forecast_url(location, plan_date), headers={"User-Agent": "Tomorrow/0.1"})
        with opener(request) as response:
            payload = json.load(response)
        daily = payload["daily"]
        low_c = float(daily["temperature_2m_min"][0])
        high_c = float(daily["temperature_2m_max"][0])
        weather_code = int(daily["weathercode"][0])
    except (URLError, HTTPError, KeyError, IndexError, TypeError, ValueError):
        return None
    return format_weather_one_liner(low_c=low_c, high_c=high_c, weather_code=weather_code)


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
