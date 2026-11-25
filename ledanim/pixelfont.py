"""Tiny 3x5 pixel font - crisp, readable small text on LED panels."""
import unicodedata

_G = {
    "0": "### #.# #.# #.# ###", "1": ".#. ##. .#. .#. ###", "2": "### ..# ### #.. ###",
    "3": "### ..# .## ..# ###", "4": "#.# #.# ### ..# ..#", "5": "### #.. ### ..# ###",
    "6": "### #.. ### #.# ###", "7": "### ..# ..# .#. .#.", "8": "### #.# ### #.# ###",
    "9": "### #.# ### ..# ###",
    "A": ".#. #.# ### #.# #.#", "B": "##. #.# ##. #.# ##.", "C": ".## #.. #.. #.. .##",
    "D": "##. #.# #.# #.# ##.", "E": "### #.. ##. #.. ###", "F": "### #.. ##. #.. #..",
    "G": ".## #.. #.# #.# .##", "H": "#.# #.# ### #.# #.#", "I": "### .#. .#. .#. ###",
    "J": "..# ..# ..# #.# .#.", "K": "#.# #.# ##. #.# #.#", "L": "#.. #.. #.. #.. ###",
    "M": "#.# ### ### #.# #.#", "N": "##. #.# #.# #.# #.#", "O": ".#. #.# #.# #.# .#.",
    "P": "##. #.# ##. #.. #..", "Q": ".#. #.# #.# ##. .##", "R": "##. #.# ##. #.# #.#",
    "S": ".## #.. .#. ..# ##.", "T": "### .#. .#. .#. .#.", "U": "#.# #.# #.# #.# ###",
    "V": "#.# #.# #.# #.# .#.", "W": "#.# #.# ### ### #.#", "X": "#.# #.# .#. #.# #.#",
    "Y": "#.# #.# .#. .#. .#.", "Z": "### ..# .#. #.. ###",
    " ": "... ... ... ... ...", "-": "... ... ### ... ...", ".": "... ... ... ... .#.",
    ",": "... ... ... .#. #..", ":": "... .#. ... .#. ...", "%": "#.. ..# .#. #.. ..#",
    "/": "..# ..# .#. #.. #..", "!": ".#. .#. .#. ... .#.", "?": "##. ..# .#. ... .#.",
    "+": "... .#. ### .#. ...", "(": ".#. #.. #.. #.. .#.", ")": ".#. ..# ..# ..# .#.",
    "'": ".#. .#. ... ... ...", "°": "##. ##. ... ... ...", "_": "... ... ... ... ###",
    "<": "..# .#. #.. .#. ..#", ">": "#.. .#. ..# .#. #..", "=": "... ### ... ### ...",
    "#": "#.# ### #.# ### #.#", "&": ".#. #.# .#. #.# .##", "*": "#.# .#. #.# ... ...",
}
GLYPHS = {}
for ch, rows in _G.items():
    pts = [(x, y) for y, row in enumerate(rows.split()) for x, c in enumerate(row) if c == "#"]
    if not pts:  # space
        GLYPHS[ch] = ([], 2)
        continue
    mn = min(x for x, _ in pts)
    mx = max(x for x, _ in pts)
    GLYPHS[ch] = ([(x - mn, y) for x, y in pts], mx - mn + 1)

HEIGHT = 5
_SUBST = {"ß": "SS", "Ä": "AE", "Ö": "OE", "Ü": "UE", "ä": "AE", "ö": "OE", "ü": "UE"}


def normalize(text):
    out = []
    for ch in str(text):
        ch = _SUBST.get(ch, ch)
        ch = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode() or ch
        out.append(ch.upper())
    return "".join(out)


def text_width(text, spacing=1):
    text = normalize(text)
    if not text:
        return 0
    return sum(GLYPHS.get(c, GLYPHS["?"])[1] + spacing for c in text) - spacing


def draw_text(img, xy, text, color, scale=1, spacing=1):
    """Draw text onto a PIL image. Returns the x after the text."""
    x0, y0 = xy
    W, H = img.size
    px = img.load()
    x = x0
    for ch in normalize(text):
        if ch not in GLYPHS:
            ch = "?"
        pts, w = GLYPHS[ch]
        for gx, gy in pts:
            for sx in range(scale):
                for sy in range(scale):
                    X, Y = x + gx * scale + sx, y0 + gy * scale + sy
                    if 0 <= X < W and 0 <= Y < H:
                        px[X, Y] = color
        x += (w + spacing) * scale
    return x
