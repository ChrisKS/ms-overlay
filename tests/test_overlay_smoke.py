"""Builds the real overlay and settings window and drives them a little. Needs Tk and a display
(locally: xvfb-run -a pytest); skipped otherwise."""
import os
import time

import pytest

tk = pytest.importorskip("tkinter")
try:
    tk.Tk().destroy()
except tk.TclError:
    pytest.skip("no display", allow_module_level=True)

from maplereader import paths, settings                      # noqa: E402
from maplereader.settings import GRAPH_MODES, GRAPH_STYLES   # noqa: E402


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA", str(tmp_path))
    from maplereader.ui import overlay as ov_mod
    monkeypatch.setattr(ov_mod, "POLL_MS", 10 ** 9)          # the test calls poll() itself
    ov = ov_mod.Overlay(demo=False)
    yield ov
    try: ov.root.destroy()
    except tk.TclError: pass


def feed(ov, t, lvl, exp, pct):
    for _ in range(2):
        ov.q.put(("read", t, dict(found=True, unknown=False, level=lvl, exp=exp, pct=pct)))
    ov.poll()


def test_overlay_draws_a_session_in_every_graph_mode(overlay, tmp_path):
    ov = overlay
    ov.S["graph"] = True; ov.resize()
    t = time.time() - 600
    for i in range(41):
        feed(ov, t + i * 15, 142, 38_000_000 + i * 25_000, round((38_000_000 + i * 25_000) / 40e6 * 100, 2))
    for mode in GRAPH_MODES:
        for style in GRAPH_STYLES:
            ov.S.update(mode=mode, graph_style=style); ov.redraw()
            assert ov.linecv.find_all(), (mode, style)            # a line was drawn
    assert os.path.exists(tmp_path / "maple_log.csv")


def test_graph_buttons_switch_the_mode(overlay):
    ov = overlay
    ov.S["graph"] = True; ov.resize(); ov.redraw(); ov.root.update()
    for k in GRAPH_MODES:
        x1, y1, x2, y2 = ov.cv.bbox(ov.cv.find_withtag(f"mode_{k}")[0])
        ov.cv.event_generate("<ButtonPress-1>", x=(x1 + x2) // 2, y=(y1 + y2) // 2); ov.root.update()
        assert ov.S["mode"] == k


def test_settings_window_opens_and_restores_defaults(overlay, tmp_path):
    ov = overlay
    ov.open_settings()
    assert ov.settings_win.exists() and len(ov.settings_win.nb.tabs()) == 6
    ov.S["accent"] = "#a78bfa"; ov.S["discord_webhook"] = "keep-me"
    ov.restore_defaults()
    assert ov.S["accent"] == settings.DEFAULTS["accent"] and ov.S["discord_webhook"] == "keep-me"
    assert ov.settings_win.exists()
    assert settings.load(tmp_path / "maple_settings.json")["accent"] == settings.DEFAULTS["accent"]


def test_pause_and_reset_from_the_menu_actions(overlay):
    ov = overlay
    t = time.time() - 60
    feed(ov, t, 142, 1000, 1.0); feed(ov, t + 10, 142, 2000, 1.01)
    ov.toggle_pause(); assert ov.session.state == "paused"
    ov.toggle_pause(); ov.reset()
    assert ov.session.tracker.t0 is None
