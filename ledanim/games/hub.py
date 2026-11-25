"""
Phones connected as game controllers.

Each phone connects over WebSocket (see ledanim/wsserver.py) and becomes a player.
Connection threads store the latest input per player; the running game (matrix
thread) reads it and publishes a small state dict per player, which is sent back.

Messages from the phone:
  {"t": "pos", "v": 0..1}                 slider position
  {"t": "stick", "x": -1..1, "y": -1..1}  joystick (y points down)
  {"t": "btn", "b": "fire", "down": true}  action button held / released
  {"t": "start"}                           start or restart the match
  {"t": "launch", "game": "<id>"}          put a game on the matrix
  {"t": "hi"}                              keep-alive
"""
import json
import math
import threading
import time


class GameHub:
    TIMEOUT = 10  # seconds without any message -> the phone is gone

    def __init__(self, is_running, launch, games=None):
        self.is_running = is_running  # () -> bool: is a game on the matrix?
        self.launch = launch          # (game id) -> None: put that game on the matrix
        self.games = dict(games or {})  # id -> {"title": ..., "players": ...}
        self._lock = threading.Lock()
        self._next_id = 1
        self._players = {}   # pid -> input state (dicts keep join order)
        self._actions = []   # (pid, "start" | "press:<button>")
        self._views = {}     # pid -> dict published by the game
        self._events = {}    # pid -> [event names] (phones vibrate on these)

    # -------------------------------------------------- used by the game
    def roster(self):
        with self._lock:
            return list(self._players)

    def position(self, pid):
        with self._lock:
            p = self._players.get(pid)
            return p["pos"] if p else None

    def stick(self, pid):
        with self._lock:
            p = self._players.get(pid)
            return p["stick"] if p else (0.0, 0.0)

    def held(self, pid, button):
        with self._lock:
            p = self._players.get(pid)
            return bool(p) and button in p["held"]

    def take_actions(self):
        with self._lock:
            actions, self._actions = self._actions, []
            return actions

    def publish(self, views):
        with self._lock:
            self._views = dict(views)

    def event(self, pid, name):
        with self._lock:
            if pid in self._events:
                self._events[pid].append(name)

    # -------------------------------------------------- connections
    def _join(self):
        with self._lock:
            pid = self._next_id
            self._next_id += 1
            self._players[pid] = {"pos": 0.5, "stick": (0.0, 0.0), "held": set()}
            self._events[pid] = []
            return pid

    def _leave(self, pid):
        with self._lock:
            self._players.pop(pid, None)
            self._events.pop(pid, None)
            self._views.pop(pid, None)

    def _handle(self, pid, raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        kind = msg.get("t")
        try:
            if kind == "pos":
                pos = max(0.0, min(1.0, float(msg.get("v"))))
                with self._lock:
                    if pid in self._players:
                        self._players[pid]["pos"] = pos
            elif kind == "stick":
                x, y = float(msg.get("x", 0)), float(msg.get("y", 0))
                if not (math.isfinite(x) and math.isfinite(y)):
                    return
                m = math.hypot(x, y)
                if m > 1:
                    x, y = x / m, y / m
                with self._lock:
                    if pid in self._players:
                        self._players[pid]["stick"] = (x, y)
            elif kind == "btn":
                button = str(msg.get("b", ""))[:16]
                with self._lock:
                    p = self._players.get(pid)
                    if p is None or not button:
                        return
                    if msg.get("down"):
                        if button not in p["held"]:
                            self._actions.append((pid, "press:" + button))
                        p["held"].add(button)
                    else:
                        p["held"].discard(button)
            elif kind == "start":
                with self._lock:
                    self._actions.append((pid, "start"))
            elif kind == "launch" and msg.get("game") in self.games:
                self.launch(msg["game"])
        except (TypeError, ValueError):
            return
        except Exception as exc:  # e.g. launching failed
            print("games: %s" % exc)

    def _view(self, pid):
        if not self.is_running():
            return {"t": "state", "running": False, "games": self.games}
        with self._lock:
            view = dict(self._views.get(pid) or {"t": "state", "running": True, "phase": "joining"})
        view["games"] = self.games
        return view

    def _pop_events(self, pid):
        with self._lock:
            ev = self._events.get(pid) or []
            if ev:
                self._events[pid] = []
            return ev

    def serve(self, conn):
        """Runs in the connection's thread until the phone disconnects."""
        pid = self._join()
        last_sent, last_msg = None, time.monotonic()
        try:
            conn.send(json.dumps({"t": "hello", "id": pid}))
            while True:
                msg = conn.recv(0.05)
                while msg is not None:  # handle everything that is waiting
                    last_msg = time.monotonic()
                    self._handle(pid, msg)
                    msg = conn.recv(0)
                if time.monotonic() - last_msg > self.TIMEOUT:
                    break
                view = json.dumps(self._view(pid), sort_keys=True)
                if view != last_sent:
                    conn.send(view)
                    last_sent = view
                for name in self._pop_events(pid):
                    conn.send(json.dumps({"t": "event", "name": name}))
        finally:
            self._leave(pid)
