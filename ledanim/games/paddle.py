"""Paddle Duel: two paddles at the ends of the strip, 1-2 players (the computer fills in)."""
import math
import random
from collections import deque

from .base import WHITE, Game, scale
from .. import pixelfont


class Paddle:
    def __init__(self, color, h):
        self.color = color
        self.base_h = self.h = h
        self.y = 0.0
        self.grow_until = 0.0
        self.ai_error = 0.0


class PaddleDuel(Game):
    """Each hit speeds the ball up, and power orbs give the last player who hit
    the ball a bigger paddle for a while. First to 7 wins."""
    id = "paddle"
    title = "Paddle Duel"
    players = "1-2"
    max_players = 2
    controls = {"type": "slider"}
    WIN = 7
    PADDLE_H = 8
    GROW_H = 13
    GROW_SECONDS = 10
    SPEED0, SPEEDUP, SPEED_MAX = 40.0, 1.07, 115.0
    AI_SPEED = 34.0

    # ------------------------------------------------------------ state
    def reset(self):
        self.paddles = [Paddle(self.COLORS[0], self.PADDLE_H), Paddle(self.COLORS[1], self.PADDLE_H)]
        for p in self.paddles:
            p.y = (self.h - p.h) / 2
        self.score = [0, 0]
        self.ball = None
        self.trail = deque(maxlen=7)
        self.orb, self.next_orb = None, random.uniform(8, 14)
        self.serve_to = random.choice((0, 1))
        self.flash = [0.0, 0.0]
        self.last_hitter = None
        self.sub, self.sub_t = "serve", 0.0   # serve | rally | point
        self.match_t = 0.0
        self.pending_serve = True

    def name(self, i):
        return "P%d" % (i + 1) if self.slots[i] is not None else "CPU"

    def hud(self):
        return "%d : %d" % tuple(self.score)

    def play_message(self, side):
        msg = "First to %d" % self.WIN
        if self.slots[1 - side] is None:
            msg += " · vs computer"
        return msg

    def view_extra(self, side):
        return {"grown": bool(self.paddles[side].grow_until)}

    # ------------------------------------------------------------ loop
    def idle(self, dt):
        self.flash = [max(0.0, f - dt * 1.5) for f in self.flash]
        self._move_paddles(dt)

    def update_play(self, dt):
        self.match_t += dt
        self.sub_t += dt
        self.idle(dt)
        if self.pending_serve:
            self._serve()
        if self.sub == "serve" and self.sub_t >= 1.0:
            self.sub, self.sub_t = "rally", 0.0
        elif self.sub == "rally":
            self._move_ball(dt)
            self._update_orb()
        elif self.sub == "point" and self.sub_t >= 1.2:
            if max(self.score) >= self.WIN:
                w = 0 if self.score[0] > self.score[1] else 1
                self.finish("%s WINS" % self.name(w), self.COLORS[w],
                            "%d : %d" % tuple(self.score), winner=w)
            else:
                self._serve()

    def _serve(self):
        self.pending_serve = False
        self.ball = {"x": self.w / 2 - 1, "y": random.uniform(self.h * 0.3, self.h * 0.7) - 1,
                     "speed": self.SPEED0}
        angle = random.uniform(-0.5, 0.5)
        direction = -1 if self.serve_to == 0 else 1
        self.ball["vx"] = direction * self.SPEED0 * math.cos(angle)
        self.ball["vy"] = self.SPEED0 * math.sin(angle)
        self.trail.clear()
        self.last_hitter = None
        self.sub, self.sub_t = "serve", 0.0

    def _move_paddles(self, dt):
        for i, p in enumerate(self.paddles):
            if p.grow_until and self.match_t > p.grow_until:
                p.grow_until = 0.0
                p.y += (p.h - p.base_h) / 2
                p.h = p.base_h
            if self.slots[i] is not None:
                pos = self.pos(i)
                target = (pos if pos is not None else 0.5) * (self.h - p.h)
                p.y += (target - p.y) * min(1.0, dt * 30)
            else:
                p.y += max(-self.AI_SPEED * dt, min(self.AI_SPEED * dt, self._ai_target(i, p) - p.y))
            p.y = max(0.0, min(self.h - p.h, p.y))

    def _ai_target(self, i, p):
        b = self.ball
        coming = b and self.phase == "playing" and (b["vx"] < 0) == (i == 0)
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
        self.event(side, "hit")

    def _point(self, scorer):
        self.score[scorer] += 1
        self.flash[scorer] = 1.0
        self.serve_to = 1 - scorer
        self.ball = None
        self.orb = None
        self.next_orb = self.match_t + random.uniform(8, 14)
        self.event(scorer, "point")
        self.event(1 - scorer, "miss")
        self.sub, self.sub_t = "point", 0.0

    def _update_orb(self):
        b = self.ball
        if self.orb is None:
            if self.match_t >= self.next_orb:
                self.orb = {"x": random.randint(self.w // 3, 2 * self.w // 3),
                            "y": random.randint(4, self.h - 5), "until": self.match_t + 8}
            return
        o = self.orb
        if self.match_t > o["until"]:
            self.orb, self.next_orb = None, self.match_t + random.uniform(8, 14)
        elif self.last_hitter is not None and abs(b["x"] + 1 - o["x"]) <= 2 and abs(b["y"] + 1 - o["y"]) <= 2:
            p = self.paddles[self.last_hitter]
            if p.h < self.GROW_H:
                p.y -= (self.GROW_H - p.h) / 2
                p.h = self.GROW_H
            p.grow_until = self.match_t + self.GROW_SECONDS
            self.event(self.last_hitter, "power")
            self.orb, self.next_orb = None, self.match_t + random.uniform(10, 16)

    # ------------------------------------------------------------ drawing
    def draw_game(self, img, d):
        W, H = self.w, self.h
        winner = self.result["winner"] if self.result else None
        for i, p in enumerate(self.paddles):  # each half glows in its player's color
            glow = 0.05 + 0.35 * self.flash[i]
            if winner == i:
                glow = 0.5 + 0.3 * math.sin(self.t * 5)
            x0 = 0 if i == 0 else W // 2
            d.rectangle([x0, 0, x0 + W // 2 - 1, H - 1], fill=scale(p.color, glow))

        if self.orb:
            o, pulse = self.orb, 0.6 + 0.4 * math.sin(self.t * 8)
            d.point([(o["x"], o["y"]), (o["x"] - 1, o["y"]), (o["x"] + 1, o["y"]),
                     (o["x"], o["y"] - 1), (o["x"], o["y"] + 1)], fill=scale((60, 255, 120), pulse))

        for i, p in enumerate(self.paddles):
            x = 1 if i == 0 else W - 3
            col = p.color if self.slots[i] is not None else scale(p.color, 0.45)
            if p.grow_until and p.grow_until - self.match_t < 2 and int(self.t * 8) % 2:
                col = (60, 255, 120)  # power-up about to run out
            y0 = int(round(p.y))
            d.rectangle([x, y0, x + 1, y0 + int(p.h) - 1], fill=col)

        if self.phase == "playing":
            a, b = str(self.score[0]), str(self.score[1])
            mid = W // 2
            pixelfont.draw_text(img, (mid - 3 - pixelfont.text_width(a), 1), a, self.paddles[0].color)
            pixelfont.draw_text(img, (mid + 3, 1), b, self.paddles[1].color)
            if self.ball and (self.sub != "serve" or int(self.sub_t * 6) % 2 == 0):
                for k, (tx, ty) in enumerate(self.trail):
                    f = (k + 1) / (len(self.trail) + 1) * 0.35
                    d.rectangle([int(tx), int(ty), int(tx) + 1, int(ty) + 1], fill=scale(WHITE, f))
                bl = self.ball
                d.rectangle([int(bl["x"]), int(bl["y"]), int(bl["x"]) + 1, int(bl["y"]) + 1], fill=WHITE)
