"""Where things are: the app's own folder, and where settings and the log are kept."""
import os
import sys

WIN = sys.platform == "win32"
MAC = sys.platform == "darwin"
FROZEN = getattr(sys, "frozen", False)

# The folder holding ms-overlay.exe (or the macOS app's executable); the repository root when run
# from source. The bundled Tesseract is looked for here.
BASE = (os.path.dirname(sys.executable) if FROZEN
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Settings and the log live next to the exe, except in the macOS app, whose own folder must stay
# unchanged (writing into it would break its code signature).
DATA = os.path.expanduser("~/Library/Application Support/ms-overlay") if MAC and FROZEN else BASE


def data_file(name):
    """Path of a file in the data folder (created if needed)."""
    os.makedirs(DATA, exist_ok=True)
    return os.path.join(DATA, name)
