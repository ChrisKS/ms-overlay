"""Number, percentage and duration formatting. Numbers follow the "number format" setting, which
the overlay applies with set_style()."""

DASH = "—"           # shown where there is no value yet
MINUS = "−"

_style = "da"


def set_style(style):
    """'da' (1.234.567 / 12,5%), 'en' (1,234,567), 'space' (1 234 567) or 'compact' (1.2M)."""
    global _style
    _style = style


def _decimal(t):
    return t.replace(".", ",") if _style == "da" else t


def num(n):
    """A whole number with thousands separators; shortened to M from 10 million (or always, in the
    compact style)."""
    n = int(round(n)); neg, a = n < 0, abs(n)
    if _style == "compact" or a >= 10_000_000:
        if a >= 1_000_000: t = f"{a / 1e6:.2f}".rstrip("0").rstrip(".") + "M"
        elif a >= 10_000 and _style == "compact": t = f"{a / 1e3:.1f}".rstrip("0").rstrip(".") + "k"
        else: t = str(a)
        t = _decimal(t)
    else:
        t = f"{a:,}".replace(",", {"da": ".", "en": ",", "space": " "}.get(_style, "."))
    return ("-" if neg else "") + t


def short(n):
    """Compact number for tight spots like axis labels: 850k, 1,25M."""
    a = abs(n)
    if a >= 1e6: t = f"{a / 1e6:.2f}".rstrip("0").rstrip(".") + "M"
    elif a >= 1e4: t = f"{a / 1e3:.0f}k"
    else: t = str(int(round(a)))
    return ("-" if n < 0 else "") + _decimal(t)


def pct(v, nd=2):
    return _decimal(f"{v:.{nd}f}") + "%"


def signed(n, approx=""):
    """+1.234 / −1.234; `approx` ("~") goes between the sign and the number."""
    return ("+" if n >= 0 else MINUS) + approx + num(abs(n))


def signed_pct(v, nd=2):
    return ("+" if v >= 0 else MINUS) + pct(abs(v), nd)


def dur(sec):
    """1:02:03, or 2:03 under an hour."""
    sec = int(sec); h, r = divmod(sec, 3600); m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def hours_minutes(sec):
    """5h 07m: for times that don't need seconds."""
    m = int(sec // 60)
    return f"{m // 60}h {m % 60:02d}m"
