"""The overlay's core without any UI: turns the reader's results into a session, keeps a clock that
stands still while paused, and reports what happened (accepted changes, level-ups)."""
import difflib
import time

from .tracker import Tracker

FAIL_AFTER = 5           # failed reads in a row before the overlay shows a problem
STALE_AFTER = 60         # seconds without a good read before the game is treated as closed


def different_character(a, b):
    """True if two read names belong to different characters, not just an OCR wobble."""
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() < 0.6


class Session:
    def __init__(self):
        self.tracker = Tracker()
        self.paused = False
        self.pause_t = None         # wall time the current pause started
        self.paused_total = 0.0     # seconds spent paused so far: cut out of the session clock
        self.cur = None             # last good (level, exp, pct)
        self.status, self.hint = "wait", ""
        self.fails = 0
        self.last_ok = 0.0          # wall time of the last good reading

    @property
    def state(self):
        """'wait' (nothing read yet), 'ok', 'bad' (see hint) or 'paused'."""
        return "paused" if self.paused else self.status

    def clock(self, t=None):
        """Wall time -> session time, which stands still while paused. The tracker only ever sees
        session time, so paused time is left out of every rate, window and duration."""
        t = time.time() if t is None else t
        if self.pause_t is not None: t = min(t, self.pause_t)
        return t - self.paused_total

    def toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self.pause_t = time.time()
        else:
            self.paused_total += time.time() - self.pause_t; self.pause_t = None
            self.tracker.skip_gap()
            self.status = "wait"

    def reset(self):
        self.tracker.reset()

    def capture_error(self):
        self.status, self.hint = "bad", "capture error"

    def _fail(self, hint):
        self.fails += 1
        if self.fails >= FAIL_AFTER: self.status, self.hint = "bad", hint

    def read(self, t, r):
        """One result from the reader, taken at wall time t. -> (changed, new_level): `changed` if
        the session accepted a change (worth logging); `new_level` if that change was a level-up."""
        if not r["found"]:
            self._fail("status bar not found"); return False, None
        if r["unknown"]:
            self._fail("unreadable digit"); return False, None
        lvl, exp, pct = r["level"], r["exp"], r["pct"]
        if None in (lvl, exp, pct):
            self._fail("can't read status bar"); return False, None
        self.fails, self.status, self.hint, self.cur = 0, "ok", "", (lvl, exp, pct)
        self.last_ok = t
        before = self.tracker.last
        if not self.tracker.feed(self.clock(t), lvl, exp, pct):
            return False, None
        up = before is not None and lvl == before[0] + 1 and pct < 50   # a real level-up starts low
        return True, (lvl if up else None)

    def recently_read(self, now):
        """False once nothing has been read for a while (the game is probably closed)."""
        return self.paused or self.status == "ok" or now - self.last_ok <= STALE_AFTER
