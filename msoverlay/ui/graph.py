"""The graph under the overlay: what to plot (series, no Tk needed) and how to draw it."""
import numpy as np

from .. import fmt
from ..settings import GRAPH_MODES
from ..tracker import eta_seconds
from .theme import BG, BORDER, FONT, GRID, rrect

MAX_POINTS = 700         # downsample longer sessions to keep the canvas light


def blur(y):
    """Light Gaussian blur for the smooth graph style; keeps both ends where they were."""
    k = np.exp(-0.5 * (np.arange(-6, 7) / 2.2) ** 2); k /= k.sum()
    sm = np.convolve(np.pad(np.asarray(y, dtype=float), 6, mode="edge"), k, mode="valid")
    sm[0], sm[-1] = y[0], y[-1]
    return sm


def nice_ticks(lo, hi, n=4):
    """About n round axis values between lo and hi (steps of 1, 2, 2.5 or 5 times a power of 10)."""
    raw = (hi - lo) / n
    mag = 10 ** int(np.floor(np.log10(raw)))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    first = np.ceil(lo / step) * step
    return [first + i * step for i in range(int((hi - first) / step) + 1)]


def series(tracker, mode, style, rate_minutes, now):
    """-> (xs, ys, avg): seconds since the session started / values, shaped according to the graph
    style. avg is the session-average line of the EXP per hour graph (else None). None if there's
    nothing to plot yet."""
    tr, t0 = tracker, tracker.t0
    if mode == "rate":                                  # always a line: rates change gradually
        r = tr.rate_series(now, rate_minutes * 60)
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
    if len(px) > MAX_POINTS:
        k = len(px) // MAX_POINTS + 1
        px, py = px[::k] + [px[-1]], py[::k] + [py[-1]]
    if style == "line":
        return px, py, None
    # smooth: resample on an even grid and blur lightly
    gx = np.linspace(px[0], px[-1], 140)
    return list(gx), list(blur(np.interp(gx, px, py))), None


SEP = "  \u00b7  "


def summary_parts(tracker, cur, now):
    """The text above the graph, most important first: session time, EXP and % gained, time to
    level. (A narrow overlay shows as many as fit.)"""
    tr = tracker
    if tr.t0 is None:
        return ["Waiting for data\u2026"]
    r = tr.recent_rate(now)
    eta = eta_seconds(cur[2] if cur else None, r[1] if r else None)
    parts = [fmt.dur(now - tr.t0), f"{fmt.signed(tr.cum_exp, '~' if tr.approx else '')} EXP", fmt.signed_pct(tr.cum_pct)]
    return parts + ([f"level in {fmt.dur(eta)}"] if eta is not None else [])


def summary_line(tracker, cur, now):
    return SEP.join(summary_parts(tracker, cur, now))


def draw(ov, x1, y1, x2, y2, now):
    """Draw the graph panel of overlay `ov` into the box (x1, y1)-(x2, y2). The axes, labels and
    buttons go on the text layer, the fill and the line on their own layers (own opacity)."""
    S, tr = ov.S, ov.session.tracker
    cv, fcv, lcv = ov.cv, ov.fillcv, ov.linecv
    mode = S["mode"]
    cv.create_line(x1, y1 - 2, x2, y1 - 2, fill=BORDER, width=1, tags="dyn")
    # header line: EXP/%/EXP-per-hour switch, and as much of the session summary as fits beside it
    bx = x2 - 4                                          # buttons, right to left
    for key, (label, _) in reversed(GRAPH_MODES.items()):
        on, w = mode == key, 36 if len(label) < 4 else 50
        rrect(cv, bx - w, y1 + 4, bx, y1 + 24, 9, fill=ov.acc_fill if on else BG,
              outline=ov.acc if on else BORDER, width=1, tags=("dyn", f"mode_{key}"))
        cv.create_text(bx - w / 2, y1 + 14, text=label, fill=ov.acc if on else ov.c_label,
                       font=(FONT, 8, "bold"), tags=("dyn", f"mode_{key}"))
        bx -= w + 8
    parts = summary_parts(tr, ov.session.cur, now)
    text = ov.fitting([SEP.join(parts[:n]) for n in range(len(parts), 0, -1)], 9, bx - x1, bold=False)
    if text: ov.txt(x1, y1 + 14, text, 9, ov.c_fg, False, "w")

    # chart
    L, T, R, B = x1 + 46, y1 + 36, x2, y2 - 16
    data = series(tr, mode, S["graph_style"], S["graph_rate_minutes"], now)
    if data is None:
        msg = "Gathering a minute of EXP…" if mode == "rate" and tr.t_first else "Gain some EXP to start the graph"
        ov.txt((L + R) / 2, (T + B) / 2, msg, 10, ov.c_sub)
        return
    xs, ys, avg = data
    if not S["graph_avg"]: avg = None
    xmax = max(xs[-1], 60)
    ymin, ymax = min(0, min(ys + (avg or []))), max(ys + (avg or []))
    if ymax - ymin < 1: ymax = ymin + 1
    if mode == "rate": ymax *= 1.15                    # headroom so the line stays clear of the legend
    px = lambda x: L + (R - L) * x / xmax
    py = lambda y: B - (B - T) * (y - ymin) / (ymax - ymin)
    for tv in nice_ticks(ymin, ymax):
        y = py(tv)
        lcv.create_line(L, y, R, y, fill=GRID, tags="dyn")
        lab = fmt.num(tv) if mode == "exp" else fmt.short(tv) if mode == "rate" else f"{tv:.0f}%"
        ov.txt(L - 8, y, lab, 8, ov.c_label, False, "e")
    n = max(1, min(4, int((R - L) // 80)))             # time labels: fewer on a narrow graph
    for i in range(n + 1):
        x = xmax * i / n
        ov.txt(px(x), B + 11, fmt.dur(x), 8, ov.c_label, False, "w" if i == 0 else "e" if i == n else "center")
    line = [c for x, y in zip(xs, ys) for c in (px(x), py(y))]
    if S["graph_fill"]:       # solid accent on its own layer; that layer's opacity is the fill opacity
        fcv.create_polygon(line + [px(xs[-1]), py(0), px(xs[0]), py(0)], fill=ov.acc, outline="", tags="dyn")
    wd = S["graph_width"]
    if avg:
        lcv.create_line(*[c for x, y in zip(xs, avg) for c in (px(x), py(y))],
                        fill=ov.c_sub, width=1, dash=(4, 3), tags="dyn")
    if mode == "rate":
        m = S["graph_rate_minutes"]
        legend = ov.fitting([f"EXP/h over the last {m} min" + ("   - - session average" if avg else ""),
                             f"last {m} min" + ("  - - average" if avg else ""), f"{m} min"], 8, R - L - 12, bold=False)
        if legend: ov.txt(L + 6, T + 2, legend, 8, ov.c_label, False, "nw")
    lcv.create_line(*line, fill=ov.acc, width=wd, joinstyle="round", tags="dyn")
    r_ = 2 + wd
    lcv.create_oval(px(xs[-1]) - r_, py(ys[-1]) - r_, px(xs[-1]) + r_, py(ys[-1]) + r_, fill=ov.acc, outline="", tags="dyn")
