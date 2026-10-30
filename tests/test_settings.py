import json

from msoverlay import settings


def test_defaults_are_valid_and_independent_copies():
    a, b = settings.defaults(), settings.defaults()
    assert settings.sanitize(dict(a)) == a
    a["rate_minutes"][0] = 99
    assert b["rate_minutes"][0] == settings.DEFAULTS["rate_minutes"][0] != 99


def test_sanitize_repairs_bad_values():
    s = settings.sanitize(dict(settings.defaults(), rate_on=[False] * 4, rate_minutes=[5, "x", 9999, -3],
                               rate_kind=["nope"] * 4, accent="red", mode="bogus", font_scale=1.12,
                               reads_per_sec=99, graph_rate_minutes=0, discord_webhook="  url  ", topmost=0))
    assert s["rate_on"] == [True, False, False, False]          # at least one column stays on
    assert s["rate_minutes"] == [5, settings.DEFAULTS["rate_minutes"][1], 720, 0]   # "x": that slot's default
    assert s["rate_kind"] == ["exp_h"] * 4
    assert s["accent"] == settings.DEFAULTS["accent"] and s["mode"] == settings.DEFAULTS["mode"]
    assert s["font_scale"] == 1.15 and s["reads_per_sec"] == 20 and s["graph_rate_minutes"] == 1
    assert s["discord_webhook"] == "url" and s["topmost"] is False


def test_load_migrates_old_files_and_ignores_unknown_keys(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"opacity": 0.5, "fill_strength": 0.4, "name": "Mapler", "junk": 1}))
    s = settings.load(p)
    assert (s["bg_opacity"], s["fg_opacity"], s["graph_opacity"]) == (0.5, 0.5, 0.5)
    assert abs(s["fill_opacity"] - 0.6) < 1e-9 and s["name"] == "Mapler" and "junk" not in s


def test_load_survives_missing_or_broken_files(tmp_path):
    assert settings.load(tmp_path / "missing.json") == settings.defaults()
    (tmp_path / "bad.json").write_text("{not json")
    assert settings.load(tmp_path / "bad.json") == settings.defaults()


def test_save_load_round_trip(tmp_path):
    s = settings.defaults(); s.update(name="Mapler", x=10, y=20, accent="#a78bfa")
    settings.save(s, tmp_path / "s.json")
    assert settings.load(tmp_path / "s.json") == s


def test_restore_defaults_keeps_identity_and_connections():
    s = settings.defaults()
    s.update(name="Mapler", x=1, y=2, discord_webhook="w", discord_app_id="1", accent="#a78bfa", graph=True)
    settings.restore_defaults(s)
    assert (s["name"], s["x"], s["y"], s["discord_webhook"], s["discord_app_id"]) == ("Mapler", 1, 2, "w", "1")
    assert s["accent"] == settings.DEFAULTS["accent"] and s["graph"] is False


def test_column_slot_sets_are_validated_alike():
    s = settings.sanitize(dict(settings.defaults(), presence_on=[False, False], presence_minutes=[5],
                               presence_kind=["nope", "kills"]))
    assert s["presence_on"] == [False, False]                    # the presence line may show nothing...
    assert s["presence_minutes"] == settings.DEFAULTS["presence_minutes"]   # ...a malformed list: the defaults
    assert s["presence_kind"] == ["exp_h", "kills"]
    s = settings.sanitize(dict(settings.defaults(), rate_on=[False] * 4))
    assert s["rate_on"][0]                                       # ...but the overlay keeps a column
    assert settings.enabled_columns(settings.defaults(), "rate") == [(0, "exp_gain"), (300, "exp_h"), (1800, "exp_h"), (1800, "eta")]
    assert settings.enabled_columns(settings.defaults(), "presence") == [(0, "exp_gain"), (300, "exp_h")]


def test_the_chosen_defaults():
    """What a fresh install starts with (chosen from the settings window, October 2026)."""
    d = settings.defaults()
    assert (d["topmost"], d["show_name"], d["reset_on_char"], d["check_updates"], d["reads_per_sec"]) == (True, True, True, True, 10)
    assert (d["rate_on"], d["rate_dim"]) == ([True] * 4, True)
    assert (d["text_color"], d["accent"], d["font_scale"], d["text_shadow"]) == ("#5ec8f2", "#5ec8f2", 1.0, True)
    assert (d["bg_opacity"], d["fg_opacity"], d["number_format"]) == (0.85, 1.0, "da")
    assert (d["graph"], d["mode"], d["graph_rate_minutes"], d["graph_avg"], d["graph_style"]) == (False, "rate", 5, True, "line")
    assert (d["graph_width"], d["graph_opacity"], d["graph_fill"], d["fill_opacity"]) == (1, 0.5, True, 0.05)
    assert (d["discord_levelups"], d["discord_screenshot"], d["discord_sessions"], d["discord_presence"]) == (True, False, False, False)
    assert (d["presence_on"], d["presence_minutes"], d["presence_kind"]) == ([True, True], [0, 5], ["exp_gain", "exp_h"])
