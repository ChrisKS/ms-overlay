"""Settings: defaults, the choices offered in the settings window, validation, loading and saving.

Settings are a plain dict shared by the whole app; sanitize() keeps every value valid."""
import json
import re

from .paths import data_file

SETTINGS_NAME = "maple_settings.json"

DEFAULTS = dict(
    name="Character", x=None, y=None,
    # general
    topmost=True, lock_position=False, show_name=True, reset_on_char=True, reads_per_sec=10,
    graph=False, mode="exp",
    # graph
    graph_style="step", graph_fill=True, graph_width=2, graph_opacity=1.0, fill_opacity=0.25,
    graph_rate_minutes=5, graph_avg=True,
    # rate columns
    rate_minutes=[5, 15, 30, 60], rate_on=[True, True, True, True],
    rate_kind=["exp_h", "exp_h", "exp_h", "exp_h"], rate_dim=True,
    # appearance
    accent="#5ec8f2", text_color="#ffffff", font_scale=1.0, text_shadow=True,
    bg_opacity=1.0, fg_opacity=1.0, number_format="da",
    # data
    log_csv=True,
    # discord
    discord_webhook="", discord_levelups=True, discord_screenshot=False, discord_sessions=True,
    discord_presence=False, discord_app_id="",
)
# kept by "Restore default settings": not preferences, but who you are and what you connected
KEEP_ON_RESTORE = ("name", "x", "y", "discord_webhook", "discord_app_id")

# what a column can show: key -> (header label, description for the settings list)
KINDS = {
    "exp_h":    ("EXP/H",    "EXP per hour"),
    "exp_gain": ("EXP",      "EXP gained in the window"),
    "pct_h":    ("%/H",      "Level % per hour"),
    "pct_gain": ("% GAINED", "Level % gained in the window"),
    "eta":      ("LEVEL IN", "Time to next level at that pace"),
    "kills":    ("KILLS",    "Number of EXP gains (kills) in the window"),
    "avg":      ("AVG/KILL", "Average EXP per kill"),
}
ACCENTS = [("Sky", "#5ec8f2"), ("Mint", "#5fd38d"), ("Amber", "#e0b34a"), ("Rose", "#ef6a8a"),
           ("Violet", "#a78bfa"), ("Orange", "#f59e57"), ("Silver", "#c9ced8")]
NUMBER_FORMATS = {"da": "1.234.567  (Danish)", "en": "1,234,567  (English)",
                  "space": "1 234 567  (spaces)", "compact": "1.2M  (compact)"}
TEXT_COLORS = [("White", "#ffffff"), ("Soft", "#e3e6ee"), ("Yellow", "#ffe48a"), ("Cyan", "#b3f0ff"),
               ("Mint", "#bff7d6"), ("Pink", "#ffc7dc")]
FONT_SCALES = [("Small", 0.9), ("Normal", 1.0), ("Large", 1.15), ("Extra large", 1.3)]
GRAPH_STYLES = {"step": "Stepped (sharp)", "line": "Straight lines", "smooth": "Smooth curve"}
# what the graph plots: key -> (button label, settings label), in the order the buttons appear
GRAPH_MODES = {"exp": ("EXP", "EXP gained"), "pct": ("%", "% gained"), "rate": ("EXP/H", "EXP per hour")}

_BOOLS = ("topmost", "lock_position", "show_name", "reset_on_char", "graph", "log_csv", "graph_fill",
          "text_shadow", "rate_dim", "graph_avg", "discord_levelups", "discord_screenshot", "discord_sessions",
          "discord_presence")
_TEXTS = ("discord_webhook", "discord_app_id")


def _num(v, lo, hi, default):
    try: v = float(v)
    except (TypeError, ValueError): return default
    return min(max(v, lo), hi)


def _color(v, default):
    return v if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v) else default


def _four(v, default):
    """one of the per-column lists, or the default if it isn't a list of four"""
    return v if isinstance(v, list) and len(v) == 4 else default


def sanitize(s):
    """Make every value valid (in place) and return the same dict."""
    d = DEFAULTS
    s["rate_minutes"] = [int(_num(x, 0, 720, d["rate_minutes"][i])) for i, x in enumerate(_four(s.get("rate_minutes"), d["rate_minutes"]))]
    s["rate_on"] = [bool(x) for x in _four(s.get("rate_on"), d["rate_on"])]
    if not any(s["rate_on"]): s["rate_on"][0] = True
    s["rate_kind"] = [k if k in KINDS else "exp_h" for k in _four(s.get("rate_kind"), d["rate_kind"])]
    s["bg_opacity"] = _num(s.get("bg_opacity"), 0.0, 1.0, 1.0)
    s["fg_opacity"] = _num(s.get("fg_opacity"), 0.2, 1.0, 1.0)
    s["reads_per_sec"] = int(_num(s.get("reads_per_sec"), 2, 20, 10))
    if s.get("number_format") not in NUMBER_FORMATS: s["number_format"] = "da"
    s["accent"] = _color(s.get("accent"), d["accent"])
    s["text_color"] = _color(s.get("text_color"), d["text_color"])
    if s.get("mode") not in GRAPH_MODES: s["mode"] = "exp"
    s["graph_rate_minutes"] = int(_num(s.get("graph_rate_minutes"), 1, 60, 5))
    if s.get("graph_style") not in GRAPH_STYLES: s["graph_style"] = "step"
    s["graph_opacity"] = _num(s.get("graph_opacity"), 0.0, 1.0, 1.0)
    s["fill_opacity"] = _num(s.get("fill_opacity"), 0.0, 1.0, 0.25)
    s["graph_width"] = int(_num(s.get("graph_width"), 1, 4, 2))
    fs = _num(s.get("font_scale"), 0.8, 1.5, 1.0)
    s["font_scale"] = min((v for _, v in FONT_SCALES), key=lambda v: abs(v - fs))
    for k in _BOOLS:
        s[k] = bool(s.get(k, d[k]))
    for k in _TEXTS:
        s[k] = str(s.get(k) or "").strip()[:300]
    return s


def defaults():
    """A fresh copy of the defaults (the per-column lists are copied too)."""
    return {k: list(v) if isinstance(v, list) else v for k, v in DEFAULTS.items()}


def restore_defaults(s):
    """Reset `s` in place to the defaults, keeping KEEP_ON_RESTORE."""
    keep = {k: s[k] for k in KEEP_ON_RESTORE}
    s.clear(); s.update(defaults()); s.update(keep)
    return s


def load(path=None):
    s = defaults()
    try:
        with open(path or data_file(SETTINGS_NAME), encoding="utf-8") as f:
            raw = json.load(f)
        if "opacity" in raw:                       # older versions had one opacity for everything
            raw.setdefault("bg_opacity", raw["opacity"]); raw.setdefault("fg_opacity", raw["opacity"])
            raw.setdefault("graph_opacity", raw["opacity"])
        if "fill_strength" in raw:                 # renamed: "fill strength" -> "fill opacity"
            raw.setdefault("fill_opacity", min(1.0, raw["fill_strength"] * 1.5))
        s.update({k: v for k, v in raw.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return sanitize(s)


def save(s, path=None):
    """Write the settings; failing (read-only folder, ...) is ignored."""
    try:
        with open(path or data_file(SETTINGS_NAME), "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass
