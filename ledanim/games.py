"""
Multiplayer games for the matrix, controlled from phones (static/play.html).

Phones connect over WebSocket (see wsserver.py) and join the GameHub. The running
game reads each player's latest input from the hub and publishes a small state
dict per player, which the hub sends back to that phone.
"""
import json
import math
import random
import threading
import time
from collections import deque

from PIL import Image, ImageDraw

from . import pixelfont
from .scenes import Scene, draw_big, fit_font, small_line

GAMES = {"paddle": "Paddle Duel"}


def _hex(c):
    return "#%02x%02x%02x" % tuple(c)


def _scale(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def _ticker(img, x0, y, width, text, color, t):
    """Like scenes.small_line, but only the letters are drawn, so the background stays visible."""
    strip = Image.new("RGB", (width, pixelfont.HEIGHT))
    small_line(strip, 0, 0, width, text, color, t)
    img.paste(strip, (x0, y), strip.convert("L").point(lambda v: 255 if v else 0))


# ---------------------------------------------------------------- players
class GameHub:
    """Phones connected as players. Thread-safe: connection threads write inputs,
    the matrix thread (the game) reads them and publishes per-player views."""
    TIMEOUT = 10  # seconds without any message -> the phone is gone

    def __init__(self, is_running, launch):
        self.is_running = is_running  # () -> bool: is a game on the matrix?
        self.launch = launch          # (name) -> None: put a game on the matrix
        self._lock = threading.Lock()
        self._next_id = 1
        self._players = {}   # pid -> {"pos": 0..1}   (dicts keep join order)
        self._actions = []   # (pid, action)
        self._views = {}     # pid -> dict published by the game
        self._events = {}    # pid -> [event names] (phones vibrate on these)

    # -------------------------------------------- used by the game
    def roster(self):
        with self._lock:
            return list(self._players)

    def position(self, pid):
        with self._lock:
            p = self._players.get(pid)
            return p["pos"] if p else None

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

    # -------------------------------------------- used by connections
    def _join(self):
        with self._lock:
            pid = self._next_id
            self._next_id += 1
            self._players[pid] = {"pos": 0.5}
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
        if kind == "pos":
            try:
                pos = max(0.0, min(1.0, float(msg.get("v"))))
            except (TypeError, ValueError):
                return
            with self._lock:
                if pid in self._players:
                    self._players[pid]["pos"] = pos
        elif kind == "start":
            with self._lock:
                self._actions.append((pid, "start"))
        elif kind == "launch" and msg.get("game") in GAMES:
            try:
                self.launch(msg["game"])
            except Exception as exc:
                print("games: could not start %s: %s" % (msg.get("game"), exc))

    def _view(self, pid):
        if not self.is_running():
            return {"t": "state", "running": False, "games": GAMES}
        with self._lock:
            return self._views.get(pid) or {"t": "state", "running": True, "phase": "joining"}

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


# ---------------------------------------------------------- paddle duel
class Paddle:
    def __init__(self, side, color, h):
        self.side, self.color = side, color
        self.base_h = self.h = h
        self.y = 0.0
        self.grow_until = 0.0
        self.ai_error = 0.0


class PaddleDuel(Scene):
    """Two paddles at the ends of the strip. Up to two phones play; an empty side
    is played by the computer. Each hit speeds the ball up, and power orbs make
    the last player who hit the ball grow a bigger paddle for a while."""
    WIN = 7
    FPS = 50
    PADDLE_H = 8
    GROW_H = 13
    GROW_SECONDS = 10
    SPEED0, SPEEDUP, SPEED_MAX = 40.0, 1.07, 115.0
    AI_SPEED = 34.0
    COLORS = [(0, 170, 255), (255, 110, 0)]
    WHITE, GREY = (235, 235, 235), (120, 128, 145)

    def __init__(self, hub, w, h, join_url=""):
        self.hub, self.w, self.h, self.join_url = hub, w, h, join_url
        self.count_font = fit_font("8", 24, h - 10, 40)

    # ------------------------------------------------------------ state
    def start(self):
        self.hub.publish({})
        self.last = time.monotonic()
        self.t = 0.0
        self.slots = [None, None]  # pid per side, None = computer
        self.paddles = [Paddle("left", self.COLORS[0], self.PADDLE_H),
                        Paddle("right", self.COLORS[1], self.PADDLE_H)]
        for p in self.paddles:
            p.y = (self.h - p.h) / 2
        self._to_lobby()

    def _to_lobby(self):
        self.phase, self.phase_t = "lobby", 0.0
        self.score = [0, 0]
        self.ball = None
        self.trail = deque(maxlen=7)
        self.orb, self.next_orb = None, 0.0
        self.serve_to = random.choice((0, 1))
        self.flash = [0.0, 0.0]
        self.winner = None
        self.last_hitter = None
        for p in self.paddles:
            p.h, p.grow_until = p.base_h, 0.0

    def _set_phase(self, phase):
        self.phase, self.phase_t = phase, 0.0

    def _assign_slots(self):
        roster = self.hub.roster()
        self.slots = [pid if pid in roster else None for pid in self.slots]
        for pid in roster:
            if pid in self.slots:
                continue
            if None not in self.slots:
                break
            self.slots[self.slots.index(None)] = pid

    def _humans(self):
        return [pid for pid in self.slots if pid is not None]

    def _start_match(self):
        self.score = [0, 0]
        self.winner = None
        self.orb, self.next_orb = None, self.t + random.uniform(8, 14)
        for p in self.paddles:
            p.h, p.grow_until = p.base_h, 0.0
        self._set_phase("countdown")

    # ------------------------------------------------------------ loop
    def next(self):
        now = time.monotonic()
        dt = min(0.05, now - self.last)
        self.last = now
        self.t += dt
        self.phase_t += dt
        self._assign_slots()
        for pid, action in self.hub.take_actions():
            if action == "start" and pid in self.slots:
                if self.phase == "lobby" or (self.phase == "over" and self.phase_t > 1.5):
                    self._start_match()
        self._update(dt)
        img = self._draw()
        self._publish()
        return img, 1.0 / self.FPS

    def _update(self, dt):
        self.flash = [max(0.0, f - dt * 1.5) for f in self.flash]
        self._move_paddles(dt)
        if self.phase != "lobby" and not self._humans():
            self._to_lobby()  # everybody left
            return
        if self.phase == "countdown" and self.phase_t >= 3:
            self._serve()
        elif self.phase == "serve" and self.phase_t >= 1.0:
            self._set_phase("playing")
        elif self.phase == "playing":
            self._move_ball(dt)
            self._update_orb()
        elif self.phase == "point" and self.phase_t >= 1.2:
            if max(self.score) >= self.WIN:
                self.winner = 0 if self.score[0] > self.score[1] else 1
                self._set_phase("over")
            else:
                self._serve()
        elif self.phase == "over" and self.phase_t >= 12:
            self._to_lobby()

    def _serve(self):
        self.ball = {"x": self.w / 2 - 1, "y": random.uniform(self.h * 0.3, self.h * 0.7) - 1,
                     "speed": self.SPEED0}
        angle = random.uniform(-0.5, 0.5)
        direction = -1 if self.serve_to == 0 else 1
        self.ball["vx"] = direction * self.SPEED0 * math.cos(angle)
        self.ball["vy"] = self.SPEED0 * math.sin(angle)
        self.trail.clear()
        self.last_hitter = None
        self._set_phase("serve")

    def _move_paddles(self, dt):
        for i, p in enumerate(self.paddles):
            if p.grow_until and self.t > p.grow_until:
                p.grow_until = 0.0
                p.y += (p.h - p.base_h) / 2
                p.h = p.base_h
            pid = self.slots[i]
            if pid is not None:
                pos = self.hub.position(pid)
                target = (pos if pos is not None else 0.5) * (self.h - p.h)
                p.y += (target - p.y) * min(1.0, dt * 30)
            else:
                p.y += max(-self.AI_SPEED * dt, min(self.AI_SPEED * dt, self._ai_target(i, p) - p.y))
            p.y = max(0.0, min(self.h - p.h, p.y))

    def _ai_target(self, i, p):
        b = self.ball
        coming = b and self.phase in ("playing", "serve") and (b["vx"] < 0) == (i == 0)
        if not coming:
            return (self.h - p.h) / 2
        return b["y"] + 1 - p.h / 2 + p.ai_error

    def _move_ball(self, dt):
        b = self.ball
        px = b["x"]
        b["y"] += b["vy"] * dt
        if b["y"] < 0:
            b["y"], b["vy"] = -b["y"], abs(b["vy"])
        elif b["y"] > self.h - 2:
            b["y"], b["vy"] = 2 * (self.h - 2) - b["y"], -abs(b["vy"])
        b["x"] += b["vx"] * dt
        self.trail.append((b["x"], b["y"]))

        left, right = self.paddles
        face_l, face_r = 3, self.w - 3
        if b["vx"] < 0 and px >= face_l > b["x"] and self._overlaps(left, b):
            b["x"] = face_l
            self._bounce(0, left, 1)
        elif b["vx"] > 0 and px + 2 <= face_r < b["x"] + 2 and self._overlaps(right, b):
            b["x"] = face_r - 2
            self._bounce(1, right, -1)
        elif b["x"] < -4:
            self._point(1)
        elif b["x"] > self.w + 2:
            self._point(0)

    @staticmethod
    def _overlaps(p, b):
        return b["y"] + 2 > p.y and b["y"] < p.y + p.h

    def _bounce(self, side, p, direction):
        b = self.ball
        off = ((b["y"] + 1) - (p.y + p.h / 2)) / (p.h / 2 + 1)
        angle = max(-1.0, min(1.0, off)) * 1.0  # up to ~57 degrees
        b["speed"] = min(self.SPEED_MAX, b["speed"] * self.SPEEDUP)
        b["vx"] = direction * b["speed"] * math.cos(angle)
        b["vy"] = b["speed"] * math.sin(angle)
        self.last_hitter = side
        other = self.paddles[1 - side]
        other.ai_error = random.uniform(-0.45, 0.45) * other.h  # the computer isn't perfect
        if self.slots[side] is not None:
            self.hub.event(self.slots[side], "hit")

    def _point(self, scorer):
        self.score[scorer] += 1
        self.flash[scorer] = 1.0
        self.serve_to = 1 - scorer
        self.ball = None
        self.orb = None
        self.next_orb = self.t + random.uniform(8, 14)
        for side, name in ((scorer, "point"), (1 - scorer, "miss")):
            if self.slots[side] is not None:
                self.hub.event(self.slots[side], name)
        self._set_phase("point")

    def _update_orb(self):
        b = self.ball
        if self.orb is None:
            if self.t >= self.next_orb:
                self.orb = {"x": random.randint(self.w // 3, 2 * self.w // 3),
                            "y": random.randint(4, self.h - 5), "until": self.t + 8}
            return
        o = self.orb
        if self.t > o["until"]:
            self.orb, self.next_orb = None, self.t + random.uniform(8, 14)
        elif self.last_hitter is not None and abs(b["x"] + 1 - o["x"]) <= 2 and abs(b["y"] + 1 - o["y"]) <= 2:
            p = self.paddles[self.last_hitter]
            if p.h < self.GROW_H:
                p.y -= (self.GROW_H - p.h) / 2
                p.h = self.GROW_H
            p.grow_until = self.t + self.GROW_SECONDS
            if self.slots[self.last_hitter] is not None:
                self.hub.event(self.slots[self.last_hitter], "power")
            self.orb, self.next_orb = None, self.t + random.uniform(10, 16)

    # ------------------------------------------------------------ views
    def _side_name(self, i):
        return "P%d" % (i + 1) if self.slots[i] is not None else "CPU"

    def _publish(self):
        views = {}
        for pid in self.hub.roster():
            side = self.slots.index(pid) if pid in self.slots else None
            view = {"t": "state", "running": True, "game": "paddle", "phase": self.phase,
                    "score": self.score, "win": self.WIN, "side": side,
                    "can_start": side is not None and (self.phase == "lobby" or
                                                       (self.phase == "over" and self.phase_t > 1.5))}
            if side is not None:
                view["player"] = side + 1
                view["color"] = _hex(self.paddles[side].color)
                view["opponent"] = "player" if self.slots[1 - side] is not None else "cpu"
                view["grown"] = bool(self.paddles[side].grow_until)
            if self.winner is not None:
                view["won"] = self.winner == side
            views[pid] = view
        self.hub.publish(views)

    # ------------------------------------------------------------ drawing
    def _draw(self):
        W, H = self.w, self.h
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)
        # each half glows faintly in its player's color, brighter after scoring
        for i, p in enumerate(self.paddles):
            glow = 0.05 + 0.35 * self.flash[i]
            if self.phase == "over" and self.winner == i:
                glow = 0.12 + 0.1 * math.sin(self.t * 5)
            x0 = 0 if i == 0 else W // 2
            d.rectangle([x0, 0, x0 + W // 2 - 1, H - 1], fill=_scale(p.color, glow))

        if self.orb:
            o, pulse = self.orb, 0.6 + 0.4 * math.sin(self.t * 8)
            col = _scale((60, 255, 120), pulse)
            d.point([(o["x"], o["y"]), (o["x"] - 1, o["y"]), (o["x"] + 1, o["y"]),
                     (o["x"], o["y"] - 1), (o["x"], o["y"] + 1)], fill=col)

        for i, p in enumerate(self.paddles):
            x = 1 if i == 0 else W - 3
            col = p.color if self.slots[i] is not None else _scale(p.color, 0.45)
            if p.grow_until and p.grow_until - self.t < 2 and int(self.t * 8) % 2:
                col = (60, 255, 120)  # power-up about to run out
            y0 = int(round(p.y))
            d.rectangle([x, y0, x + 1, y0 + int(p.h) - 1], fill=col)

        if self.phase == "lobby":
            self._draw_lobby(img)
        elif self.phase == "countdown":
            n = str(3 - int(self.phase_t))
            draw_big(img, 0, (H - 20) // 2, n, self.count_font, self.WHITE, align="center", width=W)
        elif self.phase == "over":
            self._draw_over(img)
        else:
            self._draw_score(img)
            if self.ball and (self.phase != "serve" or int(self.phase_t * 6) % 2 == 0):
                for k, (tx, ty) in enumerate(self.trail):
                    f = (k + 1) / (len(self.trail) + 1) * 0.35
                    d.rectangle([int(tx), int(ty), int(tx) + 1, int(ty) + 1], fill=_scale(self.WHITE, f))
                b = self.ball
                d.rectangle([int(b["x"]), int(b["y"]), int(b["x"]) + 1, int(b["y"]) + 1], fill=self.WHITE)
        return img

    def _draw_score(self, img):
        a, b = str(self.score[0]), str(self.score[1])
        mid = self.w // 2
        pixelfont.draw_text(img, (mid - 3 - pixelfont.text_width(a), 1), a, self.paddles[0].color)
        pixelfont.draw_text(img, (mid + 3, 1), b, self.paddles[1].color)

    def _centered(self, img, y, text, color, scale=1):
        x = (self.w - pixelfont.text_width(text) * scale) // 2
        pixelfont.draw_text(img, (x, y), text, color, scale=scale)

    def _draw_lobby(self, img):
        self._centered(img, 2, GAMES["paddle"], self.WHITE)
        for i in (0, 1):
            joined = self.slots[i] is not None
            text = ("P%d READY" % (i + 1)) if joined else ("P%d OPEN" % (i + 1))
            col = self.paddles[i].color if joined else self.GREY
            x = 6 if i == 0 else self.w - 6 - pixelfont.text_width(text)
            pixelfont.draw_text(img, (x, 13), text, col)
        if self._humans():
            hint = "PRESS START ON YOUR PHONE"
            if None in self.slots:
                hint += " - OR WAIT FOR PLAYER %d - JOIN AT %s" % (self.slots.index(None) + 1, self.join_url)
        else:
            hint = "TO PLAY OPEN %s ON YOUR PHONE" % self.join_url
        _ticker(img, 5, self.h - 6, self.w - 10, hint, self.GREY, self.t)

    def _draw_over(self, img):
        i = self.winner
        self._centered(img, 6, "%s WINS" % self._side_name(i), self.paddles[i].color, scale=2)
        self._centered(img, 22, "%d : %d" % tuple(self.score), self.WHITE)
