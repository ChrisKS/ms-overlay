import sys

import pytest
from PIL import Image

from msoverlay import gamewindow


def test_blank_pictures_are_rejected():
    assert gamewindow.is_blank(Image.new("RGB", (50, 50), "black"))
    assert gamewindow.is_blank(Image.new("RGB", (50, 50), (40, 41, 42)))
    img = Image.new("RGB", (50, 50), "black"); img.putpixel((3, 3), (200, 180, 20))
    assert not gamewindow.is_blank(img)


def test_capture_never_returns_a_blank_picture(monkeypatch):
    name = {"win32": "_capture_windows", "darwin": "_capture_mac"}.get(sys.platform)
    if name is None:
        pytest.skip("no game-window capture on this platform")
    monkeypatch.setattr(gamewindow, name, lambda: Image.new("RGB", (800, 600), "black"))
    assert gamewindow.capture() is None


def test_capture_fails_closed(monkeypatch):
    """No game window, an error, or an unsupported platform: no picture, never the screen."""
    def boom(): raise OSError("access denied")
    monkeypatch.setattr(gamewindow, "_capture_windows", boom)
    monkeypatch.setattr(gamewindow, "_capture_mac", boom)
    assert gamewindow.capture() is None
    if sys.platform not in ("win32", "darwin"):
        monkeypatch.undo()
        assert gamewindow.capture() is None


def test_jpeg():
    data = gamewindow.as_jpeg(Image.new("RGB", (16, 16), "white"))
    assert data[:2] == b"\xff\xd8"


def win(**kw):
    d = dict(hwnd=1, title="", cls="", exe="", w=1280, h=720, minimized=False)
    d.update(kw); return d


@pytest.fixture
def windows(monkeypatch):
    """Simulated Windows windows: set .list; .printed records which window got drawn."""
    class State: list = []; printed = []; refuse = False; black = False
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(gamewindow, "_windows_list", lambda: State.list)
    def no_graphics_capture(game): raise OSError("not available")      # these tests: the PrintWindow path
    monkeypatch.setattr(gamewindow, "_graphics_capture", no_graphics_capture)
    def teal(hwnd, w, h, flags):
        State.printed.append(hwnd)
        if State.refuse: return None
        img = Image.new("RGB", (w, h), "black")
        if not State.black: img.putpixel((1, 1), (0, 128, 128))
        return img
    monkeypatch.setattr(gamewindow, "_print_window", teal)
    return State


def test_the_game_is_found_by_process_or_by_window_class(windows):
    windows.list = [win(hwnd=1, title="MapleStory wiki - Browser", exe="browser.exe"),
                    win(hwnd=2, cls="MapleStoryClass", exe="")]            # process name refused
    assert gamewindow.capture() is not None and windows.printed[-1] == 2
    windows.list = [win(hwnd=3, exe="maplestory.exe", cls="Other")]
    assert gamewindow.capture() is not None and windows.printed[-1] == 3


def test_a_window_merely_titled_maplestory_is_never_captured(windows):
    windows.list = [win(hwnd=1, title="MapleStory", exe="chrome.exe", cls="Chrome_WidgetWin_1")]
    assert gamewindow.capture() is None and not windows.printed
    assert gamewindow.last_problem == "no MapleStory window was found"


@pytest.mark.parametrize("setup, problem", [
    (dict(list=[win(cls="MapleStoryClass", minimized=True)]), "the MapleStory window is minimised"),
    (dict(list=[win(cls="MapleStoryClass")], refuse=True),
     "Windows wouldn't let ms-overlay capture the MapleStory window (Graphics Capture: not available)"),
    (dict(list=[win(cls="MapleStoryClass")], black=True), "the MapleStory window came back black"),
])
def test_each_failed_step_is_named(windows, setup, problem):
    for k, v in setup.items(): setattr(windows, k, v)
    assert gamewindow.capture() is None and gamewindow.last_problem.startswith(problem)


def test_the_largest_game_window_is_used(windows):
    windows.list = [win(hwnd=1, cls="MapleStoryClass", w=200, h=100), win(hwnd=2, cls="MapleStoryClass", w=1920, h=1080)]
    assert gamewindow.capture().size == (1920, 1080)


def test_candidates_list_maple_windows_only(windows):
    windows.list = [win(title="MapleStory", cls="MapleStoryClass", exe=""), win(title="Notepad", exe="notepad.exe")]
    lines = gamewindow.candidates()
    assert len(lines) == 1 and "process=(access denied)" in lines[0] and "game=True" in lines[0]



@pytest.fixture
def graphics_capture(monkeypatch):
    """The real Graphics Capture path, with a stand-in for the windows-capture package that follows
    its API (event handlers; start_free_threaded() delivers BGRA frames on another thread), and a
    simulated window list. Set .frame to the BGRA array to deliver, or None for no frames."""
    import threading
    import types
    import numpy as np
    class Control:
        stopped = False
        def stop(self): self.stopped = True
        def is_finished(self): return self.stopped
    class WindowsCapture:
        created, frame, printed = [], None, []
        def __init__(self, **kw): WindowsCapture.created.append(kw)
        def event(self, fn): setattr(self, fn.__name__, fn); return fn
        def start_free_threaded(self):
            c = Control()
            if WindowsCapture.frame is not None:
                f = types.SimpleNamespace(frame_buffer=WindowsCapture.frame)
                threading.Thread(target=self.on_frame_arrived, args=(f, c)).start()
            return c
    mod = types.ModuleType("windows_capture"); mod.WindowsCapture = WindowsCapture
    monkeypatch.setitem(sys.modules, "windows_capture", mod)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(gamewindow, "_windows_list", lambda: [win(hwnd=7, cls="MapleStoryClass", w=160, h=90)])
    def drawn(hwnd, w, h, flags):
        WindowsCapture.printed.append(hwnd)
        img = Image.new("RGB", (w, h)); img.putpixel((1, 1), (9, 9, 9)); return img
    monkeypatch.setattr(gamewindow, "_print_window", drawn)
    bgra = np.zeros((90, 160, 4), np.uint8); bgra[..., 0] = 200; bgra[..., 2] = 10   # blue in BGRA order,
    bgra[50:60, 50:60, 1] = 255                                                       # with some detail
    WindowsCapture.frame = bgra
    return WindowsCapture


def test_graphics_capture_comes_first_and_gives_rgb(graphics_capture):
    img = gamewindow.capture()
    assert img.size == (160, 90) and img.getpixel((0, 0)) == (10, 0, 200)
    assert graphics_capture.created == [dict(cursor_capture=False, draw_border=False, window_hwnd=7)]
    assert graphics_capture.printed == []                       # the fallback wasn't needed


def test_no_frame_falls_back_to_drawing_the_window(graphics_capture, monkeypatch):
    graphics_capture.frame = None
    real = gamewindow._graphics_capture
    monkeypatch.setattr(gamewindow, "_graphics_capture", lambda game: real(game, timeout=0.1))
    assert gamewindow.capture() is not None and graphics_capture.printed == [7]


def test_graphics_capture_works_again_after_the_first(graphics_capture, monkeypatch):
    monkeypatch.delitem(sys.modules, "cv2", raising=False)
    assert gamewindow.capture() is not None and gamewindow.capture() is not None
    assert graphics_capture.printed == [] and len(graphics_capture.created) == 2
