"""Discord: posts to a channel through a webhook, and Rich Presence on the user's profile.

The message builders are plain functions of the session; DiscordLink applies the settings and does
the sending."""
import json
import os
import re
import sys
import threading
import time
import uuid

from . import fmt, gamewindow
from .tracker import WHOLE, eta_seconds

USER_AGENT = "ms-overlay (https://github.com/ChrisKS/ms-overlay)"
WEBHOOK_RE = re.compile(r"https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+")
# ms-overlay's own Discord application: what profiles show after "Playing" (not a secret; every
# Rich Presence app ships its ID). A user can set their own in the settings instead.
APP_ID = "1565725885989003434"
SUMMARY_MIN = 300                # a session needs this many seconds since its first EXP gain to be posted
SCREENSHOT_DELAY = 1.0           # seconds after a level-up before the game is captured (the effect shows)
IMAGE_NAME = "maplestory.jpg"


# ------------------------------------------------------------------ sending


def post_webhook(url, payload, timeout=10, image=None):
    """POST one message to a Discord webhook, with `image` (JPEG bytes) attached if given; the
    message can show it with attachment://IMAGE_NAME. -> None if it was sent, else a short reason."""
    import urllib.error
    import urllib.request
    if not WEBHOOK_RE.fullmatch(url or ""):
        return "that isn't a Discord webhook URL"
    if image is None:
        body, kind = json.dumps(payload).encode(), "application/json"
    else:                                         # multipart: the message as JSON, then the file
        b = uuid.uuid4().hex
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                f"Content-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n"
                f"--{b}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"{IMAGE_NAME}\"\r\n"
                f"Content-Type: image/jpeg\r\n\r\n").encode() + image + f"\r\n--{b}--\r\n".encode()
        kind = f"multipart/form-data; boundary={b}"
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": kind, "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return None
    except urllib.error.HTTPError as e:
        return "the webhook was deleted" if e.code == 404 else f"Discord answered {e.code}"
    except Exception as e:                       # offline, DNS, timeout...
        return f"couldn't reach Discord ({getattr(e, 'reason', e)})"


# ------------------------------------------------------------------ Rich Presence


class Presence:
    """Rich Presence through the Discord desktop app's local connection (a named pipe on Windows,
    a socket on macOS/Linux). set() only records the wanted activity; a thread sends it, at most
    once per 15 s (Discord's limit), and keeps retrying while Discord isn't running."""
    INTERVAL = 15                # seconds between updates and between connection attempts

    def __init__(self):
        self.app_id = self.activity = self.pipe = None
        self.status = "off"
        self.changed = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def set(self, app_id, activity):
        """app_id None turns presence off; activity None clears it but stays connected."""
        if (app_id, activity) != (self.app_id, self.activity):
            self.app_id, self.activity = app_id, activity
            self.changed.set()

    def _run(self):
        conn = sent = None
        while True:
            self.changed.wait(); self.changed.clear()
            app_id, act = self.app_id, self.activity
            try:
                if self.pipe is not None and conn != app_id:
                    self._close()                    # turned off, or a different application
                if not app_id:
                    self.status = "off"; continue
                if self.pipe is None:
                    self._connect(app_id); conn, sent = app_id, None
                if act != sent:
                    self._send(1, {"cmd": "SET_ACTIVITY", "nonce": f"{time.time():.6f}",
                                   "args": {"pid": os.getpid(), "activity": act}})
                    op, reply = self._recv()
                    if reply.get("evt") == "ERROR":
                        raise ValueError(reply.get("data", {}).get("message", "Discord refused the update"))
                    sent = act
                self.status = "connected"
            except (OSError, ValueError) as e:
                self._close(); conn = sent = None
                self.status = str(e) or "connection lost"
                self.changed.set()                   # try again after the pause below
            time.sleep(self.INTERVAL)

    def _connect(self, app_id):
        for i in range(10):
            try:
                if sys.platform == "win32":
                    self.pipe = open(rf"\\?\pipe\discord-ipc-{i}", "r+b", buffering=0)
                else:
                    import socket
                    base = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
                    sk = socket.socket(socket.AF_UNIX); sk.settimeout(10)
                    try: sk.connect(os.path.join(base, f"discord-ipc-{i}"))
                    except OSError: sk.close(); raise
                    self.pipe = sk
                break
            except OSError:
                continue
        if self.pipe is None:
            raise OSError("Discord isn't running")
        self._send(0, {"v": 1, "client_id": app_id})          # handshake
        op, reply = self._recv()
        if reply.get("evt") != "READY":
            raise ValueError(reply.get("message") or "Discord didn't accept the Application ID")

    def _send(self, op, obj):
        data = json.dumps(obj).encode()
        frame = op.to_bytes(4, "little") + len(data).to_bytes(4, "little") + data
        if hasattr(self.pipe, "sendall"): self.pipe.sendall(frame)
        else: self.pipe.write(frame)

    def _recv(self):
        def read(n):
            out = b""
            while len(out) < n:
                c = self.pipe.recv(n - len(out)) if hasattr(self.pipe, "recv") else self.pipe.read(n - len(out))
                if not c: raise OSError("Discord closed the connection")
                out += c
            return out
        head = read(8)
        op, n = int.from_bytes(head[:4], "little"), int.from_bytes(head[4:], "little")
        return op, json.loads(read(n) or b"{}")

    def _close(self):
        try:
            if self.pipe is not None: self.pipe.close()
        except OSError:
            pass
        self.pipe = None


