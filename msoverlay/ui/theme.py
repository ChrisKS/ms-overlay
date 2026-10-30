"""Colours, fonts and small drawing helpers shared by the overlay and the settings window."""
from ..paths import MAC, WIN

FONT = "Segoe UI" if WIN else "Helvetica Neue" if MAC else "DejaVu Sans"

KEY = "#010203"                                # colour keyed out to make windows see-through (Windows)
CLEAR = "systemTransparent" if MAC else KEY    # see-through window/canvas background
BG, BORDER, GRID = "#15161b", "#2c2f3a", "#2a2d36"
FG, DIM, DIM2 = "#eceef2", "#7d8190", "#474a56"
GOOD, BAD, WARN = "#5fd38d", "#ef6a6a", "#e0b34a"
# settings window controls
FIELD, TAB, BUTTON, BUTTON_HOVER, SLIDER = "#22242c", "#1c1d23", "#2a2c35", "#353844", "#9aa0b0"


def mix(c1, c2, t):
    """blend hex colour c1 into c2 by fraction t"""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]; b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(y + (x - y) * t) for x, y in zip(a, b))


def rrect(cv, x1, y1, x2, y2, r, **kw):
    """A rounded rectangle on a canvas."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def see_through(w):
    """Let the window's background colour (CLEAR) show what is behind it."""
    import tkinter as tk
    try:
        if MAC: w.attributes("-transparent", True)    # pairs with the "systemTransparent" colour
        else: w.attributes("-transparentcolor", KEY)  # Windows
    except tk.TclError:
        pass
