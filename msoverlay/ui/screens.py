"""The usable area of the screen at a point, for placing the overlay at a screen's edges."""
from ..paths import MAC, WIN


def work_area(root, x, y):
    """(left, top, right, bottom) of the screen containing (x, y), without the taskbar where
    the system says (Windows). Falls back to the main screen as Tk sees it."""
    try:
        if WIN:
            return _windows(x, y)
        if MAC:
            return _mac(x, y)
    except Exception:
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def _windows(x, y):
    import ctypes
    from ctypes import wintypes as wt
    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
    u = ctypes.windll.user32
    u.MonitorFromPoint.restype = ctypes.c_void_p; u.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
    u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    mon = u.MonitorFromPoint(wt.POINT(int(x), int(y)), 2)           # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    if not u.GetMonitorInfoW(mon, ctypes.byref(info)):
        raise OSError("GetMonitorInfo failed")
    r = info.rcWork                                                  # the monitor minus the taskbar
    return r.left, r.top, r.right, r.bottom


def _mac(x, y):
    import Quartz
    err, ids, n = Quartz.CGGetDisplaysWithPoint((x, y), 1, None, None)
    if err or not n:
        ids = [Quartz.CGMainDisplayID()]
    b = Quartz.CGDisplayBounds(ids[0])
    top = b.origin.y + (25 if Quartz.CGDisplayIsMain(ids[0]) else 0)   # leave the menu bar free
    return int(b.origin.x), int(top), int(b.origin.x + b.size.width), int(b.origin.y + b.size.height)
