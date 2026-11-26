"""Brick Storm: a sideways brick breaker for one player.

The paddle is on the left edge, the wall of bricks on the right. Tougher bricks
take several hits, every level brings a new layout and a faster ball, and broken
bricks sometimes release capsules that drift towards the paddle:
  green  = longer paddle, cyan = two extra balls, yellow = slower ball.
"""
import colorsys
import math
import random

from .base import WHITE, GREY, Game, centered, scale
from .. import pixelfont

CAPSULES = {"wide": (60, 230, 90), "multi": (0, 220, 255), "slow": (255, 210, 0)}


class BrickStorm(Game):
    id = "bricks"
    title = "Brick Storm"
    players = "1"
    max_players = 1
    controls = {"type": "slider"}
    COLS = 8
    PITCH = 4          # brick 3x3 pixels + 1 pixel gap
    PADDLE_H, WIDE_H = 8, 13
    LIVES = 3

    def reset(self):
        self.rows = self.h // self.PITCH
        self.x0 = self.w - 2 - self.COLS * self.PITCH + 1
        self.score, self.lives, self.level = 0, self.LIVES, 1
        self.paddle_h, self.paddle_y = self.PADDLE_H, (self.h - self.PADDLE_H) / 2
        self.wide_until = 0.0
        self.play_t = 0.0
        self.capsules = []
        self.banner_until = 0.0
        self._new_level()

    def hud(self):
        return "Score %d · Level %d · %s" % (self.score, self.level, "♥" * self.lives)

    def play_message(self, side):
        return "Slide to move the paddle"

    def view_extra(self, side):
        return {"grown": self.paddle_h > self.PADDLE_H}

    # ------------------------------------------------------------ levels
    def _new_level(self):
        R, C, n = self.rows, self.COLS, self.level
        grid = [[0] * C for _ in range(R)]
        kind = (n - 1) % 4
        for r in range(R):
            for c in range(C):
                if kind == 0:      # solid wall, the far columns are tougher
                    hp = 2 if c >= C - 2 else 1
                elif kind == 1:    # checkerboard of soft and tough bricks
                    hp = 2 if (r + c) % 2 else 1
                elif kind == 2:    # diamond
                    d = abs(r - (R - 1) / 2) + abs(c - (C - 1) / 2)
                    hp = 0 if d > 4.5 else (3 if d < 1.5 else 1)
                else:              # stripes with gaps
                    hp = 0 if r % 3 == 2 else (2 if c % 2 else 1)
                if hp and n > 4:
                    hp = min(3, hp + (n - 1) // 4)
                grid[r][c] = hp
        self.grid = grid
        self.speed = min(80.0, 40.0 + 5.0 * (n - 1))
        self.balls = []
        self.capsules = []
        self._serve()

    def _serve(self):
        self.balls = [{"x": 3.0, "y": self.paddle_y + self.paddle_h / 2 - 1, "vx": 0.0, "vy": 0.0,
                       "stuck": 1.2}]

    def _bricks_left(self):
        return any(hp for row in self.grid for hp in row)

    # ------------------------------------------------------------ loop
    def idle(self, dt):
        self._move_paddle(dt)
        for b in self.balls:
            if b.get("stuck"):
                b["y"] = self.paddle_y + self.paddle_h / 2 - 1

    def _move_paddle(self, dt):
        if self.wide_until and self.play_t > self.wide_until:
            self.wide_until = 0.0
            self.paddle_y += (self.paddle_h - self.PADDLE_H) / 2
            self.paddle_h = self.PADDLE_H
        pos = self.pos(0)
        target = (pos if pos is not None else 0.5) * (self.h - self.paddle_h)
        self.paddle_y += (target - self.paddle_y) * min(1.0, dt * 30)
        self.paddle_y = max(0.0, min(self.h - self.paddle_h, self.paddle_y))

    def update_play(self, dt):
        self.play_t += dt
        self._move_paddle(dt)
        for b in list(self.balls):
            if b.get("stuck"):
                b["stuck"] -= dt
                b["y"] = self.paddle_y + self.paddle_h / 2 - 1
                if b["stuck"] <= 0:
                    del b["stuck"]
                    a = random.uniform(-0.5, 0.5)
                    b["vx"], b["vy"] = self.speed * math.cos(a), self.speed * math.sin(a)
                continue
            self._move_ball(b, dt)
            if b["x"] < -3:
                self.balls.remove(b)
        self._move_capsules(dt)

        if not self.balls:
            self.lives -= 1
            self.event(0, "miss")
            if self.lives <= 0:
                self.finish("GAME OVER", (255, 80, 60), "SCORE %d - LEVEL %d" % (self.score, self.level),
                            score=self.score)
                return
            self.wide_until = 0.0
            self.paddle_h = self.PADDLE_H
            self._serve()
        elif not self._bricks_left():
            self.level += 1
            self.score += 100 * (self.level - 1)
            self.event(0, "point")
            self.banner_until = self.play_t + 2.0
            self._new_level()

    def _move_ball(self, b, dt):
        dx, dy = b["vx"] * dt, b["vy"] * dt
        steps = max(1, int(math.ceil(max(abs(dx), abs(dy)) / 0.8)))
        dx, dy = dx / steps, dy / steps
        for _ in range(steps):
            px = b["x"]
            b["x"] += dx
            if self._hit_bricks(b):
                b["x"] -= dx
                b["vx"], dx = -b["vx"], -dx
            b["y"] += dy
            if b["y"] < 0:
                b["y"], b["vy"], dy = -b["y"], abs(b["vy"]), abs(dy)
            elif b["y"] > self.h - 2:
                b["y"], b["vy"], dy = 2 * (self.h - 2) - b["y"], -abs(b["vy"]), -abs(dy)
            elif self._hit_bricks(b):
                b["y"] -= dy
                b["vy"], dy = -b["vy"], -dy
            if b["x"] > self.w - 2:
                b["x"], b["vx"], dx = self.w - 2, -abs(b["vx"]), -abs(dx)
            if b["vx"] < 0 and px >= 3 > b["x"] and \
                    b["y"] + 2 > self.paddle_y and b["y"] < self.paddle_y + self.paddle_h:
                b["x"] = 3
                off = ((b["y"] + 1) - (self.paddle_y + self.paddle_h / 2)) / (self.paddle_h / 2 + 1)
                a = max(-1.0, min(1.0, off)) * 1.0
                sp = math.hypot(b["vx"], b["vy"])
                b["vx"], b["vy"] = sp * math.cos(a), sp * math.sin(a)
                dx, dy = b["vx"] * dt / steps, b["vy"] * dt / steps
                self.event(0, "hit")

    def _cell(self, px, py):
        if px < self.x0 or py < 0:
            return None
        c, r = (px - self.x0) // self.PITCH, py // self.PITCH
        if c >= self.COLS or r >= self.rows:
            return None
        if (px - self.x0) % self.PITCH == 3 or py % self.PITCH == 3:
            return None  # gap between bricks
        return (r, c) if self.grid[r][c] > 0 else None

    def _hit_bricks(self, b):
        hit = set()
        for px in (int(b["x"]), int(b["x"]) + 1):
            for py in (int(b["y"]), int(b["y"]) + 1):
                cell = self._cell(px, py)
                if cell:
                    hit.add(cell)
        for r, c in hit:
            self.grid[r][c] -= 1
            if self.grid[r][c] == 0:
                self.score += 10 * self.level
                if random.random() < 0.12:
                    self.capsules.append({"x": float(self.x0 + c * self.PITCH), "y": r * self.PITCH + 0.5,
                                          "kind": random.choice(list(CAPSULES))})
            else:
                self.score += 2
        return bool(hit)

    def _move_capsules(self, dt):
        for cap in list(self.capsules):
            cap["x"] -= 16 * dt
            if cap["x"] <= 3 and cap["y"] + 2 > self.paddle_y and cap["y"] < self.paddle_y + self.paddle_h:
                self.capsules.remove(cap)
                self._apply(cap["kind"])
            elif cap["x"] < -2:
                self.capsules.remove(cap)

    def _apply(self, kind):
        self.event(0, "power")
        self.score += 25
        if kind == "wide":
            if self.paddle_h < self.WIDE_H:
                self.paddle_y -= (self.WIDE_H - self.paddle_h) / 2
                self.paddle_h = self.WIDE_H
            self.wide_until = self.play_t + 15
        elif kind == "multi":
            free = [b for b in self.balls if not b.get("stuck")]
            if free:
                src = free[0]
                sp = math.hypot(src["vx"], src["vy"])
                for a in (-0.6, 0.6):
                    ang = math.atan2(src["vy"], src["vx"]) + a
                    self.balls.append({"x": src["x"], "y": src["y"],
                                       "vx": abs(sp * math.cos(ang)) * (1 if src["vx"] > 0 else -1),
                                       "vy": sp * math.sin(ang)})
        elif kind == "slow":
            for b in self.balls:
                sp = math.hypot(b["vx"], b["vy"])
                if sp > 0:
                    f = max(0.6, (self.speed * 0.75) / sp)
                    b["vx"] *= f
                    b["vy"] *= f

    # ------------------------------------------------------------ drawing
    def _brick_color(self, r, hp):
        hue = r / max(1, self.rows) * 0.8
        base = tuple(int(v * 255) for v in colorsys.hsv_to_rgb(hue, 0.85, 1.0))
        return scale(base, 0.75), hp

    def draw_game(self, img, d):
        for r in range(self.rows):
            for c in range(self.COLS):
                hp = self.grid[r][c]
                if not hp:
                    continue
                col, _ = self._brick_color(r, hp)
                x, y = self.x0 + c * self.PITCH, r * self.PITCH
                d.rectangle([x, y, x + 2, y + 2], fill=col)
                if hp >= 2:   # tougher bricks have a bright core
                    d.point((x + 1, y + 1), fill=WHITE if hp >= 3 else scale(col, 1.6))
        for cap in self.capsules:
            col = CAPSULES[cap["kind"]]
            if int(self.t * 6) % 2:
                col = scale(col, 0.6)
            x, y = int(cap["x"]), int(cap["y"])
            d.rectangle([x, y, x + 1, y + 1], fill=col)

        if self.phase == "playing":  # HUD in the free area, dim so the ball stays visible
            pixelfont.draw_text(img, (6, 1), str(self.score), scale(GREY, 0.8))
            for i in range(self.lives):
                d.point((6 + i * 3, 8), fill=scale(self.COLORS[0], 0.7))
            if self.play_t < self.banner_until:
                centered(img, 13, "LEVEL %d" % self.level, WHITE)

        col = self.COLORS[0]
        if self.wide_until and self.wide_until - self.play_t < 2 and int(self.t * 8) % 2:
            col = CAPSULES["wide"]
        y0 = int(round(self.paddle_y))
        d.rectangle([1, y0, 2, y0 + int(self.paddle_h) - 1], fill=col)
        for b in self.balls:
            if b.get("stuck") and int(self.t * 6) % 2:
                continue
            d.rectangle([int(b["x"]), int(b["y"]), int(b["x"]) + 1, int(b["y"]) + 1], fill=WHITE)
