"""
Common flow for all phone-controlled games:

  lobby -> (a player presses Start) -> countdown -> playing -> over -> lobby

A game subclasses Game and fills in the hooks (reset, update_play, draw_game, ...).
Players are kept in `slots` (one per side / color). An empty slot is None; games
with computer opponents treat None slots as the computer.
"""
import json
import os
import threading
import time

from PIL import Image, ImageDraw

from .. import pixelfont
from ..scenes import Scene, draw_big, fit_font, small_line

COLORS = [(0, 170, 255), (255, 110, 0), (60, 220, 90), (230, 60, 200)]
WHITE, GREY = (235, 235, 235), (120, 128, 145)

HIGHSCORE_FILE = None  # set by app.py; None = keep high scores in memory only
_hs_lock = threading.Lock()
_hs_memory = {}


def load_best(game_id):
    with _hs_lock:
        if HIGHSCORE_FILE:
            try:
                with open(HIGHSCORE_FILE) as fh:
                    _hs_memory.update(json.load(fh))
            except (OSError, ValueError):
                pass
        return int(_hs_memory.get(game_id, 0))


def save_best(game_id, score):
    with _hs_lock:
        _hs_memory[game_id] = int(score)
        if HIGHSCORE_FILE:
            try:
                with open(HIGHSCORE_FILE + ".tmp", "w") as fh:
                    json.dump(_hs_memory, fh)
                os.replace(HIGHSCORE_FILE + ".tmp", HIGHSCORE_FILE)
            except OSError as exc:
                print("games: could not save high score:", exc)


def hex_color(c):
    return "#%02x%02x%02x" % tuple(c)


