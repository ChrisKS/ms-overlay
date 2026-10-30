"""The session clock and what the session reports, driven with a fake wall clock."""
import pytest

from msoverlay import session as session_mod
from msoverlay.session import FAIL_AFTER, Session, different_character
from msoverlay.tracker import WHOLE


class Clock:
    def __init__(self): self.t = 1_000_000.0
    def time(self): return self.t
    def __getattr__(self, k): return getattr(__import__("time"), k)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(session_mod, "time", c)
    return c


def ok(lvl, exp, pct):
    return dict(found=True, unknown=False, level=lvl, exp=exp, pct=pct)


class Player:
    """Feeds a session like the reader does: every reading arrives twice."""
    def __init__(self, ses, clock, lvl=150, exp=10_000_000):
        self.ses, self.clock, self.lvl, self.exp = ses, clock, lvl, exp

    def read(self):
        r = None
        for _ in range(2):
            r = self.ses.read(self.clock.t, ok(self.lvl, self.exp, round(self.exp / 50e6 * 100, 2)))
        return r

    def grind(self, minutes, step=10_000):
        for _ in range(minutes * 6):
            self.clock.t += 10; self.exp += step; self.read()


def test_pause_works_like_a_stopwatch(clock):
    ses = Session(); p = Player(ses, clock); tr = ses.tracker
    p.read(); p.grind(10)                                       # 10 min at 3,6M/h
    before = (tr.rate(ses.clock(), 300)[0], tr.rate(ses.clock(), WHOLE)[0], tr.cum_exp)
    ses.toggle_pause(); assert ses.state == "paused"
    clock.t += 1800                                             # 30 min paused...
    assert (tr.rate(ses.clock(), 300)[0], tr.rate(ses.clock(), WHOLE)[0]) == before[:2]
    assert ses.clock() - tr.t0 == 600
    ses.toggle_pause(); assert ses.state == "wait"
    p.exp += 5_000_000; p.read()                                # ...while still playing
    assert tr.cum_exp == before[2]
    clock.t += 10; p.exp += 10_000; p.read()
    assert tr.cum_exp == before[2] + 10_000
    assert tr.rate(ses.clock(), 300)[0] == pytest.approx(3.6e6)
    p.grind(10)
    assert tr.rate(ses.clock(), WHOLE)[0] == pytest.approx(3.6e6)
    assert ses.clock() - tr.t0 == pytest.approx(1210)


def test_level_up_while_paused_is_reported_but_not_counted(clock):
    ses = Session(); p = Player(ses, clock); tr = ses.tracker
    p.read(); p.grind(1)
    gained = tr.cum_exp
    ses.toggle_pause(); clock.t += 600; ses.toggle_pause()
    p.lvl, p.exp = 151, 1_500_000
    assert p.read() == (True, 151)
    assert tr.cum_exp == gained


def test_reset_while_paused_then_resume(clock):
    ses = Session(); p = Player(ses, clock)
    p.read(); p.grind(1)
    ses.toggle_pause(); ses.reset(); clock.t += 100; ses.toggle_pause()
    p.read(); clock.t += 10; p.exp += 10_000; p.read()
    assert ses.tracker.cum_exp == 10_000 and ses.clock() - ses.tracker.t0 == pytest.approx(10)


def test_level_ups_are_reported_only_when_they_start_low(clock):
    ses = Session(); p = Player(ses, clock, lvl=150, exp=49_000_000)
    p.read()
    p.lvl, p.exp = 151, 100_000
    assert p.read() == (True, 151)
    ses2 = Session(); q = Player(ses2, clock, lvl=150, exp=10_000_000)
    q.read()
    q.lvl, q.exp = 151, 40_000_000                              # 80%: a misread, not a level-up
    assert q.read() == (True, None)


def test_failures_show_after_a_few_reads(clock):
    ses = Session()
    for i in range(FAIL_AFTER - 1):
        ses.read(clock.t, dict(found=False))
    assert ses.state == "wait"
    ses.read(clock.t, dict(found=False))
    assert ses.state == "bad" and ses.hint == "status bar not found"
    ses.read(clock.t, dict(found=True, unknown=True))
    assert ses.hint == "unreadable digit"
    ses.read(clock.t, ok(150, None, 1.0))
    assert ses.hint == "can't read status bar"
    ses.read(clock.t, ok(150, 1000, 1.0))
    assert ses.state == "ok" and ses.hint == "" and ses.fails == 0
    ses.capture_error()
    assert ses.state == "bad" and ses.hint == "capture error"


def test_recently_read(clock):
    ses = Session()
    assert not ses.recently_read(clock.t)
    ses.read(clock.t, ok(150, 1000, 1.0))
    for _ in range(FAIL_AFTER): ses.read(clock.t, dict(found=False))
    assert ses.recently_read(clock.t + 59) and not ses.recently_read(clock.t + 61)
    ses.toggle_pause()
    assert ses.recently_read(clock.t + 3600)


def test_different_character():
    assert different_character("Mapler", "Zzyzx")
    assert not different_character("Mapler", "MapIer")         # one OCR-misread letter
