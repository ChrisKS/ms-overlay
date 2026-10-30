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
