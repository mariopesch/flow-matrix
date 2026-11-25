"""
Procedural animated effects. Each effect renders a (H, W, 3) uint8 numpy array.

    eff = EFFECTS["plasma"](96, 32)
    arr = eff.step(dt)          # dt = seconds since previous frame
"""
import math
import random

import numpy as np


def hsv(h, s, v):
    """Vectorized HSV -> RGB. h, s, v are arrays (or scalars) in 0..1. Returns uint8 (...,3)."""
    h = np.asarray(h, dtype=np.float32) % 1.0
    s = np.broadcast_to(np.asarray(s, dtype=np.float32), h.shape)
    v = np.broadcast_to(np.asarray(v, dtype=np.float32), h.shape)
    i = np.floor(h * 6).astype(np.int32) % 6
    f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return (np.stack([r, g, b], axis=-1).clip(0, 1) * 255).astype(np.uint8)


def palette(stops, n=256):
    """Build an (n,3) uint8 lookup table from [(pos 0..1, (r,g,b)), ...]."""
    xs = np.linspace(0, 1, n)
    pos = [p for p, _ in stops]
    out = np.zeros((n, 3), np.float32)
    for c in range(3):
        out[:, c] = np.interp(xs, pos, [col[c] for _, col in stops])
    return out.astype(np.uint8)


class Effect:
    title = "Effect"

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.t = 0.0
        self.y, self.x = np.mgrid[0:h, 0:w].astype(np.float32)
        self.setup()

    def setup(self):
        pass

    def step(self, dt):
        self.t += dt
        return self.render(dt)

    def render(self, dt):
        raise NotImplementedError


# ---------------------------------------------------------------- effects
class Plasma(Effect):
    title = "Plasma"

    def render(self, dt):
        t, x, y = self.t, self.x, self.y
        cx, cy = self.w / 2 + math.sin(t * 0.5) * self.w / 3, self.h / 2 + math.cos(t * 0.7) * self.h / 3
        v = (np.sin(x / 9 + t) + np.sin(y / 5 + t * 1.3) + np.sin((x + y) / 12 + t * 0.7)
             + np.sin(np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / 5 - t * 2))
        return hsv(v / 8 + t * 0.05, 1.0, 0.75 + 0.25 * np.sin(v * math.pi))


class Rainbow(Effect):
    title = "Rainbow"

    def render(self, dt):
        h = self.x / self.w * 0.8 + self.t * 0.25 + 0.08 * np.sin(self.y / 4 + self.t * 3)
        return hsv(h, 1.0, 1.0)


class Fire(Effect):
    title = "Fire"
    PAL = palette([(0, (0, 0, 0)), (0.25, (120, 0, 0)), (0.5, (230, 60, 0)),
                   (0.75, (255, 170, 0)), (1, (255, 255, 200))])

    def setup(self):
        self.heat = np.zeros((self.h + 2, self.w), np.float32)
        self.acc = 0.0

    def render(self, dt):
        self.acc += dt
        while self.acc >= 1 / 40:          # fixed 40 Hz simulation
            self.acc -= 1 / 40
            hb = self.heat
            hb[-2:] = np.random.uniform(0.55, 1.0, (2, self.w))
            below = hb[1:-1] + np.roll(hb[1:-1], 1, 1) + np.roll(hb[1:-1], -1, 1) + hb[2:]
            hb[:-2] = below / 4.0 - np.random.uniform(0.0, 0.095, (self.h, self.w))
            np.clip(hb, 0, 1, out=hb)
        return self.PAL[(self.heat[:self.h] * 255).astype(np.uint8)]


class MatrixRain(Effect):
    title = "Matrix rain"

    def setup(self):
        self.buf = np.zeros((self.h, self.w), np.float32)
        self.pos = np.random.uniform(-self.h, 0, self.w)
        self.speed = np.random.uniform(8, 25, self.w)

    def render(self, dt):
        self.buf *= 0.88 ** (dt * 30)
        self.pos += self.speed * dt
        done = self.pos > self.h + 10
        self.pos[done] = np.random.uniform(-20, 0, done.sum())
        self.speed[done] = np.random.uniform(8, 25, done.sum())
        cols = np.arange(self.w)
        ys = self.pos.astype(int)
        ok = (ys >= 0) & (ys < self.h)
        self.buf[ys[ok], cols[ok]] = 1.0
        b = self.buf
        img = np.zeros((self.h, self.w, 3), np.float32)
        img[..., 1] = b
        img[..., 0] = np.where(b > 0.97, 0.8, b * 0.15)   # whitish heads
        img[..., 2] = np.where(b > 0.97, 0.8, b * 0.25)
        flick = np.random.random((self.h, self.w)) < 0.02
        img[..., 1][flick & (b > 0.2)] *= 0.5
        return (img * 255).astype(np.uint8)


