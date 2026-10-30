"""What the rate columns show: header and value text (no Tk needed)."""
from .. import fmt
from ..settings import KINDS
from ..tracker import eta_seconds

APPROX_KINDS = ("exp_h", "exp_gain", "avg")   # values that include an estimated level-up get a "~"


def header(kind, win):
    """e.g. 'EXP/H · 15M', or 'EXP/H · SESSION' for a window of 0."""
    return f"{KINDS[kind][0]} · " + (f"{win // 60}M" if win else "SESSION")


def value(tracker, kind, now, win, cur_pct=None):
    """(text, window_is_full) for one column, or None if there is not enough data yet."""
    r = tracker.rate(now, win)
    if r is None:
        return None
    eh, ph, full = r
    start, span = tracker.window(now, win)
    if kind == "exp_h":      t = fmt.num(eh)
    elif kind == "exp_gain": t = "+" + fmt.num(eh * span / 3600)
    elif kind == "pct_h":    t = fmt.pct(ph, 1)
    elif kind == "pct_gain": t = "+" + fmt.pct(ph * span / 3600, 2)
    elif kind == "eta":
        sec = eta_seconds(cur_pct, ph)
        t = fmt.DASH if sec is None else fmt.dur(sec) if sec < 100 * 3600 else "99h+"
    elif kind == "kills":    t = str(tracker.gains(start))
    elif kind == "avg":
        n = tracker.gains(start)
        t = fmt.num(eh * span / 3600 / n) if n else fmt.DASH
    else: t = fmt.num(eh)
    if tracker.approx and kind in APPROX_KINDS: t = "~" + t
    return t, full


def line(tracker, cols, now, cur_pct=None, sep=" \u00b7 "):
    """Several columns on one line of text, exactly as the overlay shows them, e.g.
    'EXP/H 7.640.000 · LEVEL IN 5:12:00'. `cols`: [(window, kind)]. Columns without enough data
    yet are left out; '' if none."""
    parts = []
    for win, kind in cols:
        v = value(tracker, kind, now, win, cur_pct)
        if v: parts.append(f"{KINDS[kind][0]} {v[0]}")
    return sep.join(parts)
