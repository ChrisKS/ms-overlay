"""EXP bookkeeping: turns confirmed readings into cumulative EXP / % gained, and rates over windows.

All times given to a Tracker are session-clock seconds (see Session.clock); it never looks at the
wall clock itself."""
import numpy as np

WHOLE = 10 ** 9          # a window that covers the whole session
RECENT = 900             # "your current pace": the last 15 minutes


def eta_seconds(cur_pct, pct_per_hour):
    """Seconds until 100% at this pace, or None if there is no progress to extrapolate."""
    if cur_pct is None or not pct_per_hour or pct_per_hour <= 0:
        return None
    return (100 - cur_pct) / pct_per_hour * 3600


class Tracker:
    """Turns noisy readings into a session: cumulative EXP and % gained."""
    def __init__(self): self.reset()

    def reset(self):
        self.t0 = None; self.last = None; self.cand = None
        self.first = None           # first accepted (level, exp, pct) of the session
        self.t_first = None         # time of the first EXP gain: the rate clock starts here
        self.points = []            # (t, cum_exp, cum_pct) on every change
        self.cum_exp = 0; self.cum_pct = 0.0
        self.req = {}               # level -> (best_pct, estimated EXP needed)
        self.approx = False         # True if a level-up had to be estimated
        self.skip = False           # next reading is a new starting point, not a gain (after a pause)

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
        if not confirmed:
            return False
        if self.skip:                              # whatever changed while paused isn't counted
            self.skip = False
            if self.last is not None:              # (a session that hasn't started has nothing to skip)
                self._learn_req(lvl, exp, pct)
                changed, self.last = reading != self.last, reading
                return changed
        if reading == self.last:
            return False
        self._learn_req(lvl, exp, pct)
        if self.last is None:
            self.t0 = t; self.last = self.first = reading; self.points = [(t, 0, 0.0)]
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

    def skip_gap(self):
        """Called on resume: the next reading becomes the new starting point, so EXP gained (or a
        level reached) while the reader was paused doesn't count towards the session."""
        self.cand, self.skip = None, True

    def value_at(self, t, idx):
        v = 0
        for p in self.points:
            if p[0] <= t: v = p[idx]
            else: break
        return v

    def window(self, now, win):
        """(start, span) of the last `win` seconds (0 = whole session), never before the first
        EXP gain: idle time before it is ignored."""
        if win <= 0: win = WHOLE
        start = max(self.t_first, now - win)
        return start, now - start

    def rate(self, now, win):
        """(exp/hour, pct/hour, window_is_full) over the last `win` seconds (0 = whole session).
        A window longer than the session uses the session so far."""
        if self.t_first is None:
            return None
        start, span = self.window(now, win)
        if span < 8:
            return None
        if win <= 0: win = WHOLE
        return ((self.cum_exp - self.value_at(start, 1)) / span * 3600,
                (self.cum_pct - self.value_at(start, 2)) / span * 3600,
                now - self.t_first >= win or win >= WHOLE)

    def recent_rate(self, now):
        """The current pace: rate over the last 15 minutes, or the whole session if shorter."""
        return self.rate(now, RECENT) or self.rate(now, WHOLE)

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
