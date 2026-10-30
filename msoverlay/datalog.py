"""The CSV log: one row per accepted change of level / EXP / %."""
import csv
import datetime
import os

from .paths import data_file

LOG_NAME = "maple_log.csv"


def log_row(t, lvl, exp, pct, path=None):
    """Append one row (t = wall-clock time). Failing to write (file open in Excel, ...) is ignored."""
    path = path or data_file(LOG_NAME)
    try:
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if new: w.writerow(["time", "level", "exp", "percent"])
            w.writerow([datetime.datetime.fromtimestamp(t).isoformat(timespec="seconds"), lvl, exp, pct])
    except OSError:
        pass
