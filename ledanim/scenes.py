"""
Scenes are what the matrix shows. The driver calls  scene.start()  once and then
scene.next() -> (PIL RGB image, delay_seconds | None)  in a loop.
delay None means "hold this image until something changes".
"""
import time
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

from . import pixelfont
from . import weather as wx

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "DejaVuSans-Bold.ttf",
]
_font_cache = {}


def font(size):
    if size not in _font_cache:
        f = None
        for path in FONT_PATHS:
            try:
                f = ImageFont.truetype(path, size)
                break
            except OSError:
                pass
        if f is None:
            try:
                f = ImageFont.load_default(size=size)
            except TypeError:
                f = ImageFont.load_default()
        _font_cache[size] = f
    return _font_cache[size]


def fit_font(sample, max_w, max_h, start=40):
    for size in range(start, 5, -1):
        l, t, r, b = font(size).getbbox(sample)
        if r - l <= max_w and b - t <= max_h:
            return font(size)
    return font(6)


def draw_big(img, x, y, text, fnt, color, align="left", width=None):
    """Crisp (non anti-aliased) TrueType text with its top-left ink at (x, y)."""
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    l, t, r, b = fnt.getbbox(text)
    if align == "center" and width:
        x += (width - (r - l)) // 2
    d.text((x - l, y - t), text, font=fnt, fill=color)
    return x + (r - l)


def small_line(img, x0, y, width, text, color, t, speed=14):
    """Pixel-font line in [x0, x0+width); scrolls if it doesn't fit."""
    tw = pixelfont.text_width(text)
    if tw <= width:
        pixelfont.draw_text(img, (x0, y), text, color)
        return
    gap = 14
    off = int(t * speed) % (tw + gap)
    strip = Image.new("RGB", (width, pixelfont.HEIGHT))
    pixelfont.draw_text(strip, (-off, 0), text, color)
    pixelfont.draw_text(strip, (-off + tw + gap, 0), text, color)
    img.paste(strip, (x0, y))


class Scene:
    def start(self):
        pass

    def next(self):
        raise NotImplementedError


class BlankScene(Scene):
    def __init__(self, w, h):
        self.img = Image.new("RGB", (w, h))

    def next(self):
        return self.img, None


class LiveScene(Scene):
    def __init__(self, img):
        self.img = img

    def next(self):
        return self.img, None


class AnimationScene(Scene):
    def __init__(self, frames, loop=True):
        self.frames, self.loop = frames, loop

    def start(self):
        self.idx = 0

    def next(self):
        if self.idx >= len(self.frames):  # finished, not looping: hold last
            return self.frames[-1][0], None
        img, dur = self.frames[self.idx]
        self.idx += 1
        if self.idx >= len(self.frames) and self.loop:
            self.idx = 0
        return img, dur


class EffectScene(Scene):
    def __init__(self, effect_cls, w, h, speed=1.0, fps=30):
        self.cls, self.w, self.h = effect_cls, w, h
        self.speed, self.delay = float(speed), 1.0 / fps

    def start(self):
        self.effect = self.cls(self.w, self.h)
        self.last = time.monotonic()

    def next(self):
        now = time.monotonic()
        dt = min(0.1, now - self.last) * self.speed
        self.last = now
        return Image.fromarray(self.effect.step(dt), "RGB"), self.delay


class ClockScene(Scene):
    def __init__(self, w, h, color=(255, 140, 0)):
        self.w, self.h, self.color = w, h, tuple(color)
        self.big = fit_font("88:88:88", w - 2, int(h * 0.55))
        self.small = fit_font("Wed 28.09.2026", w - 2, int(h * 0.30), 20)

    def next(self):
        img = Image.new("RGB", (self.w, self.h))
        now = datetime.now()
        dim = tuple(int(c * 0.6) for c in self.color)
        lines = [(now.strftime("%H:%M:%S"), self.big, self.color),
                 (now.strftime("%a %d.%m.%Y"), self.small, dim)]
        heights = [f.getbbox(t)[3] - f.getbbox(t)[1] for t, f, _ in lines]
        y = (self.h - sum(heights) - 2) // 2
        for (text, fnt, col), hgt in zip(lines, heights):
            draw_big(img, 0, y, text, fnt, col, align="center", width=self.w)
            y += hgt + 2
        return img, (1.0 - time.time() % 1.0) + 0.005


