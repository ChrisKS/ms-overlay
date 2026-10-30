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

from msoverlay import paths, settings                      # noqa: E402
from msoverlay.settings import GRAPH_MODES, GRAPH_STYLES   # noqa: E402


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA", str(tmp_path))
    from msoverlay.ui import overlay as ov_mod
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
    nb = ov.settings_win.nb
    assert ov.settings_win.exists() and [nb.tab(t, "text") for t in nb.tabs()] == \
        ["General", "Position", "Rates", "Appearance", "Graph", "Data", "Discord"]
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


def test_settings_tabs_keep_their_size_when_selected(overlay):
    """Clicking a tab must not resize it or shift the others."""
    overlay.open_settings()
    nb = overlay.settings_win.nb
    def tab_edges(y):
        overlay.root.update()
        edges, cur = [], None
        for x in range(nb.winfo_width()):
            try: i = nb.index(f"@{x},{y}")
            except tk.TclError: i = None
            if i != cur: edges.append((x, i)); cur = i
        return edges
    layouts = set()
    for i in range(len(nb.tabs())):
        nb.select(i)
        layouts.add((tuple(tab_edges(2)), tuple(tab_edges(16))))   # top edge and middle of the tabs
    assert len(layouts) == 1


def test_update_notice_shows_and_opens_only_the_release_page(overlay, monkeypatch):
    import webbrowser
    from msoverlay.updates import REPO
    opened = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    ov = overlay
    ov.redraw()
    assert not ov.cv.find_withtag("update")
    ov.updates.available = ("v9.9.9", f"https://github.com/{REPO}/releases/tag/v9.9.9")
    ov.redraw(); ov.root.update()
    assert ov.cv.itemcget(ov.cv.find_withtag("update")[-1], "text") == "Update v9.9.9 available"
    x1, y1, x2, y2 = ov.cv.bbox(ov.cv.find_withtag("update")[-1])
    ov.cv.event_generate("<ButtonPress-1>", x=(x1 + x2) // 2, y=(y1 + y2) // 2); ov.root.update()
    assert opened == [f"https://github.com/{REPO}/releases/tag/v9.9.9"]
    ov.S["check_updates"] = False; ov.redraw()                 # turned off: no notice
    assert not ov.cv.find_withtag("update")
    ov.S["check_updates"] = True
    ov.updates.available = ("v9.9.9", "https://example.com/evil")
    ov.open_update()
    assert len(opened) == 1                                     # never a page outside the repository


def test_settings_window_stays_above_the_overlay(overlay):
    ov = overlay
    ov.open_settings()
    sw = ov.settings_win.win
    def on_top():
        for _ in range(3): ov.root.update()
        return not any(int(ov.root.tk.call("wm", "stackorder", str(sw), "isbelow", str(w))) for w in ov.layers)
    assert on_top()
    ov.S["accent"] = "#a78bfa"; ov.apply()          # any settings change
    assert on_top()
    ov.fg.lift(); ov.fix_stack()                     # something else raised the overlay
    assert on_top()


def test_always_on_top_is_only_reapplied_when_it_changes(overlay, monkeypatch):
    ov, calls = overlay, []
    for w in ov.layers:
        orig = w.attributes
        monkeypatch.setattr(w, "attributes", lambda *a, orig=orig: (calls.append(a), orig(*a))[1])
    ov.apply()
    assert not [c for c in calls if c[0] == "-topmost"]
    ov.S["topmost"] = False; ov.apply()
    assert [c for c in calls if c[0] == "-topmost"] == [("-topmost", False)] * 4


def test_text_and_accent_offer_the_same_colours_plus_a_custom_one(overlay, monkeypatch):
    from tkinter import colorchooser
    from msoverlay.settings import COLORS
    ov = overlay
    ov.open_settings()
    picked = iter([((1, 2, 3), "#C0FFEE"), (None, None)])          # a colour, then "Cancel"
    monkeypatch.setattr(colorchooser, "askcolor", lambda **kw: next(picked))
    ov.settings_win.custom_dots["accent"]()
    assert ov.S["accent"] == "#c0ffee" and ov.acc == "#c0ffee"
    ov.settings_win.custom_dots["accent"]()                         # cancelled: unchanged
    assert ov.S["accent"] == "#c0ffee"
    assert set(ov.settings_win.custom_dots) == {"text_color", "accent"}
    assert len(COLORS) == len({c for _, c in COLORS}) and ("White", "#ffffff") in COLORS


def test_rates_and_discord_tabs_share_the_column_slot_rows(overlay):
    ov = overlay
    ov.open_settings()
    sw = ov.settings_win
    def checks(name):
        f = next(sw.nb.nametowidget(t) for t in sw.nb.tabs() if sw.nb.tab(t, "text") == name)
        return [w.cget("text") for w in f.winfo_children() if w.winfo_class() == "TCheckbutton"]
    assert [t for t in checks("Rates") if t.startswith("Column")] == ["Column 1", "Column 2", "Column 3", "Column 4"]
    assert [t for t in checks("Discord") if t.startswith("Item")] == ["Item 1", "Item 2"]



def test_placing_at_corners_and_centre(overlay, monkeypatch):
    from msoverlay.ui import overlay as ov_mod, screens
    ov = overlay
    monkeypatch.setattr(screens, "work_area", lambda root, x, y: (0, 0, 1600, 900))   # one 1600x900 screen
    E, W = ov_mod.EDGE, ov.W
    def at():
        ov.root.update(); return ov.root.winfo_x(), ov.root.winfo_y()
    ov.move(300, 250); at()
    ov.place("c");  assert at() == ((1600 - W) // 2, 250)           # centred across, same height
    ov.place("tl"); assert at() == (E, E)
    ov.place("tr"); assert at() == (1600 - W - E, E)
    ov.place("bc"); assert at() == ((1600 - W) // 2, 900 - ov.height() - E)
    ov.place("br"); assert at() == (1600 - W - E, 900 - ov.height() - E)
    assert (ov.S["x"], ov.S["y"]) == at()                            # remembered
    bottom = at()[1] + ov.height()
    ov.toggle_graph(); x, y = at()                                   # at the bottom: grows upwards
    assert y + ov.height() == bottom and ov.S["graph"]
    ov.toggle_graph(); assert at()[1] + ov.height() == bottom        # and shrinks back down
    ov.place("tl"); ov.toggle_graph()                                # (straight away: no Tk update between)
    assert at() == (E, E)                                            # elsewhere: grows downwards as before
    assert settings.load(paths.data_file("maple_settings.json"))["x"] == E    # the new spot was saved


def test_dragging_the_right_edge_resizes(overlay):
    ov = overlay
    ov.move(100, 100); ov.root.update()
    x_edge = ov.W - 3
    ov.cv.event_generate("<Motion>", x=x_edge, y=60); ov.root.update()
    assert ov.cv.cget("cursor") == "sb_h_double_arrow"
    ov.cv.event_generate("<ButtonPress-1>", x=x_edge, y=60, rootx=100 + x_edge, rooty=160)
    ov.cv.event_generate("<B1-Motion>", x=x_edge - 200, y=60, rootx=100 + x_edge - 200, rooty=160)
    ov.cv.event_generate("<ButtonRelease-1>", x=x_edge - 200, y=60, rootx=100 + x_edge - 200, rooty=160)
    ov.root.update()
    assert ov.W == 580 - 200 and ov.pos == (100, 100)               # narrower, left edge kept
    assert settings.load(paths.data_file("maple_settings.json"))["width"] == 380
    ov.set_width(10); assert ov.W == settings.WIDTH_MIN             # kept within limits
    ov.set_width(10 ** 5); assert ov.W == settings.WIDTH_MAX
    ov.S["lock_position"] = True                                    # locked: no resizing
    ov.cv.event_generate("<Motion>", x=ov.W - 3, y=60); ov.root.update()
    assert ov.cv.cget("cursor") == ""


def test_a_narrow_overlay_fits_everything(overlay):
    ov = overlay
    t = time.time() - 900
    for i in range(61):
        feed(ov, t + i * 15, 40, 1_000_000 + i * 999_999, round((1_000_000 + i * 999_999) / 9e9 * 100, 2))
    ov.S.update(graph=True, name="AVeryLongCharacterName"); ov.resize()
    ov.updates.available = ("v9.9.9", "https://github.com/ChrisKS/ms-overlay/releases/tag/v9.9.9")
    for w in (settings.WIDTH_MIN, 380, 580):
        ov.set_width(w); ov.root.update()
        cv = ov.cv
        texts = [i for i in cv.find_withtag("dyn") if cv.type(i) == "text" and cv.itemcget(i, "fill") != "#000000"]
        inside = all(0 <= cv.bbox(i)[0] and cv.bbox(i)[2] <= ov.W for i in texts)
        assert inside, w                                            # nothing sticks out of the overlay
        header = sorted((cv.bbox(i) for i in texts if cv.bbox(i)[1] < 45), key=lambda b: b[0])
        assert all(a[2] <= b[0] for a, b in zip(header, header[1:])), w   # header items don't overlap
        values = sorted((cv.bbox(i) for i in texts if 80 < cv.bbox(i)[1] < 105), key=lambda b: b[0])
        assert all(a[2] <= b[0] for a, b in zip(values, values[1:])), w   # column values don't overlap
        row = [cv.bbox(i) for i in texts if ov.H < cv.bbox(i)[1] < ov.H + 25]          # graph header line
        pills = [cv.bbox(i) for i in cv.find_withtag("mode_rate")]
        assert all(b[2] <= min(p[0] for p in pills) for b in row if b[0] < min(p[0] for p in pills)), w