class Starfield(Effect):
    title = "Starfield"
    N = 140

    def setup(self):
        self.buf = np.zeros((self.h, self.w, 3), np.float32)
        self.sx = np.random.uniform(-1, 1, self.N)
        self.sy = np.random.uniform(-1, 1, self.N)
        self.sz = np.random.uniform(0.05, 1, self.N)
        self.hue = np.random.uniform(0, 1, self.N)

    def render(self, dt):
        self.buf *= 0.55 ** (dt * 30)
        self.sz -= dt * 0.45
        dead = self.sz <= 0.02
        n = dead.sum()
        self.sx[dead] = np.random.uniform(-1, 1, n)
        self.sy[dead] = np.random.uniform(-1, 1, n)
        self.sz[dead] = 1.0
        px = (self.sx / self.sz * self.w / 2 + self.w / 2).astype(int)
        py = (self.sy / self.sz * self.h / 2 + self.h / 2).astype(int)
        on = (px >= 0) & (px < self.w) & (py >= 0) & (py < self.h)
        bright = np.clip(1.2 - self.sz, 0, 1)[on]
        col = hsv(self.hue[on], 0.35, bright).astype(np.float32) / 255
        self.buf[py[on], px[on]] = np.maximum(self.buf[py[on], px[on]], col)
        self.sz[~on] = 0.0  # respawn next frame
        return (self.buf.clip(0, 1) * 255).astype(np.uint8)