# ------------------------------------------------------------------ what gets sent


def embed(title, fields, color):
    """A webhook message with one card: a title and short name/value fields side by side."""
    return {"username": "ms-overlay", "embeds": [{
        "title": title, "color": int(color[1:], 16),
        "fields": [{"name": k, "value": v, "inline": True} for k, v in fields]}]}


def test_message(name, levelups, sessions, color):
    posts = [t for on, t in ((levelups, "level-ups"), (sessions, "session summaries")) if on]
    return embed("ms-overlay is connected \u2714",
                 [("Character", name), ("Posts", ", ".join(posts) or "none (turned off)")], color)


def level_up_message(name, job, lvl, color):
    """'Mapler (Hero) reached level 143! 🎉'; without the job if it hasn't been read."""
    who = f"{name} ({job})" if job else name
    return embed(f"{who} reached level {lvl}! \U0001F389", [], color)


def session_summary(name, session, color):
    """The summary of a session that is ending, or None if it is too short to be worth posting."""
    tr, now = session.tracker, session.clock()
    if tr.t_first is None or now - tr.t_first < SUMMARY_MIN:
        return None
    ap = "~" if tr.approx else ""
    r = tr.rate(now, WHOLE)
    (l0, _, _), (l1, _, p1) = tr.first, tr.last
    return embed(f"{name}\u2019s session", [
        ("Time", fmt.dur(now - tr.t0)),
        ("EXP gained", fmt.signed(tr.cum_exp, ap)),
        ("Average EXP/h", ap + fmt.num(r[0]) if r else fmt.DASH),
        ("Level", f"{l0} \u2192 {l1} ({fmt.pct(p1)})" if l1 != l0 else f"{l1} ({fmt.pct(p1)})"),
        ("Level progress", fmt.signed_pct(tr.cum_pct)),
        ("Kills", fmt.num(tr.gains(tr.t0))),
    ], color)


