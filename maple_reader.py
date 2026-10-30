"""MapleReader - compact always-on-top overlay: reads Level / EXP from the MapleStory
status bar via OCR and shows EXP/hour over several time windows + a graph. Passive screen reading only: no game memory access,
no input injection.

  maple_reader.py                 GUI
  add --debug to save OCR crops to ./debug
"""
import argparse, csv, datetime, json, os, queue, re, sys, threading, time
from PIL import Image, ImageChops, ImageOps
import numpy as np
import pytesseract

MAC = sys.platform == "darwin"
FROZEN = getattr(sys, "frozen", False)

# --- Tesseract location: bundled "tesseract" folder next to the exe (Windows) or in the app's
# Resources folder (macOS), else a system install, else whatever is on PATH
BASE = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
for _c, _bundled in ((os.path.join(BASE, "tesseract", "tesseract.exe"), True),
                     (os.path.join(BASE, "tesseract", "tesseract"), True),
                     (os.path.join(BASE, "..", "Resources", "tesseract", "tesseract"), True),
                     (r"C:\Program Files\Tesseract-OCR\tesseract.exe", False),
                     ("/opt/homebrew/bin/tesseract", False),
                     ("/usr/local/bin/tesseract", False)):
    if os.path.isfile(_c):
        pytesseract.pytesseract.tesseract_cmd = _c
        if _bundled and MAC:    # a relocated macOS build doesn't know where its language data is
            os.environ.setdefault("TESSDATA_PREFIX", os.path.join(os.path.dirname(_c), "tessdata"))
        break

# --- Where settings and the log are kept: next to the exe, except in the macOS app, whose own
# folder must stay unchanged (writing into it would break its code signature)
DATA = os.path.expanduser("~/Library/Application Support/MapleReader") if MAC and FROZEN else BASE
os.makedirs(DATA, exist_ok=True)

DEBUG = False
# ------------------------------------------------------------------ OCR
# The status bar can be anywhere on screen (windowed client, any resolution): it is found by
# its green "[ ]" brackets (HP, MP, EXP). The EXP number and % are a 1-bit white 5x7 pixel
# font, read by exact glyph matching. Tesseract is only used for the level (orange box).
BUILTIN_GLYPHS = {"1": ".#|##|.#|.#|.#|.#|.#", "9": ".###.|#...#|#...#|.####|....#|#...#|.###.", "4": "...#.|..##.|.#.#.|#..#.|#####|...#.|...#.", "7": "#####|....#|....#|....#|...#.|..#..|..#..", "3": ".###.|#...#|....#|..##.|....#|#...#|.###.", "0": ".###.|#...#|#...#|#...#|#...#|#...#|.###.", ".": ".|.|.|.|.|.|#", "%": ".#....#|#.#..#.|.#..#..|...#...|..#..#.|.#..#.#|#....#.", "2": ".###.|#...#|....#|...#.|..#..|.#...|#####", "8": ".###.|#...#|#...#|.###.|#...#|#...#|.###.", ",": "..|..|..|..|..|.#|#.", "6": ".###.|#...#|#....|####.|#...#|#...#|.###."}
# The digit 5 has not been captured from a real screen yet. These are best guesses; if they are
# wrong, the unknown digit-shaped glyph is resolved by elimination (see _chars).
TENTATIVE_GLYPHS = {
    "#####|#....|####.|....#|....#|#...#|.###.": "5",
    "#####|#....|#....|####.|....#|#...#|.###.": "5",
}
DIGITS = "0123456789"
GLYPHS = dict(TENTATIVE_GLYPHS)
GLYPHS.update({v: k for k, v in BUILTIN_GLYPHS.items()})
_learned = set()                 # digits resolved by elimination during this run

EXP_START = 227                  # EXP digits start >= this many px right of the HP "[" (label ends at 226)
STRIP_X = (-20, 720)             # strip captured around the HP "[" bracket
LEVEL_REL = (-195, 1, -165, 15)  # level box relative to (HP "[" bracket x, glyph top row y)

def _green(a):
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    return (r >= 139) & (r <= 167) & (g >= 190) & (g <= 218) & (b >= 37) & (b <= 65)

def _runs(cols):
    """boolean sequence -> list of (start, end_exclusive) for consecutive True values"""
    out, i = [], 0
    while i < len(cols):
        if cols[i]:
            j = i
            while j < len(cols) and cols[j]: j += 1
            out.append((i, j)); i = j
        else:
            i += 1
    return out

def _key(mask):
    return "|".join("".join("#" if v else "." for v in row) for row in mask)

def find_bars(a):
    """a: HxWx3 RGB array. Finds rows with >= 6 green vertical bars (HP [ ], MP [ ], EXP [ ]).
    -> [(y_top, [x of each bar])], lowest on screen first."""
    ys, xs = np.nonzero(_green(a))
    if len(ys) < 12:
        return []
    o = np.lexsort((ys, xs)); xs, ys = xs[o], ys[o]
    brk = np.r_[True, (xs[1:] != xs[:-1]) | (ys[1:] != ys[:-1] + 1)]
    st = np.nonzero(brk)[0]; en = np.r_[st[1:], len(xs)]
    by = {}
    for s_, e_ in zip(st, en):
        if 7 <= e_ - s_ <= 9:
            by.setdefault(int(ys[s_]), []).append(int(xs[s_]))
    return sorted(((y, sorted(v)) for y, v in by.items() if len(v) >= 6), reverse=True)

def _digit_shaped(key):
    rows = key.split("|")
    return len(rows) == 7 and len(rows[0]) == 5 and key.count("#") >= 9

def _chars(keys):
    out = []
    for k in keys:
        ch = GLYPHS.get(k)
        if ch is None and _digit_shaped(k):
            real = set(BUILTIN_GLYPHS) | _learned
            missing = [d for d in DIGITS if d not in real]
            if len(missing) == 1:                 # only one digit is unaccounted for -> this is it
                ch = missing[0]; GLYPHS[k] = ch; _learned.add(ch)
        out.append(ch)
    return out

def read_strip(strip):
    """strip: RGB array whose first 7 rows are the glyph rows of the HP/MP/EXP line.
    -> dict(found, exp, pct, exp_text, pct_text, unknown)"""
    res = dict(found=False, exp=None, pct=None, exp_text="", pct_text="", unknown=False)
    if strip.shape[0] < 7:
        return res
    st = strip[:7]
    white = st.min(axis=2) >= 200
    bars = np.nonzero(_green(st).all(axis=0))[0]
    if len(bars) < 6:
        return res
    res["found"] = True
    xo, xc = int(bars[-2]), int(bars[-1])
    if not 8 <= xc - xo <= 120:
        return res
    # EXP number: left-aligned at a fixed offset from the HP "[" bracket, right after the "EXP." label
    first = -STRIP_X[0] + EXP_START
    sel = [(s_, e_) for s_, e_ in _runs(white.any(axis=0)[:xo]) if s_ >= first]
    ek = [_key(white[:, s_:e_]) for s_, e_ in sel]
    sub = white[:, xo + 1:xc]
    pk = [_key(sub[:, s_:e_]) for s_, e_ in _runs(sub.any(axis=0))]
    et, pt = _chars(ek), _chars(pk)
    res["exp_text"] = "".join(c or "?" for c in et)
    res["pct_text"] = "".join(c or "?" for c in pt)
    res["unknown"] = "?" in res["exp_text"] + res["pct_text"]
    digits = res["exp_text"].replace(",", "")
    if digits.isdigit():
        res["exp"] = int(digits)
    m = re.fullmatch(r"(\d+\.\d{2})%", res["pct_text"])
    if m:
        res["pct"] = float(m.group(1))
    return res

