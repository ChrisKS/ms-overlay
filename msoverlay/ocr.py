"""Reading the status bar from pixels: finding it on screen (by its green HP/MP/EXP brackets),
the EXP number and % (exact glyph matching), and the level and character name (Tesseract).

Nothing here captures the screen; see capture.py for that."""
import os
import re

import numpy as np
import pytesseract
from PIL import Image, ImageChops, ImageOps

from .paths import BASE, MAC

DEBUG = False            # --debug: save the level OCR crops to ./debug


def setup_tesseract():
    """Use the bundled Tesseract (next to the exe on Windows, in the app's Resources folder on
    macOS), else a system install, else whatever is on PATH."""
    for path, bundled in ((os.path.join(BASE, "tesseract", "tesseract.exe"), True),
                          (os.path.join(BASE, "tesseract", "tesseract"), True),
                          (os.path.join(BASE, "..", "Resources", "tesseract", "tesseract"), True),
                          (r"C:\Program Files\Tesseract-OCR\tesseract.exe", False),
                          ("/opt/homebrew/bin/tesseract", False),
                          ("/usr/local/bin/tesseract", False)):
        if os.path.isfile(path):
            pytesseract.pytesseract.tesseract_cmd = path
            if bundled and MAC:    # a relocated macOS build doesn't know where its language data is
                os.environ.setdefault("TESSDATA_PREFIX", os.path.join(os.path.dirname(path), "tessdata"))
            return path
    return None


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

# Areas of the status bar, as (left, top, right, bottom) relative to the HP "[" bracket's x and the
# glyph top row's y (where find_bars() reports the bar)
STRIP_REL = (-20, 0, 720, 7)     # the HP / MP / EXP line: brackets, EXP number and %
LEVEL_REL = (-195, 1, -165, 15)  # the orange level box
NAME_REL = (-158, 11, -30, 25)   # the character-name line (under the job)
JOB_REL = (-158, -3, -30, 11)    # the job line, right above the name line (not yet checked on a real screen)
EXP_START = 227                  # EXP digits start >= this many px right of the HP "[" (label ends at 226)


def rel_rect(x, y, rel):
    """An area of the status bar in screen / image pixels: (left, top, right, bottom)."""
    return (x + rel[0], y + rel[1], x + rel[2], y + rel[3])


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
    first = -STRIP_REL[0] + EXP_START
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


LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# Job names as the game shows them, every advancement. Read text must match one closely, so a
# misread never comes out as a made-up job.
JOBS = [
    "Beginner", "Noblesse", "Citizen", "Legend",
    # Explorers
    "Warrior", "Fighter", "Crusader", "Hero", "Page", "White Knight", "Paladin",
    "Spearman", "Berserker", "Dark Knight",
    "Magician", "Wizard (Fire, Poison)", "Mage (Fire, Poison)", "Arch Mage (Fire, Poison)",
    "Wizard (Ice, Lightning)", "Mage (Ice, Lightning)", "Arch Mage (Ice, Lightning)",
    "Wizard (F/P)", "Mage (F/P)", "Arch Mage (F/P)", "Wizard (I/L)", "Mage (I/L)", "Arch Mage (I/L)",
    "Cleric", "Priest", "Bishop",
    "Bowman", "Archer", "Hunter", "Ranger", "Bowmaster", "Crossbowman", "Crossbow Master", "Sniper", "Marksman",
    "Pathfinder",
    "Thief", "Assassin", "Hermit", "Night Lord", "Bandit", "Chief Bandit", "Shadower",
    "Blade Recruit", "Blade Acolyte", "Blade Specialist", "Blade Lord", "Blade Master", "Dual Blade",
    "Pirate", "Brawler", "Marauder", "Buccaneer", "Gunslinger", "Outlaw", "Corsair",
    "Cannoneer", "Cannon Trooper", "Cannon Master",
    # Cygnus Knights
    "Dawn Warrior", "Blaze Wizard", "Wind Archer", "Night Walker", "Thunder Breaker", "Mihile",
    # Heroes
    "Aran", "Evan", "Mercedes", "Phantom", "Luminous", "Shade",
    # Resistance
    "Battle Mage", "Wild Hunter", "Mechanic", "Xenon", "Blaster", "Demon Slayer", "Demon Avenger",
    # Nova, Flora, Anima and others
    "Kaiser", "Kain", "Cadena", "Angelic Buster", "Adele", "Illium", "Khali", "Ark",
    "Hoyoung", "Lara", "Lynn", "Mo Xuan", "Sia Astra", "Ren",
    "Hayato", "Kanna", "Zero", "Kinesis", "Beast Tamer", "Jett",
]
_JOB_KEYS = {re.sub(r"[^a-z]", "", j.lower()): j for j in JOBS}


def match_job(text):
    """The job name `text` was read as, or None if it isn't close to any real job."""
    import difflib
    key = re.sub(r"[^a-z]", "", (text or "").lower())
    hit = difflib.get_close_matches(key, _JOB_KEYS, n=1, cutoff=0.85) if key else []
    return _JOB_KEYS[hit[0]] if hit else None


def _read_line(img, whitelist, name, spaces=True):
    """OCR one line of near-white pixel text. Majority vote over a few scalings, since Tesseract
    is occasionally off by a letter on this small font. -> the winning text, or None."""
    a = np.asarray(img.convert("RGB")).astype(int)
    ink = a.min(axis=2) >= 215
    if DEBUG:
        os.makedirs("debug", exist_ok=True)
        img.save(f"debug/{name}_raw.png")
    cols = np.where(ink.any(axis=0))[0]
    if len(cols) == 0:
        return None
    b = Image.fromarray(np.where(ink, 0, 255).astype("uint8"))
    b = b.crop((max(cols[0] - 2, 0), 0, cols[-1] + 3, b.height))
    votes = []
    for scale, flt in ((4, Image.BICUBIC), (3, Image.LANCZOS), (4, Image.LANCZOS), (3, Image.BICUBIC)):
        p = ImageOps.expand(b.resize((b.width * scale, b.height * scale), flt), border=24, fill=255)
        try:
            t = pytesseract.image_to_string(p, config=f"--psm 7 -c tessedit_char_whitelist={whitelist}").strip()
        except Exception:
            continue
        if t: votes.append(t if spaces else t.replace(" ", ""))
    if not votes:
        return None
    return max(set(votes), key=lambda v: (votes.count(v), -votes.index(v)))


def read_name(img):
    """The character name from the status bar's name line."""
    return _read_line(img, LETTERS + "0123456789", "name", spaces=False)


def read_job(img):
    """The job from the status bar's job line, or None unless it reads as a real job name."""
    return match_job(_read_line(img, LETTERS + "()/,", "job"))


def read_image(img):
    """Read a whole screenshot (CLI / tests). -> result dict, or None if no status bar found."""
    a = np.asarray(img.convert("RGB"))
    bars = find_bars(a)
    if not bars:
        return None
    y, xs = bars[0]
    x = xs[0]
    left, top, right, bottom = rel_rect(x, y, STRIP_REL)
    res = read_strip(a[top:bottom, max(left, 0):right])
    res["level"] = read_level(img.crop(rel_rect(x, y, LEVEL_REL)))
    res["name"] = read_name(img.crop(rel_rect(x, y, NAME_REL)))
    res["job"] = read_job(img.crop(rel_rect(x, y, JOB_REL)))
    return res

