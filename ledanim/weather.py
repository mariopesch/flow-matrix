"""
Weather data from Open-Meteo (https://open-meteo.com - free, no API key)
plus animated 32x32 pixel weather icons.
"""
import json
import math
import random
import threading
import time
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
API_URL = "https://api.open-meteo.com/v1/forecast"
REFRESH = 600  # seconds


def condition(code):
    """WMO weather code -> (icon kind, short label)."""
    c = int(code if code is not None else -1)
    if c == 0:
        return "clear", "CLEAR"
    if c in (1, 2):
        return "partly", "PARTLY CLOUDY"
    if c == 3:
        return "cloudy", "OVERCAST"
    if c in (45, 48):
        return "fog", "FOG"
    if 51 <= c <= 57:
        return "rain", "DRIZZLE"
    if 61 <= c <= 67 or 80 <= c <= 82:
        return "rain", "RAIN" if c < 80 else "SHOWERS"
    if 71 <= c <= 77 or c in (85, 86):
        return "snow", "SNOW"
    if c >= 95:
        return "thunder", "THUNDERSTORM"
    return "cloudy", "?"


def _get_json(url, params, timeout=10):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "led-animator/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


class WeatherService:
    """Background thread that keeps current weather for one city fresh."""

    def __init__(self, city="Berlin", units="metric"):
        self.city = city
        self.units = units
        self.location = None   # dict(name, country, lat, lon)
        self.data = None       # dict with current values
        self.error = None
        self.updated = 0.0
        self._lock = threading.Lock()
        self._wake = threading.Event()
        threading.Thread(target=self._run, name="weather", daemon=True).start()

    def configure(self, city=None, units=None):
        with self._lock:
            if city and city.strip() != self.city:
                self.city = city.strip()
                self.location = None
                self.data = None
            if units in ("metric", "imperial") and units != self.units:
                self.units = units
                self.data = None
        self._wake.set()

    def refresh(self):
        self._wake.set()

    def info(self):
        with self._lock:
            return {"city": self.city, "units": self.units, "location": self.location,
                    "data": self.data, "error": self.error, "updated": self.updated}

    def _fetch(self):
        with self._lock:
            city, units, loc = self.city, self.units, self.location
        if not loc:
            res = _get_json(GEO_URL, {"name": city, "count": 1, "format": "json"})
            hits = res.get("results") or []
            if not hits:
                raise ValueError("city '%s' not found" % city)
            h = hits[0]
            loc = {"name": h["name"], "country": h.get("country_code", ""),
                   "lat": h["latitude"], "lon": h["longitude"]}
        params = {
            "latitude": loc["lat"], "longitude": loc["lon"], "timezone": "auto",
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                       "is_day,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,weather_code",
            "forecast_days": 2,
        }
        if units == "imperial":
            params.update(temperature_unit="fahrenheit", wind_speed_unit="mph")
        res = _get_json(API_URL, params)
        cur, daily = res["current"], res.get("daily", {})
        dmax = daily.get("temperature_2m_max") or []
        dmin = daily.get("temperature_2m_min") or []
        dcode = daily.get("weather_code") or []
        pick = lambda lst, i: lst[i] if len(lst) > i else None
        data = {
            "temp": cur.get("temperature_2m"),
            "feels": cur.get("apparent_temperature"),
            "humidity": cur.get("relative_humidity_2m"),
            "wind": cur.get("wind_speed_10m"),
            "code": cur.get("weather_code"),
            "is_day": bool(cur.get("is_day", 1)),
            "max": pick(dmax, 0), "min": pick(dmin, 0),
            "tomorrow_max": pick(dmax, 1), "tomorrow_min": pick(dmin, 1),
            "tomorrow_code": pick(dcode, 1),
            "temp_unit": "F" if units == "imperial" else "C",
            "wind_unit": "MPH" if units == "imperial" else "KM/H",
        }
        with self._lock:
            if city == self.city and units == self.units:
                self.location, self.data, self.error, self.updated = loc, data, None, time.time()

    def _run(self):
        while True:
            try:
                self._fetch()
                wait = REFRESH
            except Exception as exc:
                with self._lock:
                    self.error = str(exc)
                print("weather:", exc)
                wait = 60
            self._wake.wait(wait)
            self._wake.clear()