class Life(Effect):
    title = "Game of Life"

    def setup(self):
        self.seed()
        self.acc = 0.0

    def seed(self):
        self.grid = np.random.random((self.h, self.w)) < 0.3
        self.age = np.zeros((self.h, self.w), np.float32)
        self.history = []
        self.hue0 = random.random()

    def render(self, dt):
        self.acc += dt
        if self.acc >= 0.12:
            self.acc = 0.0
            g = self.grid.astype(np.uint8)
            n = sum(np.roll(np.roll(g, dy, 0), dx, 1)
                    for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
            new = (n == 3) | (self.grid & (n == 2))
            self.age = np.where(new, self.age + 1, 0)
            self.grid = new
            key = hash(new.tobytes())
            if key in self.history or new.sum() < 12:
                self.seed()
            self.history = (self.history + [key])[-24:]
        h = self.hue0 + np.minimum(self.age, 30) / 60
        return hsv(h, 0.9, np.where(self.grid, 1.0, 0.0))


class Fireworks(Effect):
    title = "Fireworks"
    G = 18.0

    def setup(self):
        self.buf = np.zeros((self.h, self.w, 3), np.float32)
        self.p = np.zeros((0, 8), np.float32)  # x y vx vy life r g b
        self.rockets = []
        self.next_launch = 0.0

    def render(self, dt):
        self.buf *= 0.80 ** (dt * 30)
        self.next_launch -= dt
        if self.next_launch <= 0:
            self.next_launch = random.uniform(0.4, 1.4)
            self.rockets.append([random.uniform(10, self.w - 10), self.h, random.uniform(-5, 5),
                                 random.uniform(-40, -30), random.uniform(3, self.h * 0.45)])
        alive = []
        for r in self.rockets:
            r[0] += r[2] * dt
            r[1] += r[3] * dt
            r[3] += self.G * dt
            if r[1] <= r[4] or r[3] >= 0:
                self.explode(r[0], r[1])
            else:
                alive.append(r)
                x, y = int(r[0]), int(r[1])
                if 0 <= x < self.w and 0 <= y < self.h:
                    self.buf[y, x] = (1, 0.8, 0.5)
        self.rockets = alive
        p = self.p
        if len(p):
            p[:, 0] += p[:, 2] * dt
            p[:, 1] += p[:, 3] * dt
            p[:, 3] += self.G * 0.5 * dt
            p[:, 2:4] *= 0.98 ** (dt * 30)
            p[:, 4] -= dt
            p = p[p[:, 4] > 0]
            xs, ys = p[:, 0].astype(int), p[:, 1].astype(int)
            on = (xs >= 0) & (xs < self.w) & (ys >= 0) & (ys < self.h)
            fade = np.clip(p[on, 4:5], 0, 1)
            self.buf[ys[on], xs[on]] = np.maximum(self.buf[ys[on], xs[on]], p[on, 5:8] * fade)
            self.p = p
        return (self.buf.clip(0, 1) * 255).astype(np.uint8)

    def explode(self, x, y):
        n = random.randint(30, 60)
        ang = np.random.uniform(0, 2 * math.pi, n)
        spd = np.random.uniform(5, 18, n)
        rgb = hsv(np.array([random.random()]), 0.8, 1.0)[0].astype(np.float32) / 255
        new = np.zeros((n, 8), np.float32)
        new[:, 0], new[:, 1] = x, y
        new[:, 2], new[:, 3] = np.cos(ang) * spd, np.sin(ang) * spd
        new[:, 4] = np.random.uniform(0.8, 1.6, n)
        new[:, 5:8] = rgb
        self.p = np.vstack([self.p, new])


class LavaLamp(Effect):
    title = "Lava lamp"
    PAL = palette([(0, (10, 0, 30)), (0.45, (60, 0, 80)), (0.55, (255, 40, 80)),
                   (0.8, (255, 150, 0)), (1, (255, 240, 150))])

    def setup(self):
        self.balls = [(random.uniform(0.2, 0.9), random.uniform(0.2, 0.9), random.uniform(0, 6),
                       random.uniform(4, 7)) for _ in range(5)]

    def render(self, dt):
        t = self.t
        field = np.zeros((self.h, self.w), np.float32)
        for fx, fy, ph, r in self.balls:
            bx = self.w / 2 + math.sin(t * fx + ph) * self.w * 0.42
            by = self.h / 2 + math.sin(t * fy * 1.3 + ph * 2) * self.h * 0.45
            field += r * r / ((self.x - bx) ** 2 + ((self.y - by) * 1.2) ** 2 + 1)
        v = np.clip(field / 2.0, 0, 1)
        return self.PAL[(v * 255).astype(np.uint8)]


class Snow(Effect):
    title = "Snowfall"
    N = 90

    def setup(self):
        self.fx = np.random.uniform(0, self.w, self.N)
        self.fy = np.random.uniform(-self.h, self.h, self.N)
        self.fz = np.random.uniform(0.3, 1.0, self.N)       # depth: speed & brightness
        self.pile = np.zeros(self.w, np.float32)

    def render(self, dt):
        self.fy += (4 + 10 * self.fz) * dt
        self.fx += (np.sin(self.t * 0.8 + self.fz * 10) * 3 + 2) * dt * self.fz
        self.fx %= self.w
        xs = self.fx.astype(int)
        landed = self.fy >= self.h - 1 - self.pile[xs]
        for x in xs[landed]:
            self.pile[x] += 0.35
        self.pile = np.convolve(self.pile, [0.2, 0.6, 0.2], "same").astype(np.float32)
        if self.pile.mean() > 7:
            self.pile *= 0.6
        n = landed.sum()
        self.fy[landed] = np.random.uniform(-6, 0, n)
        self.fx[landed] = np.random.uniform(0, self.w, n)
        img = np.zeros((self.h, self.w, 3), np.float32)
        img[..., 2] = 0.08 + 0.12 * (self.y / self.h)  # night-blue sky
        ground = self.y >= self.h - self.pile[None, :]
        img[ground] = (0.75, 0.8, 0.9)
        ys = self.fy.astype(int)
        on = (ys >= 0) & (ys < self.h)
        b = self.fz[on][:, None]
        img[ys[on], xs[on]] = np.maximum(img[ys[on], xs[on]], b)
        return (img.clip(0, 1) * 255).astype(np.uint8)


class Spectrum(Effect):
    title = "Equalizer"

    def setup(self):
        self.n = self.w // 4
        self.level = np.zeros(self.n, np.float32)
        self.peak = np.zeros(self.n, np.float32)
        self.phase = np.random.uniform(0, 6, self.n)
        self.col = np.zeros((self.h, self.w, 3), np.uint8)
        grad = hsv(0.33 - (1 - np.arange(self.h) / self.h) * 0.33, 1.0, 1.0)  # green→red
        self.grad = grad

    def render(self, dt):
        t = self.t
        beat = max(0.0, math.sin(t * 2 * math.pi * 2.0)) ** 8          # 120 bpm
        base = 0.35 + 0.25 * np.sin(t * 1.7 + self.phase) + 0.15 * np.sin(t * 4.3 + self.phase * 2)
        bass = np.exp(-np.arange(self.n) / 6) * beat * 0.6
        target = np.clip(base + bass + np.random.uniform(-0.1, 0.1, self.n), 0.02, 1)
        self.level += (target - self.level) * min(1, dt * 15)
        self.peak = np.maximum(self.peak - dt * 0.6, self.level)
        img = np.zeros((self.h, self.w, 3), np.uint8)
        heights = (self.level * self.h).astype(int)
        for i in range(self.n):
            x = i * 4
            hgt = heights[i]
            if hgt:
                img[self.h - hgt:, x:x + 3] = self.grad[self.h - hgt:, None, :]
            py = self.h - 1 - int(self.peak[i] * (self.h - 1))
            img[py, x:x + 3] = (255, 255, 255)
        return img


class Ripples(Effect):
    title = "Ripples"

    def setup(self):
        self.drops = []
        self.next = 0.0

    def render(self, dt):
        self.next -= dt
        if self.next <= 0:
            self.next = random.uniform(0.3, 0.9)
            self.drops.append((random.uniform(0, self.w), random.uniform(0, self.h), self.t, random.random()))
        self.drops = [d for d in self.drops if self.t - d[2] < 3.0]
        img = np.zeros((self.h, self.w, 3), np.float32)
        for dx, dy, t0, hue in self.drops:
            age = self.t - t0
            r = age * 22
            d = np.sqrt((self.x - dx) ** 2 + (self.y - dy) ** 2)
            ring = np.exp(-((d - r) ** 2) / 3.0) * (1 - age / 3.0)
            img += hsv(np.full_like(d, 0.5 + hue * 0.2), 0.7, 1.0).astype(np.float32) / 255 * ring[..., None]
        img[..., 2] += 0.05
        return (img.clip(0, 1) * 255).astype(np.uint8)


class Tunnel(Effect):
    title = "Tunnel"

    def setup(self):
        dx, dy = self.x - self.w / 2 + 0.5, (self.y - self.h / 2 + 0.5) * 1.6
        self.r = np.sqrt(dx * dx + dy * dy) + 0.5
        self.a = np.arctan2(dy, dx) / math.pi
        self.depth = 40.0 / self.r

    def render(self, dt):
        t = self.t
        stripes = np.sin(self.depth * 2 - t * 6) * np.sin(self.a * math.pi * 6 + t * 1.5)
        v = (0.5 + 0.5 * stripes) * np.clip(self.r / 12, 0, 1)
        return hsv(self.depth * 0.04 + t * 0.1, 0.85, v)


class Bounce(Effect):
    title = "Bouncing balls"

    def setup(self):
        self.buf = np.zeros((self.h, self.w, 3), np.float32)
        n = 6
        self.p = np.column_stack([np.random.uniform(2, self.w - 2, n), np.random.uniform(2, self.h - 2, n)])
        ang = np.random.uniform(0, 2 * math.pi, n)
        self.v = np.column_stack([np.cos(ang), np.sin(ang)]) * np.random.uniform(15, 35, (n, 1))
        self.col = hsv(np.linspace(0, 1, n, endpoint=False), 0.9, 1.0).astype(np.float32) / 255

    def render(self, dt):
        self.buf *= 0.7 ** (dt * 30)
        self.p += self.v * dt
        for k, lim in ((0, self.w - 1), (1, self.h - 1)):
            low, high = self.p[:, k] < 0, self.p[:, k] > lim
            self.v[low | high, k] *= -1
            self.p[:, k] = np.clip(self.p[:, k], 0, lim)
        for (x, y), c in zip(self.p, self.col):
            d2 = (self.x - x) ** 2 + (self.y - y) ** 2
            self.buf = np.maximum(self.buf, c * np.clip(1.6 - d2 / 2.5, 0, 1)[..., None])
        return (self.buf.clip(0, 1) * 255).astype(np.uint8)


EFFECTS = {
    "plasma": Plasma, "fire": Fire, "matrix": MatrixRain, "starfield": Starfield,
    "fireworks": Fireworks, "lava": LavaLamp, "snow": Snow, "equalizer": Spectrum,
    "ripples": Ripples, "tunnel": Tunnel, "life": Life, "rainbow": Rainbow, "bounce": Bounce,
}
