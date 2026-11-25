"""
Live sensor values from an openSenseMap box (https://opensensemap.org - free, no API key).
"""
import calendar
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API_URL = "https://api.opensensemap.org/boxes/"
REFRESH = 60          # seconds between updates
STALE_AFTER = 3600    # a value older than this is shown dimmed
MODES = ("big", "list")
_ID_RE = re.compile(r"[0-9a-fA-F]{24}")


def parse_box_id(text):
    """Accept a bare box id or any openSenseMap link that contains one."""
    m = _ID_RE.search(str(text or ""))
    return m.group(0).lower() if m else None


def _parse_time(value):
    """ISO UTC timestamp ('2026-10-28T20:50:00.000Z') -> unix seconds."""
    try:
        return calendar.timegm(time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return None


def _fetch_box(box_id, timeout=10):
    url = API_URL + urllib.parse.quote(box_id) + "?format=json"
    req = urllib.request.Request(url, headers={"User-Agent": "led-animator/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 404, 422):
            raise ValueError("openSenseMap box '%s' not found" % box_id)
        raise
    sensors = []
    for s in data.get("sensors") or []:
        last = s.get("lastMeasurement") or {}
        sensors.append({
            "id": s.get("_id"),
            "title": s.get("title") or "?",
            "unit": s.get("unit") or "",
            "type": s.get("sensorType") or "",
            "value": last.get("value"),
            "time": _parse_time(last.get("createdAt")),
        })
    return {"id": data.get("_id", box_id), "name": data.get("name") or box_id, "sensors": sensors}


def format_value(raw):
    """'21.347' -> '21.3', '42' -> '42', '1013.25' -> '1013', None -> '--'."""
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return "--" if raw in (None, "") else str(raw)[:6]
    if abs(v) >= 100 or ("." not in str(raw) and "e" not in str(raw).lower()):
        return "%d" % round(v)
    s = "%.1f" % v
    return "0.0" if s == "-0.0" else s


class OpenSenseMapService:
    """Background thread that keeps the latest values of one openSenseMap box fresh."""

    def __init__(self, box_id=None, sensors=None, mode="big"):
        self.box_id = parse_box_id(box_id)
        self.selected = list(sensors or [])
        self.mode = mode if mode in MODES else "big"
        self.box = None        # dict(id, name, sensors=[...])
        self.error = None
        self.updated = 0.0
        self._lock = threading.Lock()
        self._wake = threading.Event()
        threading.Thread(target=self._run, name="opensensemap", daemon=True).start()

    # ---------------------------------------------------------- config
    def set_box(self, text):
        """Load a new box right away. Raises ValueError with a readable message."""
        box_id = parse_box_id(text)
        if not box_id:
            raise ValueError("paste an openSenseMap box ID (24 characters) or a link to the box")
        try:
            box = _fetch_box(box_id)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("could not reach openSenseMap: %s" % exc)
        with self._lock:
            changed = box_id != self.box_id
            self.box_id, self.box, self.error, self.updated = box_id, box, None, time.time()
            if changed or not self.selected:
                self.selected = [s["id"] for s in box["sensors"]]
        self._wake.set()

    def configure(self, sensors=None, mode=None):
        with self._lock:
            if sensors is not None:
                known = {s["id"] for s in (self.box or {}).get("sensors", [])}
                self.selected = [str(s) for s in sensors if not known or s in known][:50]
            if mode in MODES:
                self.mode = mode

    def config(self):
        with self._lock:
            return {"box": self.box_id, "sensors": list(self.selected), "mode": self.mode}

    def info(self):
        with self._lock:
            return {"box_id": self.box_id, "box": self.box, "selected": list(self.selected),
                    "mode": self.mode, "error": self.error, "updated": self.updated}

    def selected_sensors(self):
        """Selected sensors in the box's order."""
        with self._lock:
            if not self.box:
                return []
            sel = set(self.selected)
            return [dict(s) for s in self.box["sensors"] if s["id"] in sel]

    # ---------------------------------------------------------- worker
    def _fetch(self):
        with self._lock:
            box_id = self.box_id
        if not box_id:
            return
        box = _fetch_box(box_id)
        with self._lock:
            if box_id == self.box_id:
                self.box, self.error, self.updated = box, None, time.time()

    def _run(self):
        while True:
            try:
                self._fetch()
                wait = REFRESH
            except Exception as exc:
                with self._lock:
                    self.error = str(exc)
                print("opensensemap:", exc)
                wait = 60
            self._wake.wait(wait)
            self._wake.clear()
