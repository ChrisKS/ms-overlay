"""ms-overlay: a compact always-on-top overlay that reads Level / EXP from the MapleStory status
bar and shows EXP per hour over several time windows, plus a graph.

Passive screen reading only: no game memory access, no input injection.
"""

import os as _os

# numpy's maths library (OpenBLAS) starts a worker thread per CPU core when numpy is imported and
# reserves a buffer of about 30 MB for each. Windows counts all of it, so on a 16-24 thread PC
# that was most of the overlay's memory (hundreds of MB). ms-overlay only scans a few small pixel
# areas, so one thread is plenty. This must run before numpy is first imported, which is why it's
# here: everything in the app imports this package first.
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    _os.environ.setdefault(_var, "1")
