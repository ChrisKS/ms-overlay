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

from maplereader import discord, fmt, settings
from maplereader.session import Session


@pytest.fixture
def webhook(monkeypatch):
    """A local server standing in for Discord's webhook endpoint. -> (url, posts)"""
    posts = []
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            posts.append((self.headers["User-Agent"], json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(404 if "/deleted/" in self.path else 204); self.end_headers()
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(discord, "WEBHOOK_RE", re.compile(r"http://127\.0\.0\.1:\d+/api/webhooks/\w+/[\w-]+"))
    yield f"http://127.0.0.1:{srv.server_port}/api/webhooks/123/abc-DEF", posts
    srv.shutdown()


def a_session(minutes=10, lvl=142):
    """A session that has been running for `minutes` minutes of session time."""
    ses = Session()
    t0 = ses.clock() - minutes * 60
    exp = 38_000_000
    for i in range(minutes * 4 + 1):
        r = dict(found=True, unknown=False, level=lvl, exp=exp, pct=round(exp / 40e6 * 100, 2))
        ses.read(t0 + i * 15, r); ses.read(t0 + i * 15, r)
        exp += 25_000
    return ses


def test_post_webhook(webhook):
    url, posts = webhook
    assert discord.post_webhook(url, {"content": "hi"}) is None
    assert posts == [(discord.USER_AGENT, {"content": "hi"})]
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
    up = discord.level_up_message("Mapler", 143, ses, "#5ec8f2")
    assert title(up) == "Mapler reached level 143! \U0001F389" and fields(up)["Session"] == "10:00"
    assert up["embeds"][0]["color"] == 0x5ec8f2
    s = discord.session_summary("Mapler", ses, "#5ec8f2")
    assert title(s) == "Mapler’s session"
    assert fields(s)["EXP gained"] == "+1.000.000" and fields(s)["Kills"] == "40" and fields(s)["Level"] == "142 (97,50%)"
    assert discord.session_summary("Mapler", a_session(minutes=2), "#5ec8f2") is None   # too short
    t = discord.test_message("Mapler", True, False, "#5ec8f2")
    assert fields(t)["Posts"] == "level-ups"


def test_presence_activity():
    fmt.set_style("da")
    ses = a_session()
    act = discord.presence_activity(ses, time.time())
    assert act["details"] == "Lv 142 · 97,50%" and act["state"].startswith("6M EXP/h")
    assert act["timestamps"]["start"] == int(ses.tracker.t0 * 1000)
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
    link, s, notes = link_for(url)
    ses = a_session()
    link.level_up(143, ses); link.level_up(143, ses); link.level_up(142, ses)
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
    link.level_up(143, a_session()); link.session_ended(a_session(), wait=True)
    link.test()
    wait_for(lambda: notes)
    assert len(posts) == 1 and notes == ["Test message sent."]


def test_presence_status_lines():
    link, s, _ = link_for("")
    assert link.presence_status() == "Off."
    s["discord_presence"] = True
    assert link.presence_status().startswith("Paste your Application ID")


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
