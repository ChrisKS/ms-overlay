import pytest

from maplereader import fmt


@pytest.fixture(autouse=True)
def danish():
    fmt.set_style("da")
    yield
    fmt.set_style("da")


@pytest.mark.parametrize("style, n, out", [
    ("da", 1234567, "1.234.567"), ("en", 1234567, "1,234,567"), ("space", 1234567, "1 234 567"),
    ("compact", 1234567, "1.23M"), ("compact", 12345, "12.3k"), ("compact", 999, "999"),
    ("da", 12_500_000, "12,5M"), ("en", 12_500_000, "12.5M"), ("da", -1500, "-1.500"),
])
def test_num(style, n, out):
    fmt.set_style(style)
    assert fmt.num(n) == out


def test_short_and_pct_follow_the_decimal_mark():
    assert fmt.short(1_250_000) == "1,25M" and fmt.short(850_000) == "850k" and fmt.short(0) == "0"
    assert fmt.pct(12.5) == "12,50%"
    fmt.set_style("en")
    assert fmt.short(1_250_000) == "1.25M" and fmt.pct(12.5, 1) == "12.5%"


def test_signed():
    assert fmt.signed(1500) == "+1.500" and fmt.signed(-1500, "~") == "−~1.500"
    assert fmt.signed_pct(2.5) == "+2,50%" and fmt.signed_pct(-0.25) == "−0,25%"


def test_durations():
    assert fmt.dur(59) == "0:59" and fmt.dur(3723) == "1:02:03"
    assert fmt.hours_minutes(5 * 3600 + 7 * 60 + 59) == "5h 07m"
