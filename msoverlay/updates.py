"""Checks GitHub for a newer release, so the overlay can say one is available. Only reads the
public "latest release" of this repository; nothing is downloaded or installed.

Development builds (VERSION "dev") never check: they aren't a release to compare with."""
import json
import re
import threading
import time

from .version import VERSION

REPO = "ChrisKS/ms-overlay"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = f"ms-overlay/{VERSION} (https://github.com/{REPO})"
FIRST_CHECK = 10                  # seconds after start
EVERY = 6 * 3600                  # then this often (GitHub allows 60 unauthenticated requests an hour)


def parse(version):
    """'v1.2.0' / '1.2' -> (1, 2, 0) / (1, 2); None for anything else ('dev', 'v1.2-beta')."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (version or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_newer(latest, current):
    """True if release `latest` is a newer version than `current` (1.2 == 1.2.0)."""
    a, b = parse(latest), parse(current)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def latest_release(timeout=10):
    """-> (tag, page_url) of the latest published release (drafts and pre-releases never count).
    Raises OSError / ValueError if GitHub can't be asked."""
    import urllib.request
    req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return data["tag_name"], data["html_url"]


class UpdateChecker:
    """Checks in the background while `enabled()` says so. `available` is (tag, url) once a newer
    release has been found; `status` is one line for the settings window."""
    def __init__(self, enabled, version=VERSION):
        self.enabled, self.version = enabled, version
        self.available = None
        self.status = "This is a development build: it doesn't check for updates." if parse(version) is None else ""
        self.wake = threading.Event()

    def start(self):
        if parse(self.version) is not None:
            threading.Thread(target=self._run, daemon=True).start()

    def check_now(self):
        self.wake.set()

    def check(self):
        """One check (also used by tests). Never raises."""
        try:
            tag, url = latest_release()
        except Exception as e:                     # offline, rate-limited, no releases yet (404)...
            self.status = f"Couldn't check for updates ({getattr(e, 'reason', None) or e})."
            return
        if is_newer(tag, self.version):
            self.available = (tag, url)
            self.status = f"Version {tag} is available (you have {self.version})."
        else:
            self.available = None
            self.status = f"You have the latest version ({self.version}). Checked {time.strftime('%H:%M')}."

    def _run(self):
        self.wake.wait(FIRST_CHECK)
        while True:
            self.wake.clear()
            if self.enabled():
                self.check()
            else:
                self.status = "Checking for updates is off."
            self.wake.wait(EVERY)
