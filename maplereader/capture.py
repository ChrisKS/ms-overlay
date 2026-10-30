"""Screen capture: background threads that read the status bar and report through a queue.

Messages put on the queue:
  ("read", wall_time, result)   a result of ocr.read_strip() plus "level" (see Session.read)
  ("name", name)                the character name, once it has been read consistently
  ("job", job)                  the job, likewise (only real job names; see ocr.match_job)
  ("error", text)               the screen couldn't be captured
"""
import threading
import time

import numpy as np
from PIL import Image

from . import ocr

NOT_FOUND = dict(found=False, unknown=False, exp=None, pct=None, level=None)


def _box(rect):
    left, top, right, bottom = rect
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def grab_array(sct, rect):
    """Screen area (left, top, right, bottom) -> HxWx3 RGB array."""
    return np.asarray(sct.grab(_box(rect)))[:, :, 2::-1]       # BGRA -> RGB view


def grab_image(sct, rect):
    """Screen area (left, top, right, bottom) -> PIL RGB image."""
    shot = sct.grab(_box(rect))
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def locate(sct):
    """Search every monitor for the HP/MP/EXP status bar. -> (x, y) in screen pixels, or None."""
    for mon in sct.monitors[1:]:
        bars = ocr.find_bars(grab_array(sct, (mon["left"], mon["top"], mon["left"] + mon["width"],
                                              mon["top"] + mon["height"])))
        if bars:
            return mon["left"] + bars[0][1][0], mon["top"] + bars[0][0]
    return None


class Reader:
    """Runs the two reading loops. `settings` is read live (reads per second); `session` is only
    asked whether it is paused."""
    def __init__(self, q, settings, session, demo=False):
        self.q, self.S, self.session, self.demo = q, settings, session, demo
        self.loc = None             # where the status bar is on screen: (x, y) of the HP "["

    def start(self):
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._name_loop, daemon=True).start()

    def _read_loop(self):
        """EXP and % several times a second; the level every few seconds (and right after a likely
        level-up). The demo feeds made-up, slowly rising EXP instead."""
        import mss
        sim = dict(exp=5000, req=120000)
        loc, fails, lvl, lvl_t, prev_pct = None, 0, None, 0.0, None
        with mss.mss() as s:
            while True:
                t0 = time.time()
                if not self.session.paused:
                    try:
                        if self.demo:
                            sim["exp"] += np.random.randint(0, 9) if np.random.rand() < 0.2 else 0
                            self.q.put(("read", t0, dict(found=True, level=40, exp=sim["exp"], unknown=False,
                                        pct=round(sim["exp"] / sim["req"] * 100, 2))))
                        else:
                            if loc is None or fails >= 3:      # (re)find the bar: window moved/resized
                                loc, fails, lvl = locate(s), 0, None
                                self.loc = loc
                            if loc is None:
                                self.q.put(("read", t0, dict(NOT_FOUND)))
                                time.sleep(0.5); continue
                            r = ocr.read_strip(grab_array(s, ocr.rel_rect(*loc, ocr.STRIP_REL)))
                            if not r["found"]:
                                fails += 1
                            else:
                                fails = 0
                                wrapped = prev_pct is not None and r["pct"] is not None and prev_pct - r["pct"] > 30
                                if lvl is None or wrapped or t0 - lvl_t > 3:
                                    lvl, lvl_t = ocr.read_level(grab_image(s, ocr.rel_rect(*loc, ocr.LEVEL_REL))), t0
                                if r["pct"] is not None: prev_pct = r["pct"]
                            r["level"] = lvl
                            self.q.put(("read", t0, r))
                    except Exception as ex:
                        self.q.put(("error", str(ex)))
                time.sleep(max(0.0, 1.0 / self.S["reads_per_sec"] - (time.time() - t0)))

    def _name_loop(self):
        """The character name and job now and then (slow-changing, so not part of the fast loop).
        Each is reported once it wins a vote over the last few readings."""
        import mss
        votes, last_loc = {"name": [], "job": []}, None
        with mss.mss() as s:
            while True:
                loc = self.loc
                if loc is None or self.session.paused or self.demo:
                    time.sleep(0.5); continue
                if loc != last_loc:
                    votes, last_loc = {"name": [], "job": []}, loc
                for kind, read, rel in (("name", ocr.read_name, ocr.NAME_REL), ("job", ocr.read_job, ocr.JOB_REL)):
                    try:
                        text = read(grab_image(s, ocr.rel_rect(*loc, rel)))
                    except Exception:
                        continue
                    if text:
                        v = votes[kind] = (votes[kind] + [text])[-5:]
                        top = max(set(v), key=v.count)
                        if v.count(top) >= 2 or len(v) >= 3:
                            self.q.put((kind, top))
                time.sleep(1.0 if len(votes["name"]) < 5 else 15.0)
