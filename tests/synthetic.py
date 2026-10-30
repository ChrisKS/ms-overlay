"""Draws a fake MapleStory status bar with the game's own 5x7 glyphs, for testing the reader."""
import numpy as np

from maplereader import ocr

GREEN, WHITE = (153, 204, 51), (255, 255, 255)
GLYPH = {ch: key for ch, key in ocr.BUILTIN_GLYPHS.items()}
GLYPH["5"] = next(k for k, v in ocr.TENTATIVE_GLYPHS.items() if v == "5")


def text(a, x, y, s):
    """Draw string `s` with its top-left at (x, y); returns the x after it."""
    for ch in s:
        rows = GLYPH[ch].split("|")
        for dy, row in enumerate(rows):
            for dx, c in enumerate(row):
                if c == "#": a[y + dy, x + dx] = WHITE
        x += len(rows[0]) + 1
    return x


def status_bar(exp="1,234,567", pct="12.34%", size=(1200, 80), at=(300, 40)):
    """An RGB array with a status bar whose HP "[" is at `at`: HP, MP and EXP brackets, the EXP
    number and the percentage."""
    a = np.full((size[1], size[0], 3), 20, dtype=np.uint8)
    x, y = at
    def bar(rx):
        a[y:y + 8, x + rx] = GREEN                   # brackets are 8 px tall green columns
    for rx in (0, 60, 80, 140):                      # HP [ ], MP [ ]
        bar(rx)
    text(a, x + ocr.EXP_START + 3, y, exp)           # EXP number, right after the "EXP." label
    bar(400)                                         # EXP "[" ... "]" around the percentage
    end = text(a, x + 403, y, pct)
    bar(end - x + 2)
    return a