class TestPatternScene(Scene):
    """Diagnose panel settings: every 32x32 panel gets a border, a big number
    and a color (1 red, 2 green, 3 blue). A white dot marks each top-left corner,
    and the top row shows R G B color bars."""
    COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255)]

    def __init__(self, w, h, panel=32):
        self.w, self.h, self.panel = w, h, panel

    def next(self):
        img = Image.new("RGB", (self.w, self.h))
        d = ImageDraw.Draw(img)
        p = self.panel
        num_font = fit_font("8", p - 10, p - 12)
        for i, x0 in enumerate(range(0, self.w, p)):
            for y0 in range(0, self.h, p):
                col = self.COLORS[i % len(self.COLORS)]
                d.rectangle([x0, y0, x0 + p - 1, y0 + p - 1], outline=(90, 90, 90))
                draw_big(img, x0, y0 + 9, str(i + 1), num_font, col, align="center", width=p)
                d.rectangle([x0 + 1, y0 + 1, x0 + 2, y0 + 2], fill=(255, 255, 255))  # top-left marker
        # color order check: three labelled bars on the first panel's top row
        for j, (label, col) in enumerate((("R", (255, 0, 0)), ("G", (0, 255, 0)), ("B", (0, 0, 255)))):
            x = 5 + j * 9
            pixelfont.draw_text(img, (x, 2), label, col)
            d.rectangle([x + 4, 2, x + 6, 6], fill=col)
        return img, None


class WeatherScene(Scene):
    """style 'weather': big temperature.  style 'dashboard': big clock + weather lines."""
    ROTATE = 4.0

    def __init__(self, service, w, h, style="weather", color=(255, 140, 0)):
        self.wx, self.service, self.w, self.h = wx, service, w, h
        self.style, self.color = style, tuple(color)
        self.rx = 34
        self.rw = w - self.rx
        self.big = fit_font("-88" if style == "weather" else "88:88", self.rw - 10, 15, 20)

    def start(self):
        self.t0 = time.monotonic()

    def _fmt(self, v, unit=""):
        return "--" if v is None else "%d%s" % (round(v), unit)

    def next(self):
        t = time.monotonic() - self.t0
        info = self.service.info()
        d = info["data"]
        img = Image.new("RGB", (self.w, self.h))
        kind, label = self.wx.condition(d["code"]) if d else ("cloudy", "")
        img.paste(self.wx.draw_icon(kind, t, d["is_day"] if d else True), (0, 0))

        name = (info["location"] or {}).get("name") or info["city"]
        white, grey = (230, 230, 230), (140, 150, 170)
        x0 = self.rx
        if d:
            tu, deg = d["temp_unit"], "°"
            tcol = self.wx.temp_color(d["temp"], tu)
            hl = "H%s L%s" % (self._fmt(d["max"], deg), self._fmt(d["min"], deg))
            tomorrow = ""
            if d.get("tomorrow_max") is not None:
                tomorrow = "TMRW %s %s" % (self._fmt(d["tomorrow_max"], deg),
                                           self.wx.condition(d.get("tomorrow_code"))[1])
            details = [label, hl, "FEELS " + self._fmt(d["feels"], deg),
                       "HUM %s%%" % self._fmt(d["humidity"]),
                       "WIND %s%s" % (self._fmt(d["wind"]), d["wind_unit"])] + ([tomorrow] if tomorrow else [])
        else:
            tu, tcol = "", grey
            details = [("ERR: " + info["error"]) if info["error"] else "LOADING..."]

        if self.style == "weather":
            temp = self._fmt(d["temp"]) if d else "--"
            end = draw_big(img, x0 + 1, 1, temp, self.big, tcol)
            pixelfont.draw_text(img, (end + 2, 1), "°" + tu, tcol)
            small_line(img, x0, 19, self.rw, name, white, t)
            line3 = details[int(t / self.ROTATE) % len(details)]
            small_line(img, x0, 26, self.rw, line3, grey, t)
        else:  # dashboard
            now = datetime.now()
            hhmm = now.strftime("%H:%M") if now.second % 2 == 0 else now.strftime("%H %M")
            draw_big(img, x0, 1, hhmm, self.big, self.color, align="center", width=self.rw)
            temp = (self._fmt(d["temp"], "°") + tu) if d else "--°"
            tx = pixelfont.draw_text(img, (x0, 19), temp, tcol)
            small_line(img, tx + 3, 19, max(1, self.w - tx - 3), name, white, t)
            lines = [now.strftime("%a %d.%m.")] + details
            small_line(img, x0, 26, self.rw, lines[int(t / self.ROTATE) % len(lines)], grey, t)
        return img, 1 / 15


class PlaylistScene(Scene):
    """items: list of (scene, seconds). Cycles forever."""

    def __init__(self, items):
        self.items = [(s, max(1.0, float(sec))) for s, sec in items]

    def start(self):
        self.idx = -1
        self._advance()

    def _advance(self):
        self.idx = (self.idx + 1) % len(self.items)
        self.scene, secs = self.items[self.idx]
        self.scene.start()
        self.until = time.monotonic() + secs

    def next(self):
        if time.monotonic() >= self.until:
            self._advance()
        img, delay = self.scene.next()
        remaining = max(0.01, self.until - time.monotonic())
        return img, remaining if delay is None else min(delay, remaining)
