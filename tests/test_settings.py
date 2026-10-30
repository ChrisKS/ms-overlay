import json

from maplereader import settings


def test_defaults_are_valid_and_independent_copies():
    a, b = settings.defaults(), settings.defaults()
    assert settings.sanitize(dict(a)) == a
    a["rate_minutes"][0] = 99
    assert b["rate_minutes"][0] == 5 and settings.DEFAULTS["rate_minutes"][0] == 5


def test_sanitize_repairs_bad_values():
    s = settings.sanitize(dict(settings.defaults(), rate_on=[False] * 4, rate_minutes=[5, "x", 9999, -3],
                               rate_kind=["nope"] * 4, accent="red", mode="bogus", font_scale=1.12,
                               reads_per_sec=99, graph_rate_minutes=0, discord_webhook="  url  ", topmost=0))
    assert s["rate_on"] == [True, False, False, False]          # at least one column stays on
    assert s["rate_minutes"] == [5, 15, 720, 0]
    assert s["rate_kind"] == ["exp_h"] * 4
    assert s["accent"] == settings.DEFAULTS["accent"] and s["mode"] == "exp"
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