def _ocr(im, whitelist, name):
    # keep only near-white pixels (drops the orange level box)
    r, g, b = im.convert("RGB").split()
    mn = ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 0 if v > 170 else 255)
    p = ImageOps.expand(mn.resize((mn.width * 8, mn.height * 8), Image.LANCZOS), border=30, fill=255)
    if DEBUG:
        os.makedirs("debug", exist_ok=True)
        im.save(f"debug/{name}_raw.png"); p.save(f"debug/{name}_proc.png")
    return pytesseract.image_to_string(
        p, config=f"--psm 7 -c tessedit_char_whitelist={whitelist}").strip()

def read_level(img):
    """img: PIL image of the orange level box."""
    try:
        lvl = _ocr(img, "0123456789", "level")
    except Exception:
        return None
    return int(lvl) if lvl.isdigit() and 0 < int(lvl) < 1000 else None

NAME_REL = (-158, 11, -30, 25)   # character-name line (under the job) relative to HP "[" / glyph top row

def read_name(img):
    """OCR the character name from the status bar's name line. Majority vote over a few
    scalings, since Tesseract is occasionally off by a letter on this small font."""
    a = np.asarray(img.convert("RGB")).astype(int)
    ink = a.min(axis=2) >= 215                       # the name is near-white pixel text
    cols = np.where(ink.any(axis=0))[0]
    if len(cols) == 0:
        return None
    b = Image.fromarray(np.where(ink, 0, 255).astype("uint8"))
    b = b.crop((max(cols[0] - 2, 0), 0, cols[-1] + 3, b.height))
    votes = []
    for scale, flt in ((4, Image.BICUBIC), (3, Image.LANCZOS), (4, Image.LANCZOS), (3, Image.BICUBIC)):
        p = ImageOps.expand(b.resize((b.width * scale, b.height * scale), flt), border=24, fill=255)
        try:
            t = pytesseract.image_to_string(
                p, config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789").strip()
        except Exception:
            continue
        if t: votes.append(t.replace(" ", ""))
    if not votes:
        return None
    best = max(set(votes), key=lambda v: (votes.count(v), -votes.index(v)))
    return best

def read_image(img):
    """Read a whole screenshot (CLI / tests). -> result dict, or None if no status bar found."""
    a = np.asarray(img.convert("RGB"))
    bars = find_bars(a)
    if not bars:
        return None
    y, xs = bars[0]
    x = xs[0]
    res = read_strip(a[y:y + 7, max(x + STRIP_X[0], 0):x + STRIP_X[1]])
    L = LEVEL_REL
    res["level"] = read_level(img.crop((x + L[0], y + L[1], x + L[2], y + L[3])))
    N = NAME_REL
    res["name"] = read_name(img.crop((x + N[0], y + N[1], x + N[2], y + N[3])))
    return res

# ------------------------------------------------------------------ tracking
class Tracker:
    """Turns noisy readings into a session: cumulative EXP and % gained."""
    def __init__(self): self.reset()

    def reset(self):
        self.t0 = None; self.last = None; self.cand = None
        self.t_first = None         # time of the first EXP gain: the rate clock starts here
        self.points = []            # (t, cum_exp, cum_pct) on every change
        self.cum_exp = 0; self.cum_pct = 0.0
        self.req = {}               # level -> (best_pct, estimated EXP needed)
        self.approx = False         # True if a level-up had to be estimated

    def _learn_req(self, lvl, exp, pct):
        if pct >= 1.0 and pct > self.req.get(lvl, (0, 0))[0]:
            self.req[lvl] = (pct, round(exp * 100 / pct))

    def feed(self, t, lvl, exp, pct):
        """Returns True if an accepted change happened."""
        if None in (lvl, exp, pct):
            return False
        reading = (lvl, exp, pct)
        confirmed = (reading == self.cand)   # must be seen twice in a row (OCR glitches)
        self.cand = reading
        if not confirmed or reading == self.last:
            return False
        self._learn_req(lvl, exp, pct)
        if self.last is None:
            self.t0 = t; self.last = reading; self.points = [(t, 0, 0.0)]
            return True
        pl, pe, pp = self.last
        if lvl == pl and pp - pct > 30:   # looks like a level-up whose level we haven't re-read
            self.last = reading
            return True
        if lvl == pl:
            d = exp - pe
        elif lvl == pl + 1 and pl in self.req and pp > 50 and pct < 50:
            d = (self.req[pl][1] - pe) + exp
            self.approx = True
        else:   # unexpected jump (misread, de-level...): just re-baseline
            self.last = reading
            return True
        self.cum_exp += d
        self.cum_pct += ((lvl + pct / 100) - (pl + pp / 100)) * 100
        self.last = reading
        self.points.append((t, self.cum_exp, self.cum_pct))
        if self.t_first is None and (d != 0):
            self.t_first = t
        return True

    def value_at(self, t, idx):
        v = 0
        for p in self.points:
            if p[0] <= t: v = p[idx]
            else: break
        return v

    def rate(self, now, win):
        """(exp/hour, pct/hour, window_is_full) over the last `win` seconds.
        The clock starts at the first EXP gain (idle time before it is ignored),
        and a window longer than the session uses the session so far."""
        if self.t_first is None:
            return None
        if win <= 0: win = 10 ** 9                       # 0 minutes = the whole session
        start = max(self.t_first, now - win)
        span = now - start
        if span < 8:
            return None
        return ((self.cum_exp - self.value_at(start, 1)) / span * 3600,
                (self.cum_pct - self.value_at(start, 2)) / span * 3600,
                now - self.t_first >= win or win >= 10 ** 9)

    def rate_series(self, now, win, n=240):
        """EXP/hour through the session, for the graph: -> (times, rate over the trailing `win`
        seconds, session average so far), each as rate() would have reported it at that moment.
        The first minute (or the whole window, if shorter) is left out: a rate from a few kills
        swings wildly. None until there is something to plot."""
        first = None if self.t_first is None else self.t_first + min(win, 60)
        if first is None or now - first < 1:
            return None
        ts = np.array([p[0] for p in self.points]); cum = np.array([p[1] for p in self.points], dtype=float)
        val = lambda t: cum[np.maximum(np.searchsorted(ts, t, side="right") - 1, 0)]
        g = np.linspace(first, now, n)
        start = np.maximum(self.t_first, g - win)
        return (g, (val(g) - val(start)) / (g - start) * 3600,
                (val(g) - val(self.t_first)) / (g - self.t_first) * 3600)

    def gains(self, start):
        """number of EXP gains after time `start`"""
        n, prev = 0, 0
        for t, e, _ in self.points:
            if t > start and e > prev: n += 1
            prev = e
        return n

    def metric(self, kind, now, win, cur_pct=None):
        """(text, window_is_full) for one column, or None if there is not enough data yet."""
        r = self.rate(now, win)
        if r is None:
            return None
        eh, ph, full = r
        if win <= 0: win = 10 ** 9
        start = max(self.t_first, now - win)
        span = now - start
        if kind == "exp_h":    t = fmt_num(eh)
        elif kind == "exp_gain": t = "+" + fmt_num(eh * span / 3600)
        elif kind == "pct_h":  t = fmt_pct(ph, 1)
        elif kind == "pct_gain": t = "+" + fmt_pct(ph * span / 3600, 2)
        elif kind == "eta":
            if ph > 0 and cur_pct is not None:
                sec = (100 - cur_pct) / ph * 3600
                t = fmt_dur(sec) if sec < 100 * 3600 else "99h+"
            else: t = "\u2014"
        elif kind == "kills":  t = str(self.gains(start))
        elif kind == "avg":
            n = self.gains(start)
            t = fmt_num(eh * span / 3600 / n) if n else "\u2014"
        else: t = fmt_num(eh)
        return t, full

# ------------------------------------------------------------------ helpers
FONT = "Segoe UI" if sys.platform == "win32" else "Helvetica Neue" if MAC else "DejaVu Sans"
KEY, BG, BORDER = "#010203", "#15161b", "#2c2f3a"
CLEAR = "systemTransparent" if MAC else KEY   # see-through window/canvas background
FG, FG2, DIM, DIM2 = "#eceef2", "#a4a9b8", "#7d8190", "#474a56"
GOOD, BAD, WARN = "#5fd38d", "#ef6a6a", "#e0b34a"

SETTINGS_PATH = os.path.join(DATA, "maple_settings.json")
DEFAULTS = dict(
    name="Character", x=None, y=None,
    # general
    topmost=True, lock_position=False, show_name=True, reset_on_char=True, reads_per_sec=10,
    graph=False, mode="exp",
    # graph
    graph_style="step", graph_fill=True, graph_width=2, graph_opacity=1.0, fill_opacity=0.25,
    graph_rate_minutes=5, graph_avg=True,
    # rate columns
    rate_minutes=[5, 15, 30, 60], rate_on=[True, True, True, True],
    rate_kind=["exp_h", "exp_h", "exp_h", "exp_h"], rate_dim=True,
    # appearance
    accent="#5ec8f2", text_color="#ffffff", font_scale=1.0, text_shadow=True,
    bg_opacity=1.0, fg_opacity=1.0, number_format="da",
    # data
    log_csv=True,
)
# what a column can show: key -> (header label, description for the settings list)
KINDS = {
    "exp_h":    ("EXP/H",    "EXP per hour"),
    "exp_gain": ("EXP",      "EXP gained in the window"),
    "pct_h":    ("%/H",      "Level % per hour"),
    "pct_gain": ("% GAINED", "Level % gained in the window"),
    "eta":      ("LEVEL IN", "Time to next level at that pace"),
    "kills":    ("KILLS",    "Number of EXP gains (kills) in the window"),
    "avg":      ("AVG/KILL", "Average EXP per kill"),
}
ACCENTS = [("Sky", "#5ec8f2"), ("Mint", "#5fd38d"), ("Amber", "#e0b34a"), ("Rose", "#ef6a8a"),
           ("Violet", "#a78bfa"), ("Orange", "#f59e57"), ("Silver", "#c9ced8")]
NUMBER_FORMATS = {"da": "1.234.567  (Danish)", "en": "1,234,567  (English)",
                  "space": "1 234 567  (spaces)", "compact": "1.2M  (compact)"}
TEXT_COLORS = [("White", "#ffffff"), ("Soft", "#e3e6ee"), ("Yellow", "#ffe48a"), ("Cyan", "#b3f0ff"),
               ("Mint", "#bff7d6"), ("Pink", "#ffc7dc")]
FONT_SCALES = [("Small", 0.9), ("Normal", 1.0), ("Large", 1.15), ("Extra large", 1.3)]
GRAPH_STYLES = {"step": "Stepped (sharp)", "line": "Straight lines", "smooth": "Smooth curve"}
# what the graph plots: key -> (button label, settings label), in the order the buttons appear
GRAPH_MODES = {"exp": ("EXP", "EXP gained"), "pct": ("%", "% gained"), "rate": ("EXP/H", "EXP per hour")}
NUM_STYLE = "da"

def _num(v, lo, hi, default):
    try: v = float(v)
    except (TypeError, ValueError): return default
    return min(max(v, lo), hi)

def sanitize(s):
    d = DEFAULTS
    rm = s.get("rate_minutes"); ro = s.get("rate_on")
    s["rate_minutes"] = [int(_num(x, 0, 720, d["rate_minutes"][i])) for i, x in enumerate((rm if isinstance(rm, list) and len(rm) == 4 else d["rate_minutes"]))]
    s["rate_on"] = [bool(x) for x in (ro if isinstance(ro, list) and len(ro) == 4 else d["rate_on"])]
    if not any(s["rate_on"]): s["rate_on"][0] = True
    rk = s.get("rate_kind")
    s["rate_kind"] = [k if k in KINDS else "exp_h" for k in (rk if isinstance(rk, list) and len(rk) == 4 else d["rate_kind"])]
    s["bg_opacity"] = _num(s.get("bg_opacity"), 0.0, 1.0, 1.0)
    s["fg_opacity"] = _num(s.get("fg_opacity"), 0.2, 1.0, 1.0)
    s["reads_per_sec"] = int(_num(s.get("reads_per_sec"), 2, 20, 10))
    if s.get("number_format") not in NUMBER_FORMATS: s["number_format"] = "da"
    if not (isinstance(s.get("accent"), str) and re.fullmatch(r"#[0-9a-fA-F]{6}", s["accent"])): s["accent"] = d["accent"]
    if s.get("mode") not in GRAPH_MODES: s["mode"] = "exp"
    s["graph_rate_minutes"] = int(_num(s.get("graph_rate_minutes"), 1, 60, 5))
    if s.get("graph_style") not in GRAPH_STYLES: s["graph_style"] = "step"
    s["graph_opacity"] = _num(s.get("graph_opacity"), 0.0, 1.0, 1.0)
    s["fill_opacity"] = _num(s.get("fill_opacity"), 0.0, 1.0, 0.25)
    s["graph_width"] = int(_num(s.get("graph_width"), 1, 4, 2))
    if not (isinstance(s.get("text_color"), str) and re.fullmatch(r"#[0-9a-fA-F]{6}", s["text_color"])): s["text_color"] = "#ffffff"
    fs = _num(s.get("font_scale"), 0.8, 1.5, 1.0); s["font_scale"] = min((v for _, v in FONT_SCALES), key=lambda v: abs(v - fs))
    for k in ("topmost", "lock_position", "show_name", "reset_on_char", "graph", "log_csv", "graph_fill", "text_shadow", "rate_dim", "graph_avg"):
        s[k] = bool(s.get(k, d[k]))
    return s

def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        if "opacity" in raw:                       # older versions had one opacity for everything
            raw.setdefault("bg_opacity", raw["opacity"]); raw.setdefault("fg_opacity", raw["opacity"])
            raw.setdefault("graph_opacity", raw["opacity"])
        if "fill_strength" in raw:                 # renamed: "fill strength" -> "fill opacity"
            raw.setdefault("fill_opacity", min(1.0, raw["fill_strength"] * 1.5))
        s.update({k: v for k, v in raw.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return sanitize(s)

def mix(c1, c2, t):
    """blend hex colour c1 into c2 by fraction t"""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]; b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(y + (x - y) * t) for x, y in zip(a, b))

def fmt_pct(v, nd=2):
    t = f"{v:.{nd}f}"
    return (t.replace(".", ",") if NUM_STYLE == "da" else t) + "%"

def fmt_signed(n, approx=""):
    return ("+" if n >= 0 else "\u2212") + approx + fmt_num(abs(n))

def fmt_dur(sec):
    sec = int(sec); h, r = divmod(sec, 3600); m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def fmt_num(n):
    """Number formatting follows the 'number format' setting (NUM_STYLE)."""
    n = int(round(n)); neg, a = n < 0, abs(n)
    dec = "," if NUM_STYLE == "da" else "."
    if NUM_STYLE == "compact" or a >= 10_000_000:
        if a >= 1_000_000: t = f"{a / 1e6:.2f}".rstrip("0").rstrip(".") + "M"
        elif a >= 10_000 and NUM_STYLE == "compact": t = f"{a / 1e3:.1f}".rstrip("0").rstrip(".") + "k"
        else: t = str(a)
        t = t.replace(".", dec)
    else:
        t = f"{a:,}".replace(",", {"da": ".", "en": ",", "space": "\u2009"}.get(NUM_STYLE, "."))
    return ("-" if neg else "") + t

def fmt_short(n):
    """Compact number for tight spots like axis labels: 850k, 1,25M (decimal mark per number format)."""
    a = abs(n)
    if a >= 1e6: t = f"{a / 1e6:.2f}".rstrip("0").rstrip(".") + "M"
    elif a >= 1e4: t = f"{a / 1e3:.0f}k"
    else: t = str(int(round(a)))
    return ("-" if n < 0 else "") + (t.replace(".", ",") if NUM_STYLE == "da" else t)

def blur(y):
    """Light Gaussian blur for the smooth graph style; keeps both ends where they were."""
    k = np.exp(-0.5 * (np.arange(-6, 7) / 2.2) ** 2); k /= k.sum()
    sm = np.convolve(np.pad(np.asarray(y, dtype=float), 6, mode="edge"), k, mode="valid")
    sm[0], sm[-1] = y[0], y[-1]
    return sm

def nice_ticks(lo, hi, n=4):
    raw = (hi - lo) / n
    mag = 10 ** int(np.floor(np.log10(raw)))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    first = np.ceil(lo / step) * step
    return [first + i * step for i in range(int((hi - first) / step) + 1)]

def rrect(cv, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)

# ------------------------------------------------------------------ UI
class App:
    W, H, GH = 580, 128, 230     # width, collapsed height, extra height for the graph

    def __init__(self, demo=False):
        import tkinter as tk
        self.tk, self.demo = tk, demo
        self.S = load_settings()
        self.tracker = Tracker()
        self.q = queue.Queue()
        self.paused, self.fails, self.status = False, 0, "wait"
        self.cur = None             # last good (level, exp, pct)
        self.hint = ""
        self.loc = None             # where the status bar is on screen (set by the reader thread)
        self.drag = None

        # Four stacked, borderless windows so each part can have its own opacity (Windows can only
        # fade a whole window): background (root) < fill < graph line < text/UI. Everything above the
        # background is drawn on a colour-keyed transparent canvas.
        r = self.root = tk.Tk()
        r.title("MapleReader")
        r.overrideredirect(True)
        r.configure(bg=CLEAR)
        self.see_through(r)                           # rounded corners
        def layer():
            w = tk.Toplevel(r)
            w.overrideredirect(True); w.configure(bg=CLEAR)
            self.see_through(w)
            try: w.transient(r)                       # an owned window stays above its owner
            except tk.TclError: pass
            return w
        self.fillw, self.linew, fg = layer(), layer(), layer()
        self.fg = fg                                  # the text/UI layer (top)
        self.layers = [r, self.fillw, self.linew, fg]
        self.sw = None
        self._fonts = {}
        self.name_seen = False
        self.acc = self.acc_fill = None
        self.c_fg = self.c_label = self.c_sub = self.c_faint = FG
        def canvas(w):
            c = tk.Canvas(w, bg=CLEAR, highlightthickness=0, width=self.W, height=self.H); c.pack(); return c
        self.bgcv, self.fillcv, self.linecv, self.cv = canvas(r), canvas(self.fillw), canvas(self.linew), canvas(fg)
        self.canvases = [self.bgcv, self.fillcv, self.linecv, self.cv]
        for w in self.layers:
            w.bind("<FocusIn>", lambda e: self.fix_stack())
            w.bind("<Map>", lambda e: self.fix_stack())
            w.bind("<Visibility>", lambda e: self.fix_stack())
        for c in self.canvases:
            c.bind("<ButtonPress-1>", self.on_press)
            c.bind("<B1-Motion>", self.on_drag)
            c.bind("<ButtonRelease-1>", self.on_release)
            for b in ("<Button-2>", "<Control-Button-1>") if MAC else ("<Button-3>",):   # right-click
                c.bind(b, self.on_menu)
        self.resize(initial=True)
        self.apply(save=False)

    def apply(self, save=True):
        """Push the current settings into the live window."""
        global NUM_STYLE
        self.S = sanitize(self.S)
        NUM_STYLE = self.S["number_format"]
        self.acc = self.S["accent"]; self.acc_fill = mix(self.acc, BG, 0.16)      # for the small EXP/% buttons
        tc = self.S["text_color"]                      # text colour + brightness steps derived from it
        self.c_fg, self.c_label, self.c_sub, self.c_faint = tc, mix(tc, BG, 0.80), mix(tc, BG, 0.62), mix(tc, BG, 0.38)
        alphas = (self.S["bg_opacity"], self.S["fill_opacity"], self.S["graph_opacity"], self.S["fg_opacity"])
        for w, alpha in zip(self.layers, alphas):
            w.attributes("-topmost", bool(self.S["topmost"]))
            try: w.attributes("-alpha", float(alpha))
            except self.tk.TclError: pass
        self.fix_stack()
        if save: self.save()
        self.redraw()

    # ---- window / settings
    def height(self): return self.H + (self.GH if self.S["graph"] else 0)

    def resize(self, initial=False):
        h = self.height()
        for c in self.canvases: c.config(height=h)
        if initial and self.S["x"] is not None:
            x, y = self.S["x"], self.S["y"]
        elif initial:
            x, y = (self.root.winfo_screenwidth() - self.W) // 2, 40
        else:
            x, y = self.root.winfo_x(), self.root.winfo_y()
        self.move(x, y, h)
        self.bgcv.delete("all")
        rrect(self.bgcv, 3, 3, self.W - 3, h - 3, 26, fill=BG, outline=BORDER, width=2)

    def fix_stack(self):
        """Keep the layers in order: background < fill < line < text. Windows can reorder topmost
        windows (e.g. when the settings window closes or another app grabs focus), which would hide
        the text under the background - so re-assert the order whenever it is wrong."""
        L = self.layers
        for lo, hi in zip(L, L[1:]):
            try:
                if int(self.root.tk.call("wm", "stackorder", str(lo), "isabove", str(hi))):
                    hi.lift(lo)
            except self.tk.TclError:
                try: hi.lift()
                except self.tk.TclError: pass

    def see_through(self, w):
        """Let the window's background colour show what is behind it."""
        try:
            if MAC: w.attributes("-transparent", True)    # pairs with the "systemTransparent" colour
            else: w.attributes("-transparentcolor", KEY)  # Windows
        except self.tk.TclError:
            pass

    def win32_own(self):
        """Make the text window an *owned* window of the background window (Windows only). Windows
        keeps owned windows above their owner no matter what gets activated or closed."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            u.GetAncestor.restype = ctypes.c_void_p; u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            setptr = getattr(u, "SetWindowLongPtrW", None) or u.SetWindowLongW
            setptr.restype = ctypes.c_void_p; setptr.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            h_root = u.GetAncestor(self.root.winfo_id(), 2)       # GA_ROOT
            for w in self.layers[1:]:
                setptr(u.GetAncestor(w.winfo_id(), 2), -8, h_root)   # GWLP_HWNDPARENT = owner
        except Exception:
            pass

    def move(self, x, y, h=None):
        h = h or self.height()
        for w in self.layers:
            w.geometry(f"{self.W}x{h}+{int(x)}+{int(y)}")

    def save(self):
        try:
            self.S["x"], self.S["y"] = self.root.winfo_x(), self.root.winfo_y()
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(self.S, f, indent=2)
        except (OSError, self.tk.TclError):
            pass

    def quit(self):
        self.save(); self.root.destroy()

    # ---- interaction
    def on_press(self, e):
        self.drag = None
        tags = e.widget.gettags("current")
        if "toggle" in tags: return self.toggle_graph()
        for k in GRAPH_MODES:
            if f"mode_{k}" in tags: self.S["mode"] = k; return self.redraw()
        self.fix_stack()
        if not self.S["lock_position"]:
            self.drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def on_drag(self, e):
        if self.drag and not self.S["lock_position"]:
            self.move(e.x_root - self.drag[0], e.y_root - self.drag[1])

    def on_release(self, e):
        moved = self.drag is not None
        self.drag = None
        if moved: self.save()

    def toggle_graph(self):
        self.S["graph"] = not self.S["graph"]; self.resize(); self.redraw(); self.save()

    def toggle_pause(self):
        self.paused = not self.paused; self.status = "paused" if self.paused else "wait"; self.redraw()

    def reset(self):
        self.tracker.reset(); self.redraw()

    def on_menu(self, e):
        tk = self.tk
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Resume" if self.paused else "Pause", command=self.toggle_pause)
        m.add_command(label="Reset session", command=self.reset)
        m.add_separator()
        m.add_command(label="Settings…", command=self.open_settings)
        m.add_separator()
        m.add_command(label="Quit", command=self.quit)
        m.tk_popup(e.x_root, e.y_root)

    def open_settings(self):
        tk = self.tk
        from tkinter import ttk
        if self.sw is not None and self.sw.winfo_exists():
            self.sw.deiconify(); self.sw.lift(); return
        S = self.S
        sw = self.sw = tk.Toplevel(self.root)
        sw.title("MapleReader \u2013 Settings"); sw.configure(bg=BG); sw.resizable(False, False)
        sw.attributes("-topmost", True)
        sw.geometry(f"+{self.root.winfo_x() + 30}+{self.root.winfo_y() + 40}")

        st = ttk.Style(sw); st.theme_use("clam")
        FIELD = "#22242c"
        st.configure(".", background=BG, foreground=FG, fieldbackground=FIELD, bordercolor=BORDER,
                     lightcolor=BG, darkcolor=BG, troughcolor=FIELD, font=(FONT, 10), focuscolor=BG)
        st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
        st.configure("TNotebook.Tab", background="#1c1d23", foreground=DIM, padding=(14, 7), borderwidth=0)
        st.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", FG)])
        st.configure("TCheckbutton", background=BG, foreground=FG, indicatorbackground=FIELD, indicatorforeground=FG)
        st.map("TCheckbutton", background=[("active", BG)], indicatorbackground=[("selected", self.acc)])
        st.configure("TRadiobutton", background=BG, foreground=FG, indicatorbackground=FIELD)
        st.map("TRadiobutton", background=[("active", BG)], indicatorbackground=[("selected", self.acc)])
        st.configure("TButton", background="#2a2c35", foreground=FG, padding=(12, 6), borderwidth=0)
        st.map("TButton", background=[("active", "#353844")])
        st.configure("TSpinbox", arrowsize=12, padding=3)
        st.configure("TCombobox", padding=4, arrowcolor=FG, background="#2a2c35")
        st.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)],
               selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", FG)],
               background=[("readonly", "#2a2c35"), ("active", "#353844")])
        sw.option_add("*TCombobox*Listbox.background", FIELD); sw.option_add("*TCombobox*Listbox.foreground", FG)
        sw.option_add("*TCombobox*Listbox.selectBackground", "#353844"); sw.option_add("*TCombobox*Listbox.selectForeground", FG)
        st.configure("Sec.TLabel", foreground=DIM, font=(FONT, 9))
        st.configure("Hint.TLabel", foreground=DIM, font=(FONT, 9))
        st.configure("Horizontal.TScale", background="#9aa0b0", troughcolor=FIELD, bordercolor=FIELD, lightcolor="#9aa0b0", darkcolor="#9aa0b0")

        nb = ttk.Notebook(sw); nb.pack(fill="both", expand=True, padx=14, pady=(14, 6))
        def page(title):
            f = ttk.Frame(nb, padding=(18, 16)); nb.add(f, text=title); return f
        def head(f, text, row):
            ttk.Label(f, text=text.upper(), style="Sec.TLabel").grid(row=row, column=0, columnspan=4, sticky="w", pady=(12 if row else 0, 4))
        def bvar(key, after=None):
            v = tk.BooleanVar(value=S[key])
            def cb(*_):
                S[key] = v.get(); self.apply()
                if after: after()
            v.trace_add("write", cb); return v
        def ivar(key, lo, hi):
            v = tk.IntVar(value=S[key])
            def cb(*_):
                try: x = int(v.get())
                except (tk.TclError, ValueError): return
                S[key] = min(max(x, lo), hi); self.apply()
            v.trace_add("write", cb); return v
        def slider(parent, row, label, key, lo, hi, fmt=lambda v: f"{v:.0f}%", scale=100.0):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
            v = tk.DoubleVar(value=S[key] * scale); t = tk.StringVar(value=fmt(S[key] * scale))
            def cb(*_):
                S[key] = v.get() / scale; t.set(fmt(v.get())); self.apply()
            ttk.Scale(parent, from_=lo, to=hi, variable=v, command=cb, length=190).grid(row=row, column=1, columnspan=2, sticky="w", padx=(10, 6))
            ttk.Label(parent, textvariable=t, width=5).grid(row=row, column=3, sticky="w")
        def swatches(parent, row, colors, key, after=None):
            fr = tk.Frame(parent, bg=BG); fr.grid(row=row, column=0, columnspan=4, sticky="w", pady=4)
            items = []
            def paint():
                for c, c_ in items:
                    c_.delete("all")
                    c_.create_oval(3, 3, 25, 25, fill=c, outline=FG if c.lower() == S[key].lower() else BG, width=2)
            def pick(c):
                S[key] = c; self.apply(); paint()
                if after: after(c)
            for name, c in colors:
                c_ = tk.Canvas(fr, width=28, height=28, bg=BG, highlightthickness=0, cursor="hand2")
                c_.pack(side="left", padx=2); c_.bind("<Button-1>", lambda e, c=c: pick(c)); items.append((c, c_))
            paint()
        def radios(parent, row, label, key, options, cols=4):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(6, 3))
            v = tk.StringVar(value=str(S[key]))
            def cb(*_):
                S[key] = type(DEFAULTS[key])(v.get()); self.apply()
            for i, (txt_, val) in enumerate(options):
                ttk.Radiobutton(parent, text=txt_, variable=v, value=str(val), command=cb).grid(row=row + 1 + i // cols, column=i % cols, sticky="w", padx=(0, 12), pady=2)

        # ---------- General
        g = page("General")
        head(g, "Window", 0)
        ttk.Checkbutton(g, text="Always on top", variable=bvar("topmost")).grid(row=1, column=0, sticky="w", pady=3, columnspan=4)
        ttk.Checkbutton(g, text="Lock position (disable dragging)", variable=bvar("lock_position")).grid(row=2, column=0, sticky="w", pady=3, columnspan=4)
        ttk.Checkbutton(g, text="Show character name", variable=bvar("show_name")).grid(row=3, column=0, sticky="w", pady=3, columnspan=4)
        head(g, "Session", 4)
        ttk.Checkbutton(g, text="Start a new session when the character changes", variable=bvar("reset_on_char")).grid(row=5, column=0, sticky="w", pady=3, columnspan=4)
        head(g, "Reading", 6)
        ttk.Label(g, text="Screen reads per second").grid(row=7, column=0, sticky="w", pady=3)
        ttk.Spinbox(g, from_=2, to=20, width=5, textvariable=ivar("reads_per_sec", 2, 20)).grid(row=7, column=1, sticky="w", padx=(10, 0))
        ttk.Label(g, text="Higher = EXP updates sooner, slightly more CPU.", style="Hint.TLabel").grid(row=8, column=0, columnspan=4, sticky="w")

        # ---------- Rates
        r = page("Rates")
        ttk.Label(r, text="Choose which columns are shown, what each one displays, and how many minutes it covers.",
                  style="Hint.TLabel", wraplength=400, justify="left").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))
        self.rate_vars = []
        for i in range(4):
            on = tk.BooleanVar(value=S["rate_on"][i]); mn = tk.IntVar(value=S["rate_minutes"][i])
            def cb(*_, i=i, on=on, mn=mn):
                S["rate_on"][i] = on.get()
                try: S["rate_minutes"][i] = min(max(int(mn.get()), 0), 720)
                except (tk.TclError, ValueError): return
                self.apply()
            kv = tk.StringVar(value=KINDS[S["rate_kind"][i]][1])
            def kcb(*_, i=i, kv=kv):
                for k, (_, desc) in KINDS.items():
                    if desc == kv.get(): S["rate_kind"][i] = k
                self.apply()
            kv.trace_add("write", kcb)
            on.trace_add("write", cb); mn.trace_add("write", cb); self.rate_vars += [on, mn, kv]
            ttk.Combobox(r, state="readonly", width=34, textvariable=kv,
                         values=[d for _, d in KINDS.values()]).grid(row=i + 1, column=3, padx=(14, 0))
            ttk.Checkbutton(r, text=f"Column {i + 1}", variable=on).grid(row=i + 1, column=0, sticky="w", pady=5)
            ttk.Spinbox(r, from_=0, to=720, width=6, textvariable=mn).grid(row=i + 1, column=1, padx=(14, 6))
            ttk.Label(r, text="minutes").grid(row=i + 1, column=2, sticky="w")
        ttk.Checkbutton(r, text="Dim the numbers until the window has filled up", variable=bvar("rate_dim")).grid(row=6, column=0, columnspan=4, sticky="w", pady=(14, 0))
        ttk.Label(r, text="A dimmed number is based on less data than its header says (less time than the window covers since your first EXP gain). Headers are never dimmed. Set minutes to 0 to cover the whole session (since your first EXP gain; nothing is kept between runs).",
                  style="Hint.TLabel", wraplength=560, justify="left").grid(row=7, column=0, columnspan=4, sticky="w")

        # ---------- Appearance
        ap = page("Appearance")
        head(ap, "Text colour", 0)
        swatches(ap, 1, TEXT_COLORS, "text_color")
        radios(ap, 2, "Text size", "font_scale", FONT_SCALES)
        ttk.Checkbutton(ap, text="Text shadow (helps text stand out)", variable=bvar("text_shadow")).grid(row=5, column=0, sticky="w", pady=(6, 2), columnspan=4)
        head(ap, "Accent colour", 6)
        def acc_after(c):
            st.map("TCheckbutton", indicatorbackground=[("selected", c)]); st.map("TRadiobutton", indicatorbackground=[("selected", c)])
        swatches(ap, 7, ACCENTS, "accent", acc_after)
        head(ap, "Opacity", 8)
        slider(ap, 9, "Background", "bg_opacity", 0, 100)
        slider(ap, 10, "Text", "fg_opacity", 20, 100)
        head(ap, "Number format", 11)
        nf = tk.StringVar(value=NUMBER_FORMATS[S["number_format"]])
        cb_ = ttk.Combobox(ap, textvariable=nf, values=list(NUMBER_FORMATS.values()), state="readonly", width=28)
        cb_.grid(row=12, column=0, columnspan=4, sticky="w", pady=4)
        def nf_pick(*_):
            for k, v in NUMBER_FORMATS.items():
                if v == nf.get(): S["number_format"] = k
            self.apply(); cb_.selection_clear()
        cb_.bind("<<ComboboxSelected>>", nf_pick)

        # ---------- Graph
        gr = page("Graph")
        head(gr, "Display", 0)
        ttk.Checkbutton(gr, text="Show graph", variable=bvar("graph", after=self.resize)).grid(row=1, column=0, sticky="w", pady=3, columnspan=4)
        gm = tk.StringVar(value=S["mode"])
        def set_mode(*_): S["mode"] = gm.get(); self.apply()
        ttk.Label(gr, text="Plots").grid(row=2, column=0, sticky="w", pady=(6, 3))
        for i, (k, (_, label)) in enumerate(GRAPH_MODES.items()):
            ttk.Radiobutton(gr, text=label, variable=gm, value=k, command=set_mode).grid(row=2, column=1 + i, sticky="w", padx=(10, 0), pady=(6, 3))
        head(gr, "EXP per hour", 3)
        ttk.Label(gr, text="Rate over the last").grid(row=4, column=0, sticky="w", pady=3)
        rw = tk.Frame(gr, bg=BG); rw.grid(row=4, column=1, columnspan=3, sticky="w", padx=(10, 0))
        ttk.Spinbox(rw, from_=1, to=60, width=5, textvariable=ivar("graph_rate_minutes", 1, 60)).pack(side="left")
        ttk.Label(rw, text="minutes").pack(side="left", padx=(6, 0))
        ttk.Checkbutton(gr, text="Also show the session average (dashed line)", variable=bvar("graph_avg")).grid(row=5, column=0, sticky="w", pady=3, columnspan=4)
        ttk.Label(gr, text="A short window shows every change of pace; a longer one is calmer. Above the dashed line you are beating your session average.",
                  style="Hint.TLabel", wraplength=400, justify="left").grid(row=6, column=0, columnspan=4, sticky="w")
        head(gr, "Line", 7)
        gs = tk.StringVar(value=S["graph_style"])
        def set_style(*_): S["graph_style"] = gs.get(); self.apply()
        for i, (k, label) in enumerate(GRAPH_STYLES.items()):
            ttk.Radiobutton(gr, text=label, variable=gs, value=k, command=set_style).grid(row=8 + i, column=0, columnspan=4, sticky="w", pady=2)
        ttk.Label(gr, text="Stepped shows exactly when EXP arrived; straight joins the points; smooth averages them out. The EXP per hour graph is never stepped.",
                  style="Hint.TLabel", wraplength=400, justify="left").grid(row=11, column=0, columnspan=4, sticky="w", pady=(2, 0))
        slider(gr, 12, "Line thickness", "graph_width", 1, 4, fmt=lambda v: f"{v:.0f}px", scale=1.0)
        slider(gr, 13, "Line opacity", "graph_opacity", 0, 100)
        head(gr, "Fill", 14)
        ttk.Checkbutton(gr, text="Fill the area under the line", variable=bvar("graph_fill")).grid(row=15, column=0, sticky="w", pady=3, columnspan=4)
        slider(gr, 16, "Fill opacity", "fill_opacity", 0, 100)

        # ---------- Data
        d = page("Data")
        head(d, "Logging", 0)
        ttk.Checkbutton(d, text="Save every EXP change to maple_log.csv", variable=bvar("log_csv")).grid(row=1, column=0, sticky="w", pady=3, columnspan=4)
        ttk.Button(d, text="Open data folder", command=self.open_data_folder).grid(row=2, column=0, sticky="w", pady=(8, 3), columnspan=2)
        head(d, "Actions", 3)
        ttk.Button(d, text="Reset session now", command=self.reset).grid(row=4, column=0, sticky="w", pady=3)
        ttk.Button(d, text="Reset window position", command=self.reset_position).grid(row=4, column=1, sticky="w", padx=(10, 0), pady=3)
        head(d, "Defaults", 5)
        ttk.Button(d, text="Restore default settings", command=self.restore_defaults).grid(row=6, column=0, sticky="w", pady=3, columnspan=2)

        sw.bind("<Destroy>", lambda e: self.root.after(30, self.fix_stack) if e.widget is sw else None)
        foot = tk.Frame(sw, bg=BG); foot.pack(fill="x", padx=14, pady=(0, 12))
        tk.Label(foot, text="Changes apply instantly and are saved automatically.", bg=BG, fg=DIM, font=(FONT, 9)).pack(side="left")
        ttk.Button(foot, text="Close", command=sw.destroy).pack(side="right")

    def open_data_folder(self):
        try:
            if sys.platform == "win32": os.startfile(DATA)
            else:
                import subprocess; subprocess.Popen(["open" if MAC else "xdg-open", DATA])
        except Exception:
            pass

    def reset_position(self):
        self.S["x"], self.S["y"] = (self.root.winfo_screenwidth() - self.W) // 2, 40
        self.move(self.S["x"], self.S["y"]); self.save()

    def restore_defaults(self):
        keep = {k: self.S[k] for k in ("name", "x", "y")}
        self.S.clear(); self.S.update(DEFAULTS); self.S.update(keep)
        for k in ("rate_minutes", "rate_on", "rate_kind"): self.S[k] = list(DEFAULTS[k])
        self.resize(); self.apply()
        if self.sw is not None: self.sw.destroy(); self.sw = None
        self.open_settings()

    # ---- drawing
    def txt(self, x, y, text, size, color, bold=False, anchor="center", tags="dyn"):
        """Text with the configured size/colour and an optional dark shadow so it stands out."""
        f = (FONT, max(6, round(size * self.S["font_scale"])), "bold" if bold else "normal")
        if self.S["text_shadow"]:
            self.cv.create_text(x + 1, y + 1, text=text, anchor=anchor, fill="#000000", font=f, tags="dyn")
        return self.cv.create_text(x, y, text=text, anchor=anchor, fill=color, font=f, tags=tags)

    def measure(self, text, size):
        from tkinter import font as tkfont
        key = max(6, round(size * self.S["font_scale"]))
        f = self._fonts.setdefault(key, tkfont.Font(family=FONT, size=key, weight="bold"))
        return f.measure(text)

    def redraw(self):
        cv, W, H = self.cv, self.W, self.H
        for c in (self.cv, self.fillcv, self.linecv): c.delete("dyn")
        total = self.height()

        # header: status dot, name, % and level
        dot = {"ok": GOOD, "bad": BAD, "paused": WARN}.get(self.status, DIM2)
        cv.create_oval(24, 21, 34, 31, fill=dot, outline="", tags="dyn")
        if self.S["show_name"]:
            self.txt(42, 26, self.S["name"], 12, self.c_fg, True, "w")
        lvl, exp, pct = self.cur or (None, None, None)
        if self.hint and not self.paused:
            self.txt(W / 2 + 10, 26, self.hint, 9, BAD)
        lv = self.txt(W - 28, 26, f"Lv {lvl}" if lvl else "Lv \u2014", 12, self.c_fg, True, "e")
        if pct is not None:
            x = cv.bbox(lv)[0] - 14
            self.txt(x, 27, f"{pct:.2f}%", 10, self.c_label, False, "e")

        # divider doubles as the level-progress bar
        cv.create_line(22, 49, W - 22, 49, fill=BORDER, width=3, capstyle="round", tags="dyn")
        if pct:
            cv.create_line(22, 49, 22 + (W - 44) * pct / 100, 49, fill=self.acc, width=3, capstyle="round", tags="dyn")

        # EXP/h columns
        now = time.time()
        wins = [m * 60 for m, on in zip(self.S["rate_minutes"], self.S["rate_on"]) if on]
        kinds = [k for k, on in zip(self.S["rate_kind"], self.S["rate_on"]) if on]
        cw = (W - 44) / len(wins)
        for i, w in enumerate(wins):
            cx = 22 + cw * (i + 0.5)
            kind = kinds[i]
            r = self.tracker.metric(kind, now, w, self.cur[2] if self.cur else None)
            self.txt(cx, 68, f"{KINDS[kind][0]} \u00b7 " + (f"{w // 60}M" if w else "SESSION"), 8, self.c_fg, True)
            if r:
                t = ("~" if self.tracker.approx and kind in ("exp_h", "exp_gain", "avg") else "") + r[0]
                col = self.c_fg if (r[1] or not self.S["rate_dim"]) else self.c_sub       # dimmer until the window has filled up
            else:
                t, col = "\u2014", self.c_faint
            size = 17                                          # shrink long numbers so columns never overlap
            while size > 9 and self.measure(t, size) > cw - 14:
                size -= 1
            self.txt(cx, 93, t, size, col, True)
            if i:
                cv.create_line(22 + cw * i, 60, 22 + cw * i, 104, fill=BORDER, width=3, capstyle="round", tags="dyn")

        # graph toggle chevron
        self.txt(W / 2, H - 11, "\u25b4" if self.S["graph"] else "\u25be", 9, self.c_label, False, "center", ("dyn", "toggle"))
        cv.create_rectangle(W / 2 - 30, H - 22, W / 2 + 30, H - 2, outline="", fill="", tags=("dyn", "toggle"))

        if self.S["graph"]:
            self.draw_graph(22, H + 4, W - 22, total - 16, now)

    def graph_series(self, mode, now):
        """-> (xs, ys, avg) in seconds / value, shaped according to the graph style. avg is the
        session-average line of the EXP per hour graph (else None). None if there's nothing to plot yet."""
        tr, style = self.tracker, self.S["graph_style"]
        t0 = tr.t0
        if mode == "rate":                                  # always a line: rates change gradually
            r = tr.rate_series(now, self.S["graph_rate_minutes"] * 60)
            if r is None:
                return None
            g, ys, avg = r
            return list(g - t0), list(blur(ys) if style == "smooth" else ys), list(avg)
        if len(tr.points) < 2:
            return None
        idx = 1 if mode == "exp" else 2
        if style == "step":
            xs, ys, prev = [], [], 0
            for p in tr.points:
                xs += [p[0] - t0, p[0] - t0]; ys += [prev, p[idx]]; prev = p[idx]
            return xs + [now - t0], ys + [prev], None
        px = [p[0] - t0 for p in tr.points] + [now - t0]
        py = [p[idx] for p in tr.points] + [tr.points[-1][idx]]
        if len(px) > 700:                                   # keep the canvas light on long sessions
            k = len(px) // 700 + 1
            px, py = px[::k] + [px[-1]], py[::k] + [py[-1]]
        if style == "line":
            return px, py, None
        # smooth: resample on an even grid and blur lightly
        gx = np.linspace(px[0], px[-1], 140)
        return list(gx), list(blur(np.interp(gx, px, py))), None

    def draw_graph(self, x1, y1, x2, y2, now):
        cv, tr = self.cv, self.tracker
        fcv, lcv = self.fillcv, self.linecv
        mode = self.S["mode"]
        cv.create_line(x1, y1 - 2, x2, y1 - 2, fill=BORDER, width=1, tags="dyn")
        # header line: session summary + EXP/%/EXP-per-hour switch
        if tr.t0 is not None:
            r = tr.rate(now, 900) or tr.rate(now, 10 ** 9)
            eta = f"  \u00b7  level in {fmt_dur((100 - self.cur[2]) / r[1] * 3600)}" if r and r[1] > 0 and self.cur else ""
            ap = "~" if tr.approx else ""
            sp = ("+" if tr.cum_pct >= 0 else "\u2212") + f"{abs(tr.cum_pct):.2f}%"
            t = f"{fmt_dur(now - tr.t0)}  \u00b7  {fmt_signed(tr.cum_exp, ap)} EXP  \u00b7  {sp}{eta}"
        else:
            t = "Waiting for data\u2026"
        self.txt(x1, y1 + 14, t, 9, self.c_fg, False, "w")
        bx = x2 - 4                                          # buttons, right to left
        for key, (label, _) in reversed(GRAPH_MODES.items()):
            on, w = mode == key, 36 if len(label) < 4 else 50
            rrect(cv, bx - w, y1 + 4, bx, y1 + 24, 9, fill=self.acc_fill if on else BG,
                  outline=self.acc if on else BORDER, width=1, tags=("dyn", f"mode_{key}"))
            cv.create_text(bx - w / 2, y1 + 14, text=label, fill=self.acc if on else self.c_label,
                           font=(FONT, 8, "bold"), tags=("dyn", f"mode_{key}"))
            bx -= w + 8

        # chart
        L, T, R, B = x1 + 46, y1 + 36, x2, y2 - 16
        series = self.graph_series(mode, now)
        if series is None:
            msg = "Gathering a minute of EXP\u2026" if mode == "rate" and tr.t_first else "Gain some EXP to start the graph"
            self.txt((L + R) / 2, (T + B) / 2, msg, 10, self.c_sub)
            return
        xs, ys, avg = series
        if not self.S["graph_avg"]: avg = None
        xmax = max(xs[-1], 60)
        ymin, ymax = min(0, min(ys + (avg or []))), max(ys + (avg or []))
        if ymax - ymin < 1: ymax = ymin + 1
        if mode == "rate": ymax *= 1.15                    # headroom so the line stays clear of the legend
        px = lambda x: L + (R - L) * x / xmax
        py = lambda y: B - (B - T) * (y - ymin) / (ymax - ymin)
        for tv in nice_ticks(ymin, ymax):
            y = py(tv)
            lcv.create_line(L, y, R, y, fill="#2a2d36", tags="dyn")
            lab = fmt_num(tv) if mode == "exp" else fmt_short(tv) if mode == "rate" else f"{tv:.0f}%"
            self.txt(L - 8, y, lab, 8, self.c_label, False, "e")
        for i in range(5):
            x = xmax * i / 4
            self.txt(px(x), B + 11, fmt_dur(x), 8, self.c_label, False,
                     "w" if i == 0 else "e" if i == 4 else "center")
        line = [c for x, y in zip(xs, ys) for c in (px(x), py(y))]
        if self.S["graph_fill"]:       # solid accent on its own layer; that layer's opacity is the fill opacity
            fcv.create_polygon(line + [px(xs[-1]), py(0), px(xs[0]), py(0)], fill=self.acc, outline="", tags="dyn")
        wd = self.S["graph_width"]
        if avg:
            lcv.create_line(*[c for x, y in zip(xs, avg) for c in (px(x), py(y))],
                            fill=self.c_sub, width=1, dash=(4, 3), tags="dyn")
        if mode == "rate":
            self.txt(L + 6, T + 2, f"EXP/h over the last {self.S['graph_rate_minutes']} min"
                     + ("   - - session average" if avg else ""), 8, self.c_label, False, "nw")
        lcv.create_line(*line, fill=self.acc, width=wd, joinstyle="round", tags="dyn")
        r_ = 2 + wd
        lcv.create_oval(px(xs[-1]) - r_, py(ys[-1]) - r_, px(xs[-1]) + r_, py(ys[-1]) + r_, fill=self.acc, outline="", tags="dyn")

    # ---- data feed
    def locate(self, sct):
        """Search every monitor for the HP/MP/EXP status bar. -> dict(x, y) in screen pixels."""
        for mon in sct.monitors[1:]:
            a = np.asarray(sct.grab(mon))[:, :, 2::-1]       # BGRA -> RGB view
            bars = find_bars(a)
            if bars:
                return dict(x=mon["left"] + bars[0][1][0], y=mon["top"] + bars[0][0])
        return None

    def worker(self):
        import mss
        sim = dict(exp=5000, req=120000)
        loc, fails, lvl, lvl_t, prev_pct = None, 0, None, 0.0, None
        with mss.mss() as s:
            while True:
                t0 = time.time()
                if not self.paused:
                    try:
                        if self.demo:
                            sim["exp"] += np.random.randint(0, 9) if np.random.rand() < 0.2 else 0
                            self.q.put(("read", t0, dict(found=True, level=40, exp=sim["exp"], unknown=False,
                                        pct=round(sim["exp"] / sim["req"] * 100, 2))))
                        else:
                            if loc is None or fails >= 3:      # (re)find the bar: window moved/resized
                                loc, fails, lvl = self.locate(s), 0, None
                                self.loc = loc
                            if loc is None:
                                self.q.put(("read", t0, dict(found=False, unknown=False, exp=None, pct=None, level=None)))
                                time.sleep(0.5); continue
                            box = {"left": loc["x"] + STRIP_X[0], "top": loc["y"],
                                   "width": STRIP_X[1] - STRIP_X[0], "height": 7}
                            r = read_strip(np.asarray(s.grab(box))[:, :, 2::-1])
                            if not r["found"]:
                                fails += 1
                            else:
                                fails = 0
                                wrapped = prev_pct is not None and r["pct"] is not None and prev_pct - r["pct"] > 30
                                if lvl is None or wrapped or t0 - lvl_t > 3:
                                    L = LEVEL_REL
                                    sh = s.grab({"left": loc["x"] + L[0], "top": loc["y"] + L[1],
                                                 "width": L[2] - L[0], "height": L[3] - L[1]})
                                    lvl, lvl_t = read_level(Image.frombytes("RGB", sh.size, sh.bgra, "raw", "BGRX")), t0
                                if r["pct"] is not None: prev_pct = r["pct"]
                            r["level"] = lvl
                            self.q.put(("read", t0, r))
                    except Exception as ex:
                        self.q.put(("error", str(ex)))
                time.sleep(max(0.0, 1.0 / self.S["reads_per_sec"] - (time.time() - t0)))

    def name_worker(self):
        """Reads the character name now and then (slow-changing, so not part of the fast loop)."""
        import mss
        votes = []
        last_loc = None
        with mss.mss() as s:
            while True:
                loc = self.loc
                if loc is None or self.paused or self.demo:
                    time.sleep(0.5); continue
                if loc != last_loc:
                    votes, last_loc = [], loc
                try:
                    N = NAME_REL
                    sh = s.grab({"left": loc["x"] + N[0], "top": loc["y"] + N[1],
                                 "width": N[2] - N[0], "height": N[3] - N[1]})
                    nm = read_name(Image.frombytes("RGB", sh.size, sh.bgra, "raw", "BGRX"))
                    if nm:
                        votes = (votes + [nm])[-5:]
                        top = max(set(votes), key=votes.count)
                        if votes.count(top) >= 2 or len(votes) >= 3:
                            self.q.put(("name", top))
                except Exception:
                    pass
                time.sleep(1.0 if len(votes) < 5 else 15.0)

    def log_row(self, t, lvl, exp, pct):
        if not self.S["log_csv"]:
            return
        path = os.path.join(DATA, "maple_log.csv")
        try:
            new = not os.path.exists(path)
            with open(path, "a", newline="") as f:
                w = csv.writer(f)
                if new: w.writerow(["time", "level", "exp", "percent"])
                w.writerow([datetime.datetime.fromtimestamp(t).isoformat(timespec="seconds"), lvl, exp, pct])
        except OSError:
            pass

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "error":
                    self.status, self.hint = "bad", "capture error"; continue
                if msg[0] == "name":
                    if msg[1] != self.S["name"]:
                        import difflib
                        if (self.S["reset_on_char"] and self.name_seen and
                                difflib.SequenceMatcher(None, msg[1].lower(), self.S["name"].lower()).ratio() < 0.6):
                            self.tracker.reset()          # a different character, not just an OCR wobble
                        self.S["name"] = msg[1]; self.save()
                    self.name_seen = True
                    continue
                _, t, r = msg
                if not r["found"]:
                    self.fails += 1
                    if self.fails >= 5: self.status, self.hint = "bad", "status bar not found"
                    continue
                if r["unknown"]:
                    self.fails += 1
                    if self.fails >= 5: self.status, self.hint = "bad", "unreadable digit"
                    continue
                lvl, exp, pct = r["level"], r["exp"], r["pct"]
                if None in (lvl, exp, pct):
                    self.fails += 1
                    if self.fails >= 5: self.status, self.hint = "bad", "can't read status bar"
                    continue
                self.fails, self.status, self.hint, self.cur = 0, "ok", "", (lvl, exp, pct)
                if self.tracker.feed(t, lvl, exp, pct):
                    self.log_row(t, lvl, exp, pct)
        except queue.Empty:
            pass
        if self.paused: self.status = "paused"
        self.fix_stack()
        self.redraw()
        self.root.after(250, self.poll)

    def run(self):
        for w in self.layers: w.update_idletasks()
        self.win32_own(); self.fix_stack()
        threading.Thread(target=self.worker, daemon=True).start()
        threading.Thread(target=self.name_worker, daemon=True).start()
        self.root.after(300, self.poll)
        self.root.mainloop()

# ------------------------------------------------------------------ entry
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", help="read a screenshot and print the result")
    ap.add_argument("--debug", action="store_true", help="save the level OCR crop to ./debug")
    ap.add_argument("--demo", action="store_true", help="fake data, to preview the UI")
    a = ap.parse_args()
    DEBUG = a.debug
    if a.image:
        out = read_image(Image.open(a.image))
        if sys.stdout: print(out if out else "status bar not found")
    else:
        App(demo=a.demo).run()
