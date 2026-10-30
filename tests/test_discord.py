"""Webhook posts against a local fake webhook, Rich Presence against a fake Discord desktop app."""
import json
import os
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from msoverlay import discord, fmt, settings
from msoverlay.session import Session


def parse_post(content_type, body):
    """-> (message, attached image bytes or None), for JSON and multipart posts alike"""
    if content_type == "application/json":
        return json.loads(body), None
    from email.parser import BytesParser
    msg = BytesParser().parsebytes(b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body)
    parts = {p.get_param("name", header="content-disposition"): p for p in msg.get_payload()}
    assert parts["files[0]"].get_filename() == discord.IMAGE_NAME
    return json.loads(parts["payload_json"].get_payload(decode=True)), parts["files[0]"].get_payload(decode=True)


@pytest.fixture
def webhook(monkeypatch):
    """A local server standing in for Discord's webhook endpoint. -> (url, posts)"""
    posts = []
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            payload, image = parse_post(self.headers["Content-Type"], body)
            posts.append((self.headers["User-Agent"], payload, image))
            self.send_response(404 if "/deleted/" in self.path else 204); self.end_headers()
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(discord, "WEBHOOK_RE", re.compile(r"http://127\.0\.0\.1:\d+/api/webhooks/\w+/[\w-]+"))
    yield f"http://127.0.0.1:{srv.server_port}/api/webhooks/123/abc-DEF", posts
    srv.shutdown()


def a_session(minutes=10, lvl=142):
    """A session that has been running for `minutes` minutes of session time. `ses.now` is the
    moment of its last reading: evaluate at that time for results that don't depend on how
    fast the test runs."""
    ses = Session()
    ses.now = time.time()
    t0 = ses.now - minutes * 60
    exp = 38_000_000
    for i in range(minutes * 4 + 1):
        r = dict(found=True, unknown=False, level=lvl, exp=exp, pct=round(exp / 40e6 * 100, 2))
        ses.read(t0 + i * 15, r); ses.read(t0 + i * 15, r)
        exp += 25_000
    return ses


def test_post_webhook(webhook):
    url, posts = webhook
    assert discord.post_webhook(url, {"content": "hi"}) is None
    assert posts == [(discord.USER_AGENT, {"content": "hi"}, None)]
    assert discord.post_webhook(url, {"content": "pic"}, image=b"\xff\xd8jpeg") is None
    assert posts[1] == (discord.USER_AGENT, {"content": "pic"}, b"\xff\xd8jpeg")
    assert discord.post_webhook(url.replace("/123/", "/deleted/"), {}) == "the webhook was deleted"
    assert discord.post_webhook("https://example.com/hook", {}) == "that isn't a Discord webhook URL"


def test_real_discord_urls_are_accepted():
    for u in ("https://discord.com/api/webhooks/1/a-b_c", "https://ptb.discordapp.com/api/webhooks/2/x"):
        assert discord.WEBHOOK_RE.fullmatch(u)


def test_messages():
    fmt.set_style("da")
    ses = a_session()
    title = lambda m: m["embeds"][0]["title"]
    fields = lambda m: {f["name"]: f["value"] for f in m["embeds"][0]["fields"]}
    up = discord.level_up_message("Mapler", "Hero", 143, "#5ec8f2")
    assert title(up) == "Mapler (Hero) reached level 143! \U0001F389" and fields(up) == {}
    assert up["embeds"][0]["color"] == 0x5ec8f2
    assert title(discord.level_up_message("Mapler", None, 143, "#5ec8f2")) == "Mapler reached level 143! \U0001F389"
    s = discord.session_summary("Mapler", ses, "#5ec8f2")
    assert title(s) == "Mapler’s session"
    assert fields(s)["EXP gained"] == "+1.000.000" and fields(s)["Kills"] == "40" and fields(s)["Level"] == "142 (97,50%)"
    assert discord.session_summary("Mapler", a_session(minutes=2), "#5ec8f2") is None   # too short
    t = discord.test_message("Mapler", True, False, "#5ec8f2")
    assert fields(t)["Posts"] == "level-ups"


def test_presence_activity():
    fmt.set_style("da")
    ses = a_session()
    act = discord.presence_activity(ses, ses.now)
    assert act["details"] == "Lv 142 · 97,50%" and act["state"].startswith("EXP/H 6.000.000 · LEVEL IN ")
    assert act["timestamps"]["start"] == int(ses.tracker.t0 * 1000)
    act = discord.presence_activity(ses, ses.now, [(300, "kills"), (0, "pct_gain")])   # chosen columns
    assert act["state"] == "KILLS 20 · % GAINED +2,44%"      # (the first gain only starts the clock)
    assert "state" not in discord.presence_activity(ses, ses.now, [])                  # none chosen
    assert discord.presence_activity(Session(), time.time()) is None
    ses.toggle_pause()
    act = discord.presence_activity(ses, time.time())
    assert act["state"] == "Paused" and "timestamps" not in act
    assert discord.presence_activity(Session(), time.time()) is None


def link_for(url, **kw):
    s = settings.defaults(); s.update(name="Mapler", discord_webhook=url, **kw)
    notes = []
    return discord.DiscordLink(s, notes.append), s, notes


def wait_for(cond, timeout=5):
    end = time.time() + timeout
    while not cond() and time.time() < end: time.sleep(0.02)
    assert cond()


