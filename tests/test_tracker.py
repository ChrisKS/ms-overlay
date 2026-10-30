import numpy as np
import pytest

from msoverlay.tracker import WHOLE, Tracker, eta_seconds


def feed(tr, t, lvl, exp, pct):
    tr.feed(t, lvl, exp, pct)
    return tr.feed(t, lvl, exp, pct)      # readings count once seen twice in a row


def grind(tr, t, lvl, exp, n, every=10, step=10_000, req=50e6):
    for _ in range(n):
        t += every; exp += step
        feed(tr, t, lvl, exp, round(exp / req * 100, 2))
    return t, exp


def test_a_reading_must_be_seen_twice():
    tr = Tracker()
    assert not tr.feed(0, 100, 1000, 1.0)
    assert tr.feed(0, 100, 1000, 1.0) and tr.t0 == 0
    assert not tr.feed(1, 100, 9999, 1.0)                 # a one-frame misread...
    assert not tr.feed(2, 100, 1000, 1.0)                 # ...is ignored
    assert tr.cum_exp == 0


def test_the_first_gain_starts_the_clock_and_the_second_starts_the_rates():
    tr = Tracker()
    feed(tr, 0, 100, 1_000_000, 2.0)
    feed(tr, 100, 100, 1_010_000, 2.02)                   # first gain: starts the clock...
    assert tr.rate(100, 300) is None and tr.rate(150, 300) is None   # ...but shows nothing, not 0
    feed(tr, 103, 100, 1_020_000, 2.04)                   # second gain: rates appear at once
    assert tr.rate(103, 300)[0] == pytest.approx(10_000 / 3 * 3600)
    assert tr.rate(103, 300)[2] is False                  # (dimmed: far from a full window)


def test_rates_start_at_the_first_gain():
    tr = Tracker()
    feed(tr, 0, 100, 1_000_000, 2.0)
    feed(tr, 600, 100, 1_000_000, 2.0)                    # 10 idle minutes are ignored
    t, _ = grind(tr, 600, 100, 1_000_000, 60)             # 10 min at 3,6M/h
    assert tr.t_first == 610
    eh, ph, full = tr.rate(t, WHOLE)
    assert eh == pytest.approx(3.6e6) and full       # the first gain only starts the clock
    assert tr.rate(t, 300)[0] == pytest.approx(3.6e6) and tr.rate(t, 300)[2]
    assert not tr.rate(t, 3600)[2]                        # an hour window isn't full yet
    assert tr.recent_rate(t)[:2] == tr.rate(t, WHOLE)[:2]   # shorter than 15 min: the whole session
    assert tr.gains(0) == 60 and tr.gains(t - 300) == 30


def test_level_up_is_estimated_from_the_learned_requirement():
    tr = Tracker()
    feed(tr, 0, 100, 9_000_000, 90.0)                     # learns: level 100 needs 10M
    feed(tr, 10, 100, 9_900_000, 99.0)
    assert feed(tr, 20, 101, 200_000, 1.0)
    assert tr.cum_exp == 900_000 + 100_000 + 200_000 and tr.approx
    assert tr.cum_pct == pytest.approx(9.0 + 2.0)   # 90->99%, then 99% -> 101 1%


def test_unexpected_jumps_rebaseline():
    tr = Tracker()
    feed(tr, 0, 100, 1000, 1.0); feed(tr, 10, 100, 2000, 1.1)
    feed(tr, 20, 105, 50, 0.5)                            # misread / de-level: nothing counted
    assert tr.cum_exp == 1000 and tr.last == (105, 50, 0.5)


def test_skip_gap_ignores_what_changed_and_keeps_counting():
    tr = Tracker()
    feed(tr, 0, 100, 1000, 1.0); feed(tr, 10, 100, 2000, 1.1)
    tr.skip_gap()
    assert feed(tr, 20, 100, 900_000, 9.0) and tr.cum_exp == 1000
    feed(tr, 30, 100, 901_000, 9.01)
    assert tr.cum_exp == 2000
    tr.skip_gap()
    assert not feed(tr, 40, 100, 901_000, 9.01)          # nothing changed during the gap...
    feed(tr, 50, 100, 902_000, 9.02)
    assert tr.cum_exp == 3000                             # ...and the next gain still counts


def test_skip_gap_before_the_session_starts_is_dropped():
    tr = Tracker()
    tr.skip_gap()
    feed(tr, 0, 100, 1000, 1.0); feed(tr, 10, 100, 2000, 1.1)
    assert tr.cum_exp == 1000


def test_rate_series_matches_what_rate_said_at_each_moment():
    tr, rng, t, e = Tracker(), np.random.default_rng(3), 1000.0, 0
    feed(tr, t, 100, e, 0.0)
    for _ in range(900):
        t += rng.exponential(3); e += int(rng.integers(500, 900))
        feed(tr, t, 100, e, e / 1e7 * 100)
    for win in (300, 900, WHOLE):
        g, r, a = tr.rate_series(t + 5, win)
        assert r[-1] == pytest.approx(tr.rate(t + 5, win)[0]) and a[-1] == pytest.approx(tr.rate(t + 5, WHOLE)[0])
        for k in (0, 57, 150, 239):
            st = max(tr.t_first, g[k] - win)
            assert r[k] == pytest.approx((tr.value_at(g[k], 1) - tr.value_at(st, 1)) / (g[k] - st) * 3600)
        assert g[0] == pytest.approx(tr.t_first + min(win, 60))
    assert Tracker().rate_series(0, 300) is None


def test_eta_seconds():
    assert eta_seconds(50, 10) == 5 * 3600
    assert eta_seconds(50, 0) is None and eta_seconds(None, 10) is None and eta_seconds(50, None) is None
