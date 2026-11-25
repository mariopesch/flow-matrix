"""Glow Trails: every player steers a line of light that leaves a trail. Hitting a
wall or any trail knocks you out of the round; the last one moving wins the round.
First to win 3 rounds wins. 1-4 players; with only one player the computer joins.
"""
import random

from PIL import Image

from .base import WHITE, Game, centered, scale
from .. import pixelfont

DIRS = {"right": (1, 0), "left": (-1, 0), "up": (0, -1), "down": (0, 1)}


class GlowTrails(Game):
    id = "trails"
    title = "Glow Trails"
    players = "1-4"
    max_players = 4
    controls = {"type": "stick"}
    ROUNDS = 3
    SPEED0, SPEED_MAX = 13.0, 24.0   # cells per second

    def reset(self):
        self.wins = [0] * self.max_players
        self.round_no = 0
        self.participants = []
        self._new_round()

    def name(self, i):
        return "P%d" % (i + 1) if self.slots[i] is not None else "CPU"

    def hud(self):
        return "  ".join("%s %d" % (self.name(i), self.wins[i]) for i in self.participants) + \
            " · first to %d" % self.ROUNDS

    def play_message(self, side):
        if side not in self.participants:
            return "You join in the next round"
        if side not in self.alive and not self.pause_until:
            return "Out! Wait for the next round"
        return "Drag or swipe to turn"

    # ------------------------------------------------------------ rounds
    def _starts(self, n):
        W, H = self.w, self.h
        if n <= 2:
            return [(6, H // 2, "right"), (W - 7, H // 2, "left")]
        return [(6, 7, "right"), (W - 7, H - 8, "left"), (6, H - 8, "right"), (W - 7, 7, "left")]

    def _new_round(self):
        self.round_no += 1
        humans = [i for i in range(self.max_players) if self.slots[i] is not None]
        parts = list(humans)
        for i in range(self.max_players):  # the computer fills up to two players
            if len(parts) >= 2:
                break
            if i not in parts:
                parts.append(i)
        self.participants = sorted(parts)
        self.grid = bytearray(self.w * self.h)
        starts = self._starts(len(self.participants))
        self.heads, self.queue = {}, {}
        for k, i in enumerate(self.participants):
            x, y, d = starts[k]
            self.heads[i] = [x, y, d]
            self.queue[i] = []
            self.grid[y * self.w + x] = i + 1
        self.alive = set(self.participants)
        self._redraw_trails()
        self.acc = 0.0
        self.round_t = 0.0
        self.pause_until = 0.0
        self.round_winner = None
        self.crashes = []

    # ------------------------------------------------------------ loop
    def update_play(self, dt):
        self.round_t += dt
        self.crashes = [(x, y, t - dt) for x, y, t in self.crashes if t - dt > 0]
        if self.pause_until:
            if self.round_t >= self.pause_until:
                best = max(self.wins)
                if best >= self.ROUNDS:
                    w = self.wins.index(best)
                    detail = "  ".join("%s %d" % (self.name(i), self.wins[i]) for i in self.participants)
                    self.finish("%s WINS" % self.name(w), self.COLORS[w], detail, winner=w)
                else:
                    self._new_round()
            return
        self._read_input()
        speed = min(self.SPEED_MAX, self.SPEED0 + self.round_t * 0.5)
        self.acc += dt * speed
        while self.acc >= 1 and not self.pause_until:
            self.acc -= 1
            self._step()

    def _read_input(self):
        for i in self.alive:
            if self.slots[i] is None:
                continue
            sx, sy = self.stick(i)
            if max(abs(sx), abs(sy)) < 0.4:
                continue
            d = ("right" if sx > 0 else "left") if abs(sx) > abs(sy) else ("down" if sy > 0 else "up")
            q = self.queue[i]
            last = q[-1] if q else self.heads[i][2]
            if d != last and len(q) < 2:
                q.append(d)

    def _free(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h and not self.grid[y * self.w + x]

    def _run(self, x, y, d, limit=14):
        dx, dy = DIRS[d]
        n = 0
        while n < limit and self._free(x + dx * (n + 1), y + dy * (n + 1)):
            n += 1
        return n

    def _bot_dir(self, i):
        x, y, d = self.heads[i]
        turns = {"right": ("up", "down"), "left": ("up", "down"), "up": ("left", "right"), "down": ("left", "right")}[d]
        options = [(self._run(x, y, d) + (2 if random.random() > 0.05 else -3), d)]
        options += [(self._run(x, y, t) + random.random(), t) for t in turns]
        return max(options)[1]

    def _step(self):
        moves = {}
        for i in self.alive:
            x, y, d = self.heads[i]
            if self.slots[i] is None:
                d = self._bot_dir(i)
            elif self.queue[i]:
                nd = self.queue[i].pop(0)
                if DIRS[nd] != tuple(-v for v in DIRS[d]):  # no instant U-turn
                    d = nd
            dx, dy = DIRS[d]
            moves[i] = (x + dx, y + dy, d)
        targets = {}
        for i, (x, y, _) in moves.items():
            targets.setdefault((x, y), []).append(i)
        dead = set()
        for i, (x, y, _) in moves.items():
            if not self._free(x, y) or len(targets[(x, y)]) > 1:
                dead.add(i)
        for i, (x, y, d) in moves.items():
            if i in dead:
                self.crashes.append((min(max(x, 0), self.w - 1), min(max(y, 0), self.h - 1), 0.6))
                self.event(i, "miss")
                continue
            self.heads[i] = [x, y, d]
            self.grid[y * self.w + x] = i + 1
            self.trails.putpixel((x, y), self._trail_color(i))
        self.alive -= dead
        if dead:
            self._redraw_trails()  # knocked-out trails fade
        if len(self.alive) <= 1 and dead:
            if self.alive:
                w = next(iter(self.alive))
                self.wins[w] += 1
                self.round_winner = w
                self.event(w, "point")
            self.pause_until = self.round_t + 1.8

    # ------------------------------------------------------------ drawing
    def _trail_color(self, i):
        return scale(self.COLORS[i], 0.55 if i in self.alive else 0.22)

    def _redraw_trails(self):
        """Full redraw of the trail image (new round, or someone was knocked out)."""
        self.trails = Image.new("RGB", (self.w, self.h))
        px = self.trails.load()
        colors = [self._trail_color(i) for i in range(self.max_players)]
        g, W = self.grid, self.w
        for idx, o in enumerate(g):
            if o:
                px[idx % W, idx // W] = colors[o - 1]

    def draw_game(self, img, d):
        W = self.w
        img.paste(self.trails)
        px = img.load()
        for i in self.alive:
            x, y, _ = self.heads[i]
            px[x, y] = tuple(min(255, c + 120) for c in self.COLORS[i])
        for x, y, t in self.crashes:
            r = int((0.6 - t) * 8)
            d.ellipse([x - r, y - r, x + r, y + r], outline=scale((255, 255, 255), t / 0.6))
        if self.phase == "lobby":  # show where joined players will start
            for k, (x, y, _) in enumerate(self._starts(max(2, len(self.humans())))):
                if k < self.max_players and self.slots[k] is not None:
                    d.rectangle([x - 1, y - 1, x + 1, y + 1], fill=self.COLORS[k])
        if self.phase == "playing" and self.pause_until:
            text = ("%s +1" % self.name(self.round_winner)) if self.round_winner is not None else "DRAW"
            col = self.COLORS[self.round_winner] if self.round_winner is not None else WHITE
            tw = pixelfont.text_width(text)
            d.rectangle([(W - tw) // 2 - 3, 10, (W + tw) // 2 + 2, 20], fill=(0, 0, 0))
            centered(img, 13, text, col)
