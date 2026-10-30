"""The status-bar reader against synthetic screenshots drawn with the game's own glyphs."""
import numpy as np
import pytest
from PIL import Image

from maplereader import ocr
from tests.synthetic import status_bar


def strip_of(a, at=(300, 40)):
    left, top, right, bottom = ocr.rel_rect(*at, ocr.STRIP_REL)
    return a[top:bottom, left:right]


@pytest.mark.parametrize("exp, pct, value, percent", [
    ("1,234,567", "12.34%", 1234567, 12.34), ("98,765", "0.05%", 98765, 0.05),
    ("5,550,505", "99.99%", 5550505, 99.99), ("0", "0.00%", 0, 0.0),
])
def test_read_strip(exp, pct, value, percent):
    r = ocr.read_strip(strip_of(status_bar(exp, pct)))
    assert r["found"] and not r["unknown"]
    assert (r["exp"], r["pct"], r["exp_text"], r["pct_text"]) == (value, percent, exp, pct)


def test_find_bars_reports_the_hp_bracket_on_any_screen_position():
    y, xs = ocr.find_bars(status_bar(at=(517, 23), size=(1400, 60)))[0]
    assert y == 23 and xs[:5] == [517, 577, 597, 657, 917] and len(xs) == 6
    assert ocr.find_bars(np.zeros((50, 50, 3), np.uint8)) == []


def test_unknown_glyphs_are_flagged():
    a = status_bar()
    a[40, 300 + ocr.EXP_START + 3] = (255, 255, 255)   # light the blank top-left pixel of the first "1"
    r = ocr.read_strip(strip_of(a))
    assert r["unknown"] and r["exp"] is None and r["exp_text"].startswith("?")


def test_no_status_bar():
    assert not ocr.read_strip(np.zeros((7, 740, 3), np.uint8))["found"]
    assert ocr.read_image(Image.new("RGB", (400, 300))) is None


def test_read_image_reads_the_strip():
    r = ocr.read_image(Image.fromarray(status_bar("4,567", "45.67%")))
    assert (r["exp"], r["pct"]) == (4567, 45.67)