def test_link_posts_level_ups_once_and_summaries(webhook):
    url, posts = webhook
    link, s, notes = link_for(url, discord_sessions=True)
    ses = a_session()
    link.level_up(143, "Hero"); link.level_up(143, "Hero"); link.level_up(142)
    wait_for(lambda: len(posts) == 1)
    assert "reached level 143" in posts[0][1]["embeds"][0]["title"] and notes[0].startswith("Last post")
    link.session_ended(ses, wait=True)
    assert len(posts) == 2 and posts[1][1]["embeds"][0]["title"] == "Mapler’s session"
    s["discord_sessions"] = False
    link.session_ended(ses, wait=True)
    assert len(posts) == 2


def test_link_in_demo_mode_only_sends_the_test(webhook):
    url, posts = webhook
    s = settings.defaults(); s.update(discord_webhook=url)
    notes = []
    link = discord.DiscordLink(s, notes.append, posts=False)
    link.level_up(143); link.session_ended(a_session(), wait=True)
    link.test()
    wait_for(lambda: notes)
    assert len(posts) == 1 and notes == ["Test message sent."]


def test_presence_status_lines():
    link, s, _ = link_for("")
    assert link.presence_status() == "Off."
    s["discord_presence"] = True
    assert link.app_id() == discord.APP_ID and link.presence_on()          # works without any setup
    s["discord_app_id"] = "123"
    assert link.app_id() == "123"
    s.update(presence_on=[False, True], presence_kind=["exp_h", "kills"], presence_minutes=[15, 5])
    assert settings.enabled_columns(s, "presence") == [(300, "kills")]   # what the presence line shows
    s["discord_app_id"] = "my app"
    assert not link.presence_on() and link.presence_status().startswith("That Application ID isn't valid")


@pytest.mark.skipif(sys.platform == "win32", reason="the fake Discord app uses a Unix socket")
def test_presence_talks_discords_ipc_protocol(tmp_path, monkeypatch):
    sock_dir = tmp_path / "ipc"; sock_dir.mkdir()
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("TMPDIR", str(sock_dir))
    frames = []
    ls = socket.socket(socket.AF_UNIX); ls.bind(str(sock_dir / "discord-ipc-0")); ls.listen(1)
    def fake_discord():
        c, _ = ls.accept()
        def rd(n):
            b = b""
            while len(b) < n:
                x = c.recv(n - len(b))
                if not x: raise EOFError
                b += x
            return b
        try:
            while True:
                h = rd(8); op = int.from_bytes(h[:4], "little")
                msg = json.loads(rd(int.from_bytes(h[4:], "little"))); frames.append((op, msg))
                rep = {"evt": "READY"} if op == 0 else {"cmd": msg["cmd"], "evt": None}
                d = json.dumps(rep).encode(); c.sendall((1).to_bytes(4, "little") + len(d).to_bytes(4, "little") + d)
        except EOFError:
            c.close()
    threading.Thread(target=fake_discord, daemon=True).start()
    p = discord.Presence(); p.INTERVAL = 0.05
    p.set("1234", {"details": "Lv 1"})
    wait_for(lambda: p.status == "connected" and len(frames) >= 2)
    assert frames[0] == (0, {"v": 1, "client_id": "1234"})
    assert frames[1][1]["cmd"] == "SET_ACTIVITY" and frames[1][1]["args"]["activity"] == {"details": "Lv 1"}
    assert frames[1][1]["args"]["pid"] == os.getpid()
    p.set(None, None)
    wait_for(lambda: p.status == "off")


def test_presence_reports_when_discord_is_not_running(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    if sys.platform == "win32":
        pytest.skip("can't hide a running Discord's named pipe")
    p = discord.Presence(); p.INTERVAL = 0.05
    p.set("1234", {"details": "x"})
    wait_for(lambda: p.status == "Discord isn't running")


def test_screenshots_are_attached_only_when_turned_on_and_captured(webhook, monkeypatch):
    from PIL import Image
    url, posts = webhook
    monkeypatch.setattr(discord, "SCREENSHOT_DELAY", 0)
    shots = []
    monkeypatch.setattr(discord.gamewindow, "capture", lambda: shots.append(1) or Image.new("RGB", (64, 36), "teal"))
    link, s, notes = link_for(url)
    link.level_up(150)                                          # off by default: nothing captured
    wait_for(lambda: len(posts) == 1)
    assert posts[0][2] is None and not shots and "image" not in posts[0][1]["embeds"][0]
    s["discord_screenshot"] = True
    link.level_up(151, "Hero")
    wait_for(lambda: len(posts) == 2)
    img = Image.open(__import__("io").BytesIO(posts[1][2]))
    assert img.format == "JPEG" and img.size == (64, 36)
    assert posts[1][1]["embeds"][0]["image"] == {"url": "attachment://" + discord.IMAGE_NAME}
    def fail():
        discord.gamewindow.last_problem = "no MapleStory window was found"
    monkeypatch.setattr(discord.gamewindow, "capture", fail)   # game window not capturable
    link.level_up(152)
    wait_for(lambda: len(posts) == 3 and len(notes) == 3)
    assert posts[2][2] is None and "image" not in posts[2][1]["embeds"][0]
    assert notes[-1].endswith("(no screenshot: no MapleStory window was found)")


def test_test_message_previews_the_screenshot(webhook, monkeypatch):
    from PIL import Image
    url, posts = webhook
    monkeypatch.setattr(discord.gamewindow, "capture", lambda: Image.new("RGB", (8, 8), "red"))
    link, s, notes = link_for(url, discord_screenshot=True)
    link.test()
    wait_for(lambda: notes)
    assert posts[0][2] is not None and notes == ["Test message sent."]


def test_session_summaries_are_off_by_default(webhook):
    url, posts = webhook
    link, s, notes = link_for(url)
    link.session_ended(a_session(), wait=True)
    assert not posts
