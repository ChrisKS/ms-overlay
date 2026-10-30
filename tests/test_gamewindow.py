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
    (dict(list=[win(cls="MapleStoryClass")], refuse=True), "Windows wouldn't let ms-overlay draw the MapleStory window"),
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
