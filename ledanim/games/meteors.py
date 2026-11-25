"""Meteor Drift: steer a small ship through a field of drifting rocks, one player.

The field wraps around at the edges. Drag the joystick to turn and accelerate in
that direction, hold FIRE to shoot. Big rocks split into smaller, faster ones.
Clear a wave and the next one is bigger. Every 5000 points earn an extra ship.
"""
import math
import random

from .base import WHITE, GREY, Game, centered, scale
from .. import pixelfont

ROCK_R = {3: 4.5, 2: 2.8, 1: 1.6}
ROCK_POINTS = {3: 20, 2: 50, 1: 100}
ROCK_COLOR = {3: (170, 120, 80), 2: (205, 150, 95), 1: (235, 195, 130)}
SHIP_COLOR = (0, 200, 255)


class MeteorDrift(Game):
    id = "meteors"
    title = "Meteor Drift"
    players = "1"
    max_players = 1
    controls = {"type": "stick", "buttons": ["fire"]}
    LIVES = 3
    TURN = 7.0          # radians per second
    THRUST = 70.0       # pixels per second^2 at full stick
    MAX_SPEED = 45.0
    BULLET_SPEED = 80.0
    FIRE_EVERY = 0.2
    MAX_BULLETS = 6

    def reset(self):
        self.score, self.lives, self.wave = 0, self.LIVES, 0
        self.next_life = 5000
        self.ship = self._new_ship(invulnerable=0)
        self.rocks, self.bullets, self.particles = [], [], []
        self.cooldown = 0.0
        self.respawn_at = None
        self.wave_at = 0.0
        self.end_at = None
        self.play_t = 0.0
        self.banner_until = 0.0
        self._spawn_wave()

    def hud(self):
        return "Score %d · Wave %d · %s" % (self.score, self.wave, "♥" * max(0, self.lives))

    def play_message(self, side):
        return "Drag to steer · hold FIRE to shoot"

    # ------------------------------------------------------------ setup
    def _new_ship(self, invulnerable=2.0):
        return {"x": self.w / 2, "y": self.h / 2, "vx": 0.0, "vy": 0.0, "a": -math.pi / 2,
                "inv": invulnerable, "thrust": 0.0, "alive": True}

    def _wrap_delta(self, a, b, size):
        return (a - b + size / 2) % size - size / 2

    def _dist(self, x1, y1, x2, y2):
        return math.hypot(self._wrap_delta(x1, x2, self.w), self._wrap_delta(y1, y2, self.h))

    def _rock(self, x, y, size, heading=None):
        speed = random.uniform(5, 10) * (1 + 0.5 * (3 - size)) * (1 + 0.08 * self.wave)
        a = heading if heading is not None else random.uniform(0, 2 * math.pi)
        return {"x": x, "y": y, "vx": speed * math.cos(a), "vy": speed * math.sin(a), "size": size,
                "rot": random.uniform(0, 6.3), "spin": random.uniform(-1.5, 1.5),
                "shape": [random.uniform(0.75, 1.15) for _ in range(7)]}

    def _spawn_wave(self):
        self.wave += 1
        self.banner_until = self.play_t + 2.0
        for _ in range(min(7, 2 + self.wave)):
            for _ in range(50):  # keep new rocks away from the ship
                x, y = random.uniform(0, self.w), random.uniform(0, self.h)
                if self._dist(x, y, self.ship["x"], self.ship["y"]) > 22:
                    break
            self.rocks.append(self._rock(x, y, 3))

    # ------------------------------------------------------------ loop
    def idle(self, dt):
        self._move_rocks(dt)

    def update_play(self, dt):
        self.play_t += dt
        self._move_rocks(dt)
        self._move_particles(dt)
        s = self.ship
        if s["alive"]:
            self._steer(s, dt)
            self._shoot(s, dt)
        self._move_bullets(dt)
        self._collide()

        if self.end_at is not None:
            if self.play_t >= self.end_at:
                self.finish("GAME OVER", (255, 80, 60), "SCORE %d - WAVE %d" % (self.score, self.wave),
                            score=self.score)
            return
        if not s["alive"] and self.respawn_at is not None and self.play_t >= self.respawn_at:
            if all(self._dist(r["x"], r["y"], self.w / 2, self.h / 2) > ROCK_R[r["size"]] + 8 for r in self.rocks):
                self.ship = self._new_ship()
                self.respawn_at = None
        if not self.rocks:
            if not self.wave_at:
                self.wave_at = self.play_t + 1.5
            elif self.play_t >= self.wave_at:
                self.wave_at = 0.0
                self._spawn_wave()

    def _steer(self, s, dt):
        sx, sy = self.stick(0)
        mag = math.hypot(sx, sy)
        s["thrust"] = 0.0
        if mag > 0.25:
            target = math.atan2(sy, sx)
            diff = (target - s["a"] + math.pi) % (2 * math.pi) - math.pi
            s["a"] += max(-self.TURN * dt, min(self.TURN * dt, diff))
            s["thrust"] = mag * max(0.0, math.cos(diff))
            s["vx"] += math.cos(s["a"]) * self.THRUST * s["thrust"] * dt
            s["vy"] += math.sin(s["a"]) * self.THRUST * s["thrust"] * dt
        friction = max(0.0, 1 - 0.5 * dt)
        s["vx"] *= friction
        s["vy"] *= friction
        sp = math.hypot(s["vx"], s["vy"])
        if sp > self.MAX_SPEED:
            s["vx"] *= self.MAX_SPEED / sp
            s["vy"] *= self.MAX_SPEED / sp
        s["x"] = (s["x"] + s["vx"] * dt) % self.w
        s["y"] = (s["y"] + s["vy"] * dt) % self.h
        s["inv"] = max(0.0, s["inv"] - dt)

    def _shoot(self, s, dt):
        self.cooldown = max(0.0, self.cooldown - dt)
        want = self.held(0, "fire") or self.pressed(0, "fire")
        if want and self.cooldown == 0 and len(self.bullets) < self.MAX_BULLETS:
            self.cooldown = self.FIRE_EVERY
            ca, sa = math.cos(s["a"]), math.sin(s["a"])
            self.bullets.append({"x": s["x"] + ca * 3, "y": s["y"] + sa * 3,
                                 "vx": s["vx"] + ca * self.BULLET_SPEED, "vy": s["vy"] + sa * self.BULLET_SPEED,
                                 "life": 0.9})

    def _move_rocks(self, dt):
        for r in self.rocks:
            r["x"] = (r["x"] + r["vx"] * dt) % self.w
            r["y"] = (r["y"] + r["vy"] * dt) % self.h
            r["rot"] += r["spin"] * dt

    def _move_bullets(self, dt):
        for b in list(self.bullets):
            b["x"] = (b["x"] + b["vx"] * dt) % self.w
            b["y"] = (b["y"] + b["vy"] * dt) % self.h
            b["life"] -= dt
            if b["life"] <= 0:
                self.bullets.remove(b)

    def _move_particles(self, dt):
        for p in list(self.particles):
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["life"] -= dt
            if p["life"] <= 0:
                self.particles.remove(p)

    def _burst(self, x, y, color, n=10, speed=20):
        for _ in range(n):
            a, v = random.uniform(0, 2 * math.pi), random.uniform(0.3, 1) * speed
            self.particles.append({"x": x, "y": y, "vx": v * math.cos(a), "vy": v * math.sin(a),
                                   "life": random.uniform(0.3, 0.8), "color": color})

    def _collide(self):
        for b in list(self.bullets):
            for r in list(self.rocks):
                if self._dist(b["x"], b["y"], r["x"], r["y"]) < ROCK_R[r["size"]] + 0.5:
                    self.bullets.remove(b)
                    self._break(r)
                    break
        s = self.ship
        if not s["alive"] or s["inv"] > 0 or self.end_at is not None:
            return
        for r in self.rocks:
            if self._dist(s["x"], s["y"], r["x"], r["y"]) < ROCK_R[r["size"]] + 1.2:
                s["alive"] = False
                self.lives -= 1
                self.event(0, "miss")
                self._burst(s["x"], s["y"], SHIP_COLOR, 18, 26)
                if self.lives <= 0:
                    self.end_at = self.play_t + 1.8
                else:
                    self.respawn_at = self.play_t + 1.5
                break

    def _break(self, r):
        self.rocks.remove(r)
        self.score += ROCK_POINTS[r["size"]]
        self.event(0, "hit")
        self._burst(r["x"], r["y"], ROCK_COLOR[r["size"]], 4 + 2 * r["size"], 14)
        if r["size"] > 1:
            heading = math.atan2(r["vy"], r["vx"])
            for da in (-0.7, 0.7):
                self.rocks.append(self._rock(r["x"], r["y"], r["size"] - 1, heading + da))
        if self.score >= self.next_life:
            self.next_life += 5000
            self.lives += 1
            self.event(0, "power")

    # ------------------------------------------------------------ drawing
    def _offsets(self, x, y, r):
        xs = [0] + ([self.w] if x < r + 1 else []) + ([-self.w] if x > self.w - r - 1 else [])
        ys = [0] + ([self.h] if y < r + 1 else []) + ([-self.h] if y > self.h - r - 1 else [])
        return [(ox, oy) for ox in xs for oy in ys]

    def draw_game(self, img, d):
        # a few fixed background stars
        rnd = random.Random(3)
        for _ in range(18):
            d.point((rnd.randrange(self.w), rnd.randrange(self.h)), fill=(28, 28, 40))

        for r in self.rocks:
            R, col = ROCK_R[r["size"]], ROCK_COLOR[r["size"]]
            for ox, oy in self._offsets(r["x"], r["y"], R):
                pts = [(r["x"] + ox + math.cos(r["rot"] + k * 2 * math.pi / 7) * R * f,
                        r["y"] + oy + math.sin(r["rot"] + k * 2 * math.pi / 7) * R * f)
                       for k, f in enumerate(r["shape"])]
                d.polygon(pts, fill=scale(col, 0.3), outline=col)

        for b in self.bullets:
            d.point((int(b["x"]), int(b["y"])), fill=(255, 240, 120))
        for p in self.particles:
            d.point((int(p["x"]), int(p["y"])), fill=scale(p["color"], min(1.0, p["life"] * 2)))

        s = self.ship
        if s["alive"] and not (s["inv"] > 0 and int(self.t * 10) % 2):
            ca, sa = math.cos(s["a"]), math.sin(s["a"])
            for ox, oy in self._offsets(s["x"], s["y"], 3):
                x, y = s["x"] + ox, s["y"] + oy
                nose = (x + ca * 3, y + sa * 3)
                left = (x + math.cos(s["a"] + 2.5) * 2.2, y + math.sin(s["a"] + 2.5) * 2.2)
                right = (x + math.cos(s["a"] - 2.5) * 2.2, y + math.sin(s["a"] - 2.5) * 2.2)
                d.polygon([nose, left, right], fill=scale(SHIP_COLOR, 0.5), outline=SHIP_COLOR)
                d.point((int(round(nose[0])), int(round(nose[1]))), fill=WHITE)
                if s["thrust"] > 0.2 and int(self.t * 20) % 2:
                    d.point((int(round(x - ca * 3)), int(round(y - sa * 3))), fill=(255, 140, 0))

        if self.phase == "playing":
            pixelfont.draw_text(img, (1, 1), str(self.score), scale(GREY, 0.8))
            for i in range(max(0, self.lives)):
                d.point((self.w - 2 - i * 3, 1), fill=scale(SHIP_COLOR, 0.8))
            if self.play_t < self.banner_until:
                centered(img, 13, "WAVE %d" % self.wave, WHITE)
