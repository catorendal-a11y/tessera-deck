"""Ambient screen support: the line under the idle clock, optionally current weather from Open-Meteo.

Nothing here talks to the network unless the user turned weather on and picked a place. The request
is a single small GET every 15 minutes made from a background thread; failures keep the last line.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
GEOCODING_URL = 'https://geocoding-api.open-meteo.com/v1/search'
REFRESH_SECONDS = 15 * 60
TIMEOUT_SECONDS = 6
MAX_LINE = 80
UNITS = ('celsius', 'fahrenheit')

# WMO weather interpretation codes -> short English text.
WEATHER_CODES = {0: 'Clear sky', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Overcast', 45: 'Fog', 48: 'Rime fog',
                 51: 'Light drizzle', 53: 'Drizzle', 55: 'Heavy drizzle', 56: 'Freezing drizzle',
                 57: 'Freezing drizzle', 61: 'Light rain', 63: 'Rain', 65: 'Heavy rain', 66: 'Freezing rain',
                 67: 'Freezing rain', 71: 'Light snow', 73: 'Snow', 75: 'Heavy snow', 77: 'Snow grains',
                 80: 'Rain showers', 81: 'Rain showers', 82: 'Violent showers', 85: 'Snow showers',
                 86: 'Snow showers', 95: 'Thunderstorm', 96: 'Thunderstorm with hail', 99: 'Thunderstorm with hail'}


def check_ambient(settings) -> None:
    """Validate the `ambient` block of the configuration."""
    if not isinstance(settings, dict) or type(settings.get('enabled', False)) is not bool:
        raise ValueError('ambient must be an object with enabled true or false')
    after = settings.get('after', 120)
    if type(after) is not int or not 15 <= after <= 3600:
        raise ValueError('ambient.after must be 15-3600 seconds')
    weather = settings.get('weather')
    if weather is None:
        return
    if (not isinstance(weather, dict) or not isinstance(weather.get('name', ''), str)
            or len(weather.get('name', '')) > 60 or weather.get('unit', 'celsius') not in UNITS):
        raise ValueError('ambient.weather needs a name and the unit celsius or fahrenheit')
    for key, limit in (('latitude', 90), ('longitude', 180)):
        value = weather.get(key)
        if type(value) not in (int, float) or isinstance(value, bool) or not -limit <= value <= limit:
            raise ValueError(f'ambient.weather.{key} must be a number within +-{limit}')


def describe(current: dict, name: str, unit: str) -> str:
    """'12 C, Partly cloudy - Oslo' from an Open-Meteo `current` block."""
    temperature = current.get('temperature_2m')
    if type(temperature) not in (int, float):
        raise ValueError('the weather answer has no temperature')
    text = WEATHER_CODES.get(current.get('weather_code'), '')
    parts = [f'{round(temperature)} {"F" if unit == "fahrenheit" else "C"}' + (f', {text}' if text else '')]
    if name:
        parts.append(name)
    return ' - '.join(parts)[:MAX_LINE]


def _get_json(url: str, opener=urllib.request.urlopen) -> dict:
    request = urllib.request.Request(url, headers={'User-Agent': 'Tessera-Deck'})
    with opener(request, timeout=TIMEOUT_SECONDS) as reply:
        data = json.loads(reply.read(256 * 1024))
    if not isinstance(data, dict):
        raise ValueError('unexpected answer')
    return data


def forecast_url(latitude: float, longitude: float, unit: str) -> str:
    query = urllib.parse.urlencode({'latitude': f'{latitude:.4f}', 'longitude': f'{longitude:.4f}',
                                    'current': 'temperature_2m,weather_code', 'timezone': 'auto',
                                    'temperature_unit': unit})
    return f'{FORECAST_URL}?{query}'


def search_places(query: str, opener=urllib.request.urlopen) -> list[dict]:
    """Place candidates for a city name (user-initiated lookup)."""
    query = query.strip()
    if not 2 <= len(query) <= 60:
        raise ValueError('Type at least two letters of the city name')
    url = GEOCODING_URL + '?' + urllib.parse.urlencode({'name': query, 'count': 6, 'language': 'en', 'format': 'json'})
    results = _get_json(url, opener).get('results') or []
    return [{'name': item.get('name', ''), 'region': item.get('admin1', ''), 'country': item.get('country', ''),
             'latitude': item['latitude'], 'longitude': item['longitude']}
            for item in results if isinstance(item, dict) and 'latitude' in item and 'longitude' in item]


class Weather:
    """Keeps the latest weather line fresh in the background."""

    def __init__(self, opener=urllib.request.urlopen, clock=time.monotonic):
        self._opener, self._clock = opener, clock
        self._lock = threading.Lock()
        self._line = ''
        self._key = None
        self._next = 0.0
        self._busy = False

    def line(self, settings: dict | None) -> str:
        """The current weather line for `settings['weather']`; starts a refresh when it is due."""
        weather = (settings or {}).get('weather') if (settings or {}).get('enabled') else None
        if not weather:
            return ''
        key = (weather['latitude'], weather['longitude'], weather.get('unit', 'celsius'), weather.get('name', ''))
        with self._lock:
            due = key != self._key or self._clock() >= self._next
            if key != self._key:
                self._line = ''
            if due and not self._busy:
                self._busy = True
                self._key = key
                threading.Thread(target=self._refresh, args=(key,), name='weather', daemon=True).start()
            return self._line

    def _refresh(self, key) -> None:
        latitude, longitude, unit, name = key
        try:
            current = _get_json(forecast_url(latitude, longitude, unit), self._opener).get('current') or {}
            line = describe(current, name, unit)
        except (OSError, ValueError, urllib.error.URLError, KeyError):
            line = None
        with self._lock:
            if line is not None and key == self._key:
                self._line = line
            self._next = self._clock() + (REFRESH_SECONDS if line is not None else 60)
            self._busy = False
