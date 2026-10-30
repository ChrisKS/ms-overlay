"""Screenshots of the MapleStory window, and nothing else.

The game window itself is captured, not the area of the screen where it is: whatever covers the
game (this overlay, notifications, other windows) and everything around it is never in the
picture. If the game window can't be found or captured on its own, capture() returns None; it
never falls back to capturing the screen.

  Windows   the visible window of the process MapleStory.exe, drawn by Windows on its own
            (PrintWindow); its client area, without the title bar
  macOS     the on-screen window of the app named MapleStory (CGWindowListCreateImage with only
            that window); needs the Screen Recording permission the overlay already has
  other     not supported: always None
"""
import sys

from PIL import Image

GAME_EXE = "maplestory.exe"          # Windows: the game's process
GAME_APP = "maplestory"              # macOS: the owning app's name must contain this (any case)


def capture():
    """-> PIL RGB image of the game window, or None (not running, minimised, not capturable)."""
    try:
        if sys.platform == "win32":
            img = _capture_windows()
        elif sys.platform == "darwin":
            img = _capture_mac()
        else:
            img = None
    except Exception:
        return None
    return None if img is None or is_blank(img) else img


def is_blank(img):
    """True for an all-black (or single-colour) picture: what a window that can't be drawn on
    its own (e.g. exclusive fullscreen) comes back as."""
    return all(hi - lo < 8 for lo, hi in img.convert("RGB").getextrema())


def as_jpeg(img, quality=90):
    """Encode for upload: JPEG keeps a full-screen game shot well under Discord's size limit."""
    import io
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


# ------------------------------------------------------------------ Windows
def _capture_windows():
    import ctypes
    from ctypes import wintypes
    user32, gdi32, kernel32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
    H = ctypes.c_void_p                                   # handles are pointer-sized on 64-bit
    user32.GetDC.restype = H; user32.GetDC.argtypes = [H]
    user32.ReleaseDC.argtypes = [H, H]
    user32.PrintWindow.argtypes = [H, H, wintypes.UINT]
    user32.GetClientRect.argtypes = [H, ctypes.POINTER(wintypes.RECT)]
    gdi32.CreateCompatibleDC.restype = H; gdi32.CreateCompatibleDC.argtypes = [H]
    gdi32.CreateCompatibleBitmap.restype = H; gdi32.CreateCompatibleBitmap.argtypes = [H, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = H; gdi32.SelectObject.argtypes = [H, H]
    gdi32.DeleteObject.argtypes = [H]; gdi32.DeleteDC.argtypes = [H]
    gdi32.GetDIBits.argtypes = [H, H, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    kernel32.OpenProcess.restype = H
    kernel32.QueryFullProcessImageNameW.argtypes = [H, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [H]

    def exe_of(hwnd):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(H(hwnd), ctypes.byref(pid))
        proc = kernel32.OpenProcess(0x1000, False, pid.value)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not proc:
            return ""
        try:
            buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
            ok = kernel32.QueryFullProcessImageNameW(proc, 0, buf, ctypes.byref(size))
            return buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower() if ok else ""
        finally:
            kernel32.CloseHandle(proc)

    found = []                                            # (area, hwnd, width, height)
    @ctypes.WINFUNCTYPE(wintypes.BOOL, H, H)
    def each(hwnd, _):
        if user32.IsWindowVisible(H(hwnd)) and not user32.IsIconic(H(hwnd)) and exe_of(hwnd) == GAME_EXE:
            r = wintypes.RECT()
            if user32.GetClientRect(hwnd, ctypes.byref(r)) and r.right > 0 and r.bottom > 0:
                found.append((r.right * r.bottom, hwnd, r.right, r.bottom))
        return True
    user32.EnumWindows(each, None)
    if not found:
        return None
    _, hwnd, w, h = max(found)

    screen_dc = user32.GetDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bmp = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
    try:
        old = gdi32.SelectObject(mem_dc, bmp)
        drawn = user32.PrintWindow(hwnd, mem_dc, 3)       # PW_CLIENTONLY | PW_RENDERFULLCONTENT
        gdi32.SelectObject(mem_dc, old)                   # GetDIBits needs the bitmap deselected
        if not drawn:
            return None
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
        bi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h,   # top-down rows
                              biPlanes=1, biBitCount=32, biCompression=0)                       # BI_RGB
        buf = ctypes.create_string_buffer(w * h * 4)
        if gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bi), 0) != h:
            return None
        return Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    finally:
        gdi32.DeleteObject(bmp); gdi32.DeleteDC(mem_dc); user32.ReleaseDC(hwnd, screen_dc)


# ------------------------------------------------------------------ macOS
def _capture_mac():
    import Quartz
    infos = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
    best = None
    for info in infos or []:
        if GAME_APP not in str(info.get("kCGWindowOwnerName", "")).lower() or info.get("kCGWindowLayer", 0) != 0:
            continue                                      # the app's name, never a window title (a browser
        b = info.get("kCGWindowBounds", {})               # tab titled "MapleStory" must not match)
        area = b.get("Width", 0) * b.get("Height", 0)
        if area > 0 and (best is None or area > best[0]):
            best = (area, info["kCGWindowNumber"])
    if best is None:
        return None
    ref = Quartz.CGWindowListCreateImage(Quartz.CGRectNull, Quartz.kCGWindowListOptionIncludingWindow,
                                         best[1], Quartz.kCGWindowImageBoundsIgnoreFraming)
    if ref is None:
        return None
    w, h = Quartz.CGImageGetWidth(ref), Quartz.CGImageGetHeight(ref)
    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(ref))
    return Image.frombuffer("RGB", (w, h), bytes(data), "raw", "BGRX", Quartz.CGImageGetBytesPerRow(ref), 1)