# ------------------------------------------------------------- pixel icons
def _cloud(d, ox, oy, color, scale=1.0):
    s = scale
    for cx, cy, r in ((9, 15, 5), (16, 11, 7), (23, 15, 5)):
        d.ellipse([ox + (cx - r) * s, oy + (cy - r) * s, ox + (cx + r) * s, oy + (cy + r) * s], fill=color)
    d.rectangle([ox + 9 * s, oy + 14 * s, ox + 23 * s, oy + 20 * s], fill=color)


def _sun(d, cx, cy, r, t, color=(255, 200, 0)):
    for i in range(8):
        a = t * 0.8 + i * math.pi / 4
        r1, r2 = r + 2, r + 5 + math.sin(t * 4 + i) * 1.2
        d.line([cx + math.cos(a) * r1, cy + math.sin(a) * r1,
                cx + math.cos(a) * r2, cy + math.sin(a) * r2], fill=(255, 140, 0))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)


def _moon(d, cx, cy, r, t):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(230, 230, 190))
    d.ellipse([cx - r + 4, cy - r - 2, cx + r + 4, cy + r - 2], fill=(0, 0, 0))
    rnd = random.Random(7)
    for _ in range(5):
        x, y = rnd.randrange(32), rnd.randrange(14)
        if (int(t * 3) + x) % 4:
            d.point((x, y), fill=(180, 180, 220))


def draw_icon(kind, t, is_day=True, size=32):
    """Return an animated weather icon (RGB, size x size) for time t (seconds)."""
    img = Image.new("RGB", (32, 32))
    d = ImageDraw.Draw(img)
    grey, dark = (190, 190, 200), (110, 110, 125)
    if kind == "clear":
        if is_day:
            _sun(d, 16, 16, 7, t)
        else:
            _moon(d, 16, 17, 9, t)
    elif kind == "partly":
        if is_day:
            _sun(d, 20, 10, 6, t)
        else:
            _moon(d, 21, 10, 7, t)
        _cloud(d, -3 + math.sin(t * 0.6) * 2, 6, grey)
    elif kind == "cloudy":
        _cloud(d, 2 + math.sin(t * 0.5) * 2, -2, dark, 0.8)
        _cloud(d, -2 + math.sin(t * 0.7 + 1) * 2, 5, grey)
    elif kind == "fog":
        for i in range(5):
            y = 8 + i * 4
            off = math.sin(t * 1.2 + i) * 4
            d.line([4 + off, y, 27 + off, y], fill=(150, 150, 160) if i % 2 else grey)
    elif kind in ("rain", "snow", "thunder"):
        _cloud(d, 0, -4, dark if kind == "thunder" else grey)
        if kind == "rain" or kind == "thunder":
            for i in range(7):
                x = 6 + i * 3.3
                y = 17 + ((t * 18 + i * 5.3) % 14)
                d.line([x, y, x - 1, y + 2], fill=(60, 140, 255))
        if kind == "snow":
            for i in range(6):
                x = 6 + i * 4 + math.sin(t * 2 + i) * 1.5
                y = 17 + ((t * 6 + i * 4.7) % 14)
                d.point([(x, y), (x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)], fill=(240, 240, 255))
        if kind == "thunder" and (t % 2.5) < 0.25:
            d.line([(17, 13), (13, 21), (18, 21), (14, 30)], fill=(255, 255, 80), width=2)
    else:
        _cloud(d, 0, 0, dark)
    return img if size == 32 else img.resize((size, size), Image.NEAREST)


def temp_color(temp, unit="C"):
    """Blue (cold) -> white -> yellow -> red (hot)."""
    if temp is None:
        return (200, 200, 200)
    c = temp if unit == "C" else (temp - 32) * 5 / 9
    stops = [(-15, (80, 80, 255)), (0, (120, 200, 255)), (10, (230, 255, 230)),
             (20, (255, 220, 60)), (30, (255, 110, 0)), (40, (255, 30, 30))]
    if c <= stops[0][0]:
        return stops[0][1]
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if c <= t1:
            f = (c - t0) / (t1 - t0)
            return tuple(int(a + (b - a) * f) for a, b in zip(c0, c1))
    return stops[-1][1]