def presence_activity(session, now):
    """What Discord shows on the profile at wall time `now`, or None (nothing read for a while: the
    game is probably closed)."""
    if session.cur is None or not session.recently_read(now):
        return None
    tr, sn = session.tracker, session.clock(now)
    lvl, _, pct = session.cur
    act = {"details": f"Lv {lvl} \u00b7 {fmt.pct(pct)}"}
    if tr.t0 is not None and not session.paused:   # Discord counts up from this wall time (ms);
        act["timestamps"] = {"start": int((tr.t0 + session.paused_total) * 1000)}   # pauses shift it
    r = tr.recent_rate(sn)
    if session.paused:
        act["state"] = "Paused"
    elif r and r[0] > 0:
        act["state"] = f"{fmt.short(r[0])} EXP/h"
        eta = eta_seconds(pct, r[1])
        if eta is not None and eta < 100 * 3600:
            act["state"] += f" \u00b7 level in {fmt.hours_minutes(eta)}"
    else:
        act["state"] = "Starting a session"
    return act


# ------------------------------------------------------------------ the overlay's side


class DiscordLink:
    """Everything the overlay sends to Discord, following the settings (a dict read live). Webhook
    posts run on background threads and report how they went through `notify(text)`, called from
    that thread. With `posts=False` (demo mode) only the test message is sent."""
    def __init__(self, settings, notify, posts=True):
        self.S, self.notify, self.posts = settings, notify, posts
        self.presence = Presence()
        self.announced = {}         # character name -> highest level-up already posted
        self.webhook_status = ""

    def _send(self, payload, wait=False, test=False, screenshot=False):
        """Post in the background (or right away with `wait`). With `screenshot`, the game window
        is captured first and shown in the message; if it can't be, the message goes without."""
        url = self.S["discord_webhook"]
        def go():
            image = None
            if screenshot:
                if not test: time.sleep(SCREENSHOT_DELAY)
                shot = gamewindow.capture()
                if shot is not None:
                    image = gamewindow.as_jpeg(shot)
                    payload["embeds"][0]["image"] = {"url": f"attachment://{IMAGE_NAME}"}
            err = post_webhook(url, payload, image=image)
            note = (f"Couldn't post: {err}." if err else
                    "Test message sent." if test else f"Last post: {time.strftime('%H:%M')}")
            if not err and screenshot and image is None:
                note += " (no screenshot: the MapleStory window couldn't be captured)"
            self.notify(note)
        if wait: go()
        else: threading.Thread(target=go, daemon=True).start()

    def _wants(self, key):
        return self.posts and self.S[key] and self.S["discord_webhook"]

    def test(self):
        self.webhook_status = "Sending\u2026"
        S = self.S
        self._send(test_message(S["name"], S["discord_levelups"], S["discord_sessions"], S["accent"]), test=True,
                   screenshot=S["discord_screenshot"])         # shows exactly what a level-up would share

    def level_up(self, lvl, job=None):
        name = self.S["name"]
        if lvl <= self.announced.get(name, 0):        # already posted (e.g. a misread level came back)
            return
        self.announced[name] = lvl
        if self._wants("discord_levelups"):
            self._send(level_up_message(name, job, lvl, self.S["accent"]), screenshot=self.S["discord_screenshot"])

    def session_ended(self, session, wait=False):
        """Post a summary of the session that is about to end, if it's long enough and wanted.
        `wait` sends it right away (when quitting) instead of in the background."""
        if self._wants("discord_sessions"):
            msg = session_summary(self.S["name"], session, self.S["accent"])
            if msg: self._send(msg, wait=wait)

    def app_id(self):
        """The application presence is shown under: the user's own if set, else ms-overlay's."""
        return self.S["discord_app_id"] or APP_ID

    def presence_on(self):
        return self.S["discord_presence"] and self.app_id().isdigit()

    def update_presence(self, session, now):
        on = self.presence_on()
        self.presence.set(self.app_id() if on else None,
                          presence_activity(session, now) if on else None)

    def presence_status(self):
        """One line for the settings window."""
        st = self.presence.status
        if not self.S["discord_presence"]: return "Off."
        if not self.presence_on(): return "That Application ID isn't valid: it's a long number (or leave it empty)."
        if st == "off": return "Connecting\u2026"
        if st == "connected":
            return "Connected. " + ("Showing your level." if self.presence.activity else
                                    "Nothing to show until the status bar is read.")
        return f"Not connected: {st}."
