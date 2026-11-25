"""Swarm Siege: hold the left edge against a marching swarm of drones, one player.

Your ship moves up and down the left edge (slider) and shoots to the right (FIRE).
The swarm marches up and down and steps closer every time it reaches an edge;
the fewer drones are left, the faster it marches. Some drones break formation
and dive at you. Shoot the golden drone for double shots. Clear the swarm and
the next wave starts closer and shoots more. If the swarm reaches you, it's over.
"""
import math
import random

from .base import WHITE, GREY, Game, centered, scale
from .. import pixelfont

# 4x3 drone designs, two animation frames each
SPRITES = {
    "ring":  ([".##.", "#..#", ".##."], [".##.", "####", ".##."]),
    "moth":  (["#..#", "####", "#..#"], [".##.", "####", ".##."]),
    "spike": (["..##", "####", "..##"], [".###", "##..", ".###"]),
}
KINDS = ["spike", "moth", "moth", "ring", "ring"]  # by column, front (left) to back
COLORS = {"ring": (80, 220, 160), "moth": (220, 80, 200), "spike": (255, 170, 40)}
POINTS = {"ring": 30, "moth": 20, "spike": 10}
GOLD = (255, 225, 80)
SHIP = (0, 170, 255)
SHIP_SHAPE = ["#..", "##.", "###", "##.", "#.."]  # 3x5, pointing right


def _pixels(rows):
    return [(x, y) for y, row in enumerate(rows) for x, ch in enumerate(row) if ch == "#"]


SPRITE_PX = {k: (_pixels(a), _pixels(b)) for k, (a, b) in SPRITES.items()}
SHIP_PX = _pixels(SHIP_SHAPE)


