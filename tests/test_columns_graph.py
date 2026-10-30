import pytest

from msoverlay import fmt
from msoverlay.tracker import Tracker
from msoverlay.ui import columns, graph


@pytest.fixture
def session_tracker():
    fmt.set_style("da")
    tr = Tracker()
    t, exp = 0.0, 10_000_000
    for _ in range(2): tr.feed(t, 150, exp, 20.0)
    for _ in range(120):                                   # 20 min: 10.000 EXP every 10 s
        t += 10; exp += 10_000
        for _ in range(2): tr.feed(t, 150, exp, round(exp / 50e6 * 100, 2))
    return tr, t


def test_column_values(session_tracker):
    tr, now = session_tracker
    assert columns.header("exp_h", 900) == "EXP/H · 15M" and columns.header("kills", 0) == "KILLS · SESSION"
    assert columns.value(tr, "exp_h", now, 300) == ("3.600.000", True)
    assert columns.value(tr, "exp_gain", now, 300) == ("+300.000", True)
    assert columns.value(tr, "kills", now, 300) == ("30", True)
    assert columns.value(tr, "avg", now, 300) == ("10.000", True)
    assert columns.value(tr, "pct_h", now, 3600)[1] is False         # an hour window isn't full yet
    eta = fmt.dur(76 / tr.rate(now, 300)[1] * 3600)                       # 76% to go at 7,2%/h
    assert eta.startswith("10:33:") and columns.value(tr, "eta", now, 300, cur_pct=24.0) == (eta, True)
    assert columns.value(tr, "eta", now, 300, cur_pct=None)[0] == fmt.DASH
    assert columns.value(Tracker(), "exp_h", now, 300) is None
    tr.approx = True
    assert columns.value(tr, "exp_h", now, 300)[0] == "~3.600.000"


@pytest.mark.parametrize("style", ["step", "line", "smooth"])
@pytest.mark.parametrize("mode", ["exp", "pct", "rate"])
def test_graph_series(session_tracker, mode, style):
    tr, now = session_tracker
    xs, ys, avg = graph.series(tr, mode, style, 5, now)
    assert len(xs) == len(ys) and xs[0] >= 0 and xs[-1] == pytest.approx(now - tr.t0)
    assert xs == sorted(xs)
    assert (avg is not None) == (mode == "rate")
    if mode == "exp": assert ys[-1] == pytest.approx(tr.cum_exp)
    if mode == "rate": assert ys[-1] == pytest.approx(tr.rate(now, 300)[0], rel=0.02)


def test_graph_series_needs_data():
    assert graph.series(Tracker(), "exp", "step", 5, 0) is None
    assert graph.series(Tracker(), "rate", "line", 5, 0) is None


def test_summary_line(session_tracker):
    tr, now = session_tracker
    assert graph.summary_line(Tracker(), None, 0) == "Waiting for data…"
    eta = fmt.dur(76 / tr.recent_rate(now)[1] * 3600)
    assert graph.summary_line(tr, (150, 1, 24.0), now) == \
        f"20:00  ·  +1.200.000 EXP  ·  +2,40%  ·  level in {eta}"


def test_nice_ticks():
    assert graph.nice_ticks(0, 100) == [0, 25, 50, 75, 100]
    assert graph.nice_ticks(0, 3.4e7)[:3] == [0, 1e7, 2e7]
