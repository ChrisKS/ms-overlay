import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from msoverlay import updates


@pytest.mark.parametrize("tag, parsed", [
    ("v1.2.0", (1, 2, 0)), ("1.2", (1, 2)), (" v10.0.1 ", (10, 0, 1)),
    ("dev", None), ("v1.2-beta", None), ("", None), (None, None),
])
def test_parse(tag, parsed):
    assert updates.parse(tag) == parsed


@pytest.mark.parametrize("latest, current, newer", [
    ("v1.2.1", "v1.2.0", True), ("v1.10.0", "v1.9.9", True), ("v2", "v1.9", True),
    ("v1.2.0", "v1.2.0", False), ("v1.2", "v1.2.0", False), ("v1.1.9", "v1.2.0", False),
    ("v1.3.0", "dev", False), ("weird", "v1.0.0", False),
])
def test_is_newer(latest, current, newer):
    assert updates.is_newer(latest, current) is newer


@pytest.fixture
def github(monkeypatch):
    """A local stand-in for GitHub's latest-release API. Set .release to the JSON it answers
    with, or to None for a 404 (a repository without releases)."""
    class State: release = None; agents = []
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            State.agents.append(self.headers["User-Agent"])
            if State.release is None:
                self.send_response(404); self.end_headers(); return
            body = json.dumps(State.release).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(updates, "API_URL", f"http://127.0.0.1:{srv.server_port}/latest")
    yield State
    srv.shutdown()


def release(tag):
    return {"tag_name": tag, "html_url": f"https://github.com/{updates.REPO}/releases/tag/{tag}"}


def test_newer_release_is_reported(github):
    github.release = release("v1.3.0")
    c = updates.UpdateChecker(lambda: True, version="v1.2.0")
    c.check()
    assert c.available == ("v1.3.0", f"https://github.com/{updates.REPO}/releases/tag/v1.3.0")
    assert c.status == "Version v1.3.0 is available (you have v1.2.0)."
    assert github.agents[0].startswith("ms-overlay/")


def test_same_or_older_release_is_not(github):
    github.release = release("v1.2.0")
    c = updates.UpdateChecker(lambda: True, version="v1.2.0")
    c.check()
    assert c.available is None and c.status.startswith("You have the latest version (v1.2.0).")


def test_failures_are_reported_not_raised(github):
    c = updates.UpdateChecker(lambda: True, version="v1.2.0")
    c.check()                                            # 404: no releases yet
    assert c.available is None and c.status.startswith("Couldn't check for updates")


def test_development_builds_never_check(github, monkeypatch):
    started = []
    monkeypatch.setattr(updates.threading, "Thread", lambda **kw: started.append(kw) or pytest.fail("started"))
    c = updates.UpdateChecker(lambda: True, version="dev")
    c.start()
    assert not started and "development build" in c.status


def test_background_check_respects_the_setting(github, monkeypatch):
    github.release = release("v9.0.0")
    monkeypatch.setattr(updates, "FIRST_CHECK", 0)
    on = [False]
    c = updates.UpdateChecker(lambda: on[0], version="v1.0.0")
    c.start()
    import time
    for _ in range(100):
        if c.status: break
        time.sleep(0.02)
    assert c.status == "Checking for updates is off." and not github.agents
    on[0] = True; c.check_now()
    for _ in range(100):
        if c.available: break
        time.sleep(0.02)
    assert c.available[0] == "v9.0.0"