def scale(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def ticker(img, x0, y, width, text, color, t):
    """Pixel-font line that scrolls if too long. Only the letters are drawn."""
    strip = Image.new("RGB", (width, pixelfont.HEIGHT))
    small_line(strip, 0, 0, width, text, color, t)
    img.paste(strip, (x0, y), strip.convert("L").point(lambda v: 255 if v else 0))


def centered(img, y, text, color, scale_=1):
    x = (img.width - pixelfont.text_width(text) * scale_) // 2
    pixelfont.draw_text(img, (x, y), text, color, scale=scale_)


class Game(Scene):
    id = ""
    title = ""
    players = "1"            # shown in the game list, e.g. "1" or "1-4"
    max_players = 1
    controls = {"type": "slider"}   # phone layout: slider | stick (+ "buttons": [...])
    FPS = 50
    OVER_SECONDS = 15
    COLORS = COLORS

    def __init__(self, hub, w, h, join_url=""):
        self.hub, self.w, self.h, self.join_url = hub, w, h, join_url
        self.count_font = fit_font("8", 24, h - 10, 40)

    # ------------------------------------------------------------ hooks
    def reset(self):
        """Set up a fresh match (also used for the lobby background)."""

    def idle(self, dt):
        """Called instead of update_play in lobby, countdown and over."""

    def update_play(self, dt):
        """Advance the match. Call self.finish(...) when it is over."""

    def draw_game(self, img, d):
        """Draw the field."""

    def hud(self):
        """Short status for the phones, e.g. 'Score 120 · Level 2'."""
        return ""

    def play_message(self, side):
        return ""

    def view_extra(self, side):
        return {}

    def name(self, i):
        """Label of slot i on the matrix."""
        return "P%d" % (i + 1) if self.slots[i] is not None else "CPU"

    # ------------------------------------------------------------ helpers
    def humans(self):
        return [pid for pid in self.slots if pid is not None]

    def pos(self, i):
        pid = self.slots[i]
        return self.hub.position(pid) if pid is not None else None

    def stick(self, i):
        pid = self.slots[i]
        return self.hub.stick(pid) if pid is not None else (0.0, 0.0)

    def held(self, i, button):
        pid = self.slots[i]
        return pid is not None and self.hub.held(pid, button)

    def pressed(self, i, button):
        """True once per button press (survives presses shorter than a frame)."""
        return button in self._presses.get(i, ())

    def event(self, i, name):
        """Tell slot i's phone that something happened (it vibrates)."""
        if 0 <= i < len(self.slots) and self.slots[i] is not None:
            self.hub.event(self.slots[i], name)

    def finish(self, headline, color, detail="", winner=None, score=None):
        new_best = False
        if score is not None and score > self.best:
            self.best = score
            save_best(self.id, score)
            new_best = score > 0
        self.result = {"headline": headline, "color": color, "detail": detail,
                       "winner": winner, "score": score, "new_best": new_best}
        self._set_phase("over")

    # ------------------------------------------------------------ flow
    def start(self):
        self.hub.publish({})
        self.last = time.monotonic()
        self.t = 0.0
        self.slots = [None] * self.max_players
        self._presses = {}
        self.best = load_best(self.id)
        self.result = None
        self._set_phase("lobby")
        self.reset()

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

    def next(self):
        now = time.monotonic()
        dt = min(0.05, now - self.last)
        self.last = now
        self.t += dt
        self.phase_t += dt
        self._assign_slots()
        self._presses = {}
        for pid, action in self.hub.take_actions():
            if pid not in self.slots:
                continue
            i = self.slots.index(pid)
            if action == "start":
                if self.phase == "lobby" or (self.phase == "over" and self.phase_t > 1.5):
                    self.result = None
                    self.reset()
                    self._set_phase("countdown")
            elif action.startswith("press:"):
                self._presses.setdefault(i, set()).add(action[6:])

        if self.phase != "lobby" and not self.humans():
            self.result = None
            self._set_phase("lobby")  # everybody left
            self.reset()
        if self.phase == "countdown" and self.phase_t >= 3:
            self._set_phase("playing")
        if self.phase == "playing":
            self.update_play(dt)
        else:
            self.idle(dt)
        if self.phase == "over" and self.phase_t >= self.OVER_SECONDS:
            self.result = None
            self._set_phase("lobby")
            self.reset()

        img = Image.new("RGB", (self.w, self.h))
        self.draw_game(img, ImageDraw.Draw(img))
        self._draw_overlay(img)
        self._publish()
        return img, 1.0 / self.FPS

    # ------------------------------------------------------------ matrix overlays
    def _dim(self, img, f):
        img.paste(img.point(lambda v: int(v * f)))

    def _draw_overlay(self, img):
        if self.phase == "lobby":
            self._dim(img, 0.22)
            self._draw_lobby(img)
        elif self.phase == "countdown":
            self._dim(img, 0.5)
            n = str(3 - int(self.phase_t))
            draw_big(img, 0, (self.h - 20) // 2, n, self.count_font, WHITE, align="center", width=self.w)
        elif self.phase == "over" and self.result:
            self._dim(img, 0.25)
            r = self.result
            centered(img, 5, r["headline"], r["color"], 2)
            detail = r["detail"] + (" - NEW BEST!" if r["new_best"] else "")
            if pixelfont.text_width(detail) <= self.w - 4:
                centered(img, 22, detail, WHITE)
            else:
                ticker(img, 2, 22, self.w - 4, detail, WHITE, self.phase_t)

    def _draw_lobby(self, img):
        centered(img, 2, self.title, WHITE)
        if self.max_players == 1:
            line = ("BEST %d" % self.best) if self.best else "1 PLAYER"
            centered(img, 13, line, GREY)
        elif self.max_players == 2:
            for i in (0, 1):
                joined = self.slots[i] is not None
                text = "P%d %s" % (i + 1, "READY" if joined else "OPEN")
                col = self.COLORS[i] if joined else GREY
                x = 6 if i == 0 else self.w - 6 - pixelfont.text_width(text)
                pixelfont.draw_text(img, (x, 13), text, col)
        else:
            labels = ["P%d" % (i + 1) for i in range(self.max_players)]
            x = (self.w - pixelfont.text_width("  ".join(labels))) // 2
            for i, label in enumerate(labels):
                col = self.COLORS[i] if self.slots[i] is not None else GREY
                x = pixelfont.draw_text(img, (x, 13), label, col) + pixelfont.text_width("  ") + 1
        if self.humans():
            hint = "PRESS START ON YOUR PHONE"
            if None in self.slots:
                hint += " - MORE PLAYERS: OPEN %s" % self.join_url
        else:
            hint = "TO PLAY OPEN %s ON YOUR PHONE" % self.join_url
        ticker(img, 5, self.h - 6, self.w - 10, hint, GREY, self.t)

    # ------------------------------------------------------------ phones
    def _message(self, side):
        if side is None:
            return ("Someone else is playing. You get the next turn." if self.max_players == 1
                    else "All spots are taken. You get the next free one.")
        if self.phase == "lobby":
            if self.max_players == 1:
                return "Press Start to play" + (" · best %d" % self.best if self.best else "")
            n = len(self.humans())
            if n == 1:
                return "Press Start to play the computer, or wait for friends"
            return "%d players · press Start when everybody is ready" % n
        if self.phase == "countdown":
            return "Get ready…"
        if self.phase == "over" and self.result:
            r = self.result
            if r["winner"] is not None:
                msg = "🏆 You win!" if r["winner"] == side else "You lose."
            else:
                msg = "Game over"
            if r["score"] is not None:
                msg += " · %d points" % r["score"]
            if r["new_best"]:
                msg += " · new best!"
            return msg
        return self.play_message(side)

    def _publish(self):
        views = {}
        can_restart = self.phase == "lobby" or (self.phase == "over" and self.phase_t > 1.5)
        for pid in self.hub.roster():
            side = self.slots.index(pid) if pid in self.slots else None
            view = {"t": "state", "running": True, "game": self.id, "title": self.title,
                    "phase": self.phase, "side": side, "controls": self.controls,
                    "hud": self.hud() if self.phase != "lobby" else "",
                    "msg": self._message(side),
                    "can_start": side is not None and can_restart}
            if side is not None:
                view["player"] = side + 1
                view["color"] = hex_color(self.COLORS[side])
                view.update(self.view_extra(side))
            views[pid] = view
        self.hub.publish(views)