class SwarmSiege(Game):
    id = "swarm"
    title = "Swarm Siege"
    players = "1"
    max_players = 1
    controls = {"type": "slider", "buttons": ["fire"]}
    COLS, ROWS = 5, 4
    PX, PY = 7, 6          # spacing of the formation
    LIVES = 3
    BULLET_SPEED = 95.0
    FIRE_EVERY = 0.22
    SHIP_H = 5

    def reset(self):
        self.score, self.lives, self.wave = 0, self.LIVES, 0
        self.ship_y = (self.h - self.SHIP_H) / 2
        self.inv = 0.0
        self.play_t = 0.0
        self.cooldown = 0.0
        self.double_until = 0.0
        self.particles = []
        self.end_at = None
        self.banner_until = 0.0
        self._new_wave()

    def hud(self):
        return "Score %d · Wave %d · %s" % (self.score, self.wave, "♥" * max(0, self.lives))

    def play_message(self, side):
        return "Slide to move · hold FIRE to shoot"

    # ------------------------------------------------------------ waves
    def _new_wave(self):
        self.wave += 1
        self.banner_until = self.play_t + 2.0
        self.alive = [[True] * self.ROWS for _ in range(self.COLS)]
        self.total = self.COLS * self.ROWS
        width = (self.COLS - 1) * self.PX + 4
        self.fx = float(self.w - width - 2 - min(16, 3 * (self.wave - 1)))
        self.fy = 1.0
        self.dir = 1
        self.frame = 0
        self.march_at = self.play_t + 0.5
        self.bullets, self.shots, self.divers = [], [], []
        self.gold = (random.randrange(1, self.COLS), random.randrange(self.ROWS))
        self.next_dive = self.play_t + random.uniform(5, 9)
        self.next_shot = self.play_t + 1.5

    def _count(self):
        return sum(v for col in self.alive for v in col)

    def _drone_xy(self, c, r):
        return self.fx + c * self.PX, self.fy + r * self.PY

    def _bounds(self):
        cols = [c for c in range(self.COLS) if any(self.alive[c])]
        rows = [r for r in range(self.ROWS) if any(self.alive[c][r] for c in range(self.COLS))]
        if not cols:
            return None
        return (self.fx + min(cols) * self.PX, self.fy + min(rows) * self.PY,
                self.fx + max(cols) * self.PX + 3, self.fy + max(rows) * self.PY + 2)

    # ------------------------------------------------------------ loop
    def idle(self, dt):
        self._move_ship(dt)
        self.play_t += dt
        if self.phase == "lobby" and self.play_t >= self.march_at:
            self.march_at = self.play_t + 0.5
            self._march()

    def _move_ship(self, dt):
        pos = self.pos(0)
        target = (pos if pos is not None else 0.5) * (self.h - self.SHIP_H)
        self.ship_y += (target - self.ship_y) * min(1.0, dt * 30)
        self.ship_y = max(0.0, min(self.h - self.SHIP_H, self.ship_y))

    def _march(self):
        self.frame ^= 1
        b = self._bounds()
        if not b:
            return
        if (self.dir > 0 and b[3] + 1 > self.h - 1) or (self.dir < 0 and b[1] - 1 < 0):
            self.dir = -self.dir
            self.fx -= 2  # step towards the player
        else:
            self.fy += self.dir

    def update_play(self, dt):
        self.play_t += dt
        self._move_ship(dt)
        self.inv = max(0.0, self.inv - dt)
        self._move_particles(dt)
        if self.end_at is not None:
            if self.play_t >= self.end_at:
                self.finish("GAME OVER", (255, 80, 60), "SCORE %d - WAVE %d" % (self.score, self.wave),
                            score=self.score)
            return

        # the swarm marches faster as it shrinks, and faster every wave
        if self.play_t >= self.march_at:
            frac = self._count() / self.total
            interval = (0.06 + 0.5 * frac) / (1 + 0.12 * (self.wave - 1))
            self.march_at = self.play_t + interval
            self._march()
        self._shoot(dt)
        self._enemy_fire()
        self._dive()
        self._move_bullets(dt)
        self._move_divers(dt)

        b = self._bounds()
        if b and b[0] <= 4:
            self._explode(2, self.ship_y + 2, SHIP)
            self.lives = 0
            self.end_at = self.play_t + 1.8
            self.event(0, "miss")
        elif not b and not self.divers:
            self.score += 100 * self.wave
            self.event(0, "point")
            self._new_wave()

    def _shoot(self, dt):
        self.cooldown = max(0.0, self.cooldown - dt)
        if (self.held(0, "fire") or self.pressed(0, "fire")) and self.cooldown == 0:
            limit = 4 if self.play_t < self.double_until else 2
            if len(self.bullets) < limit:
                self.cooldown = self.FIRE_EVERY
                y = self.ship_y + 2
                ys = (y - 2, y + 2) if self.play_t < self.double_until else (y,)
                for by in ys:
                    self.bullets.append([4.0, by])

    def _enemy_fire(self):
        if self.play_t < self.next_shot or len(self.shots) >= 2 + self.wave // 2:
            return
        self.next_shot = self.play_t + random.uniform(1.0, 2.2) / (1 + 0.15 * (self.wave - 1))
        fronts = []
        for r in range(self.ROWS):  # the front-most drone in each row can shoot
            for c in range(self.COLS):
                if self.alive[c][r]:
                    fronts.append((c, r))
                    break
        if fronts:
            if random.random() < 0.4 + 0.05 * self.wave:  # some shots come from the row nearest the ship
                fronts.sort(key=lambda cr: abs(self._drone_xy(*cr)[1] + 1 - (self.ship_y + 2)))
            else:
                random.shuffle(fronts)
            x, y = self._drone_xy(*fronts[0])
            self.shots.append([x - 1, y + 1, 26 + 3 * self.wave])

    def _dive(self):
        if self.play_t < self.next_dive or len(self.divers) >= 1 + self.wave // 3:
            return
        self.next_dive = self.play_t + random.uniform(4, 8) / (1 + 0.1 * self.wave)
        cand = [(c, r) for c in range(self.COLS) for r in range(self.ROWS)
                if self.alive[c][r] and (c, r) != self.gold]
        if len(cand) < 2:
            return
        c, r = random.choice(cand)
        self.alive[c][r] = False
        x, y = self._drone_xy(c, r)
        self.divers.append({"x": x, "y": y, "kind": KINDS[c], "t": 0.0, "y0": y, "speed": 24 + 2 * self.wave})

    def _move_divers(self, dt):
        for d in list(self.divers):
            d["t"] += dt
            d["x"] -= d["speed"] * dt
            # swoop towards the ship, with a wobble
            target = self.ship_y + 1 + math.sin(d["t"] * 5) * 5
            d["y"] += max(-18 * dt, min(18 * dt, target - d["y"]))
            if d["x"] < -5:
                self.divers.remove(d)
            elif self._hits_ship(d["x"], d["y"], 4, 3):
                self.divers.remove(d)
                self._explode(d["x"] + 2, d["y"] + 1, COLORS[d["kind"]])
                self._ship_hit()

    def _move_bullets(self, dt):
        for b in list(self.bullets):
            steps = 3
            for _ in range(steps):
                b[0] += self.BULLET_SPEED * dt / steps
                if self._bullet_hits(b):
                    self.bullets.remove(b)
                    break
            else:
                if b[0] > self.w:
                    self.bullets.remove(b)
        for s in list(self.shots):
            s[0] -= s[2] * dt
            if s[0] < -1:
                self.shots.remove(s)
            elif self._hits_ship(s[0], s[1], 1, 1):
                self.shots.remove(s)
                self._ship_hit()

    def _bullet_hits(self, b):
        bx, by = b
        for d in list(self.divers):
            if d["x"] - 0.5 <= bx <= d["x"] + 4 and d["y"] - 0.5 <= by <= d["y"] + 3:
                self.divers.remove(d)
                self.score += 50
                self._explode(d["x"] + 2, d["y"] + 1, COLORS[d["kind"]])
                self.event(0, "hit")
                return True
        c = int((bx - self.fx) // self.PX)
        r = int((by - self.fy) // self.PY)
        if 0 <= c < self.COLS and 0 <= r < self.ROWS and self.alive[c][r]:
            x, y = self._drone_xy(c, r)
            if x <= bx < x + 4 and y - 0.5 <= by < y + 3.5:
                self.alive[c][r] = False
                kind = KINDS[c]
                self.score += POINTS[kind] * self.wave
                self.event(0, "hit")
                if (c, r) == self.gold:
                    self.double_until = self.play_t + 12
                    self.score += 100
                    self.event(0, "power")
                    self._explode(x + 2, y + 1, GOLD, 14)
                else:
                    self._explode(x + 2, y + 1, COLORS[kind])
                return True
        return False

    def _hits_ship(self, x, y, w, h):
        return x < 4 and x + w > 1 and y < self.ship_y + self.SHIP_H and y + h > self.ship_y

    def _ship_hit(self):
        if self.inv > 0 or self.end_at is not None:
            return
        self.lives -= 1
        self.event(0, "miss")
        self._explode(2, self.ship_y + 2, SHIP, 16)
        self.shots = []
        if self.lives <= 0:
            self.end_at = self.play_t + 1.8
        else:
            self.inv = 2.0

    def _explode(self, x, y, color, n=8):
        for _ in range(n):
            a, v = random.uniform(0, 2 * math.pi), random.uniform(5, 22)
            self.particles.append([x, y, v * math.cos(a), v * math.sin(a), random.uniform(0.3, 0.7), color])

    def _move_particles(self, dt):
        for p in list(self.particles):
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[4] -= dt
            if p[4] <= 0:
                self.particles.remove(p)

    # ------------------------------------------------------------ drawing
    def _sprite(self, img, x, y, kind, color):
        W, H = self.w, self.h
        px = img.load()
        for dx, dy in SPRITE_PX[kind][self.frame]:
            X, Y = int(x) + dx, int(y) + dy
            if 0 <= X < W and 0 <= Y < H:
                px[X, Y] = color

    def draw_game(self, img, d):
        for c in range(self.COLS):
            for r in range(self.ROWS):
                if self.alive[c][r]:
                    x, y = self._drone_xy(c, r)
                    kind = KINDS[c]
                    col = COLORS[kind]
                    if (c, r) == self.gold:
                        col = GOLD if int(self.t * 4) % 2 else scale(GOLD, 0.6)
                    self._sprite(img, x, y, kind, col)
        for dv in self.divers:
            self._sprite(img, dv["x"], dv["y"], dv["kind"], scale(COLORS[dv["kind"]], 1.2))
        for x, y in self.bullets:
            d.line([int(x), int(y), int(x) + 1, int(y)], fill=(255, 255, 255))
        for x, y, _ in self.shots:
            d.point((int(x), int(y)), fill=(255, 60, 60) if int(self.t * 10) % 2 else (255, 150, 60))
        for x, y, _, _, life, col in self.particles:
            d.point((int(x), int(y)), fill=scale(col, min(1.0, life * 2)))

        dead = self.end_at is not None
        if not dead and not (self.inv > 0 and int(self.t * 10) % 2):
            col = GOLD if self.play_t < self.double_until and int(self.t * 3) % 2 else SHIP
            y0 = int(round(self.ship_y))
            for dx, dy in SHIP_PX:
                d.point((1 + dx, y0 + dy), fill=col)

        if self.phase == "playing":
            pixelfont.draw_text(img, (6, 1), str(self.score), scale(GREY, 0.7))
            for i in range(max(0, self.lives)):
                d.point((6 + i * 3, 8), fill=scale(SHIP, 0.7))
            if self.play_t < self.banner_until:
                centered(img, 13, "WAVE %d" % self.wave, WHITE)
