"""Screenshots of the MapleStory window, and nothing else.

The game window itself is captured, not the area of the screen where it is: whatever covers the
game (this overlay, notifications, other windows) and everything around it is never in the
picture. If the game window can't be found or captured on its own, capture() returns None; it
never falls back to capturing the screen.

  Windows   the visible window of the process MapleStory.exe (or with the game's window class,
            MapleStoryClass), captured with Windows Graphics Capture (what Discord streams with;
            works for a game running as administrator), else drawn by Windows on its own
            (PrintWindow); its client area, without the title bar
  macOS     the on-screen window of the app named MapleStory (CGWindowListCreateImage with only
            that window); needs the Screen Recording permission the overlay already has
  other     not supported: always None

When there's no picture, `last_problem` says which step failed.
"""
import sys

from PIL import Image

GAME_EXE = "maplestory.exe"          # Windows: the game's process ...
GAME_CLASS = "MapleStoryClass"       # ... or the game window's class, which can be read even when the
                                     # game (run as administrator, guarded by anti-cheat) won't say its name
GAME_APP = "maplestory"              # macOS: the owning app's name must contain this (any case)

last_problem = ""                    # why the last capture() gave no picture, for the user


class Problem(Exception):
    """A capture step that failed, in words for the user."""


def capture():
    """-> PIL RGB image of the game window, or None (not running, minimised, not capturable);
    `last_problem` then says why."""
    global last_problem
    try:
        if sys.platform == "win32":
            img = _capture_windows()
        elif sys.platform == "darwin":
            img = _capture_mac()
        else:
            raise Problem("screenshots only work on Windows and macOS")
        if is_blank(img):
            raise Problem("the MapleStory window came back black (is the game in exclusive fullscreen?)")
    except Problem as e:
        last_problem = str(e)
        return None
    except Exception as e:                       # anything unexpected: still never a screen capture
        last_problem = f"capturing failed ({e})"
        return None
    last_problem = ""
    return img


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


def candidates():
    """Windows whose title, class, process or app name mentions Maple, as text lines: for
    --capture-test, to see what the game looks like to this computer. Titles are only shown here;
    capture() never picks a window by its title."""
    try:
        if sys.platform == "win32":
            return [f"title={w['title']!r} class={w['cls']!r} process={w['exe'] or '(access denied)'} "
                    f"size={w['w']}x{w['h']} minimised={w['minimized']} game={_is_game(w)}"
                    for w in _windows_list() if "maple" in (w["title"] + w["cls"] + w["exe"]).lower()]
        if sys.platform == "darwin":
            return [f"app={w['owner']!r} title={w['title']!r} size={w['w']}x{w['h']} game={GAME_APP in w['owner'].lower()}"
                    for w in _mac_windows() if "maple" in (w["owner"] + w["title"]).lower()]
    except Exception as e:
        return [f"(couldn't list windows: {e})"]
    return []


# ------------------------------------------------------------------ Windows
_api = None


def _win_api():
    """ctypes access to the few Windows functions used here, with 64-bit safe prototypes."""
    global _api
    if _api is None:
        import ctypes
        from ctypes import wintypes as wt
        u, g, k = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
        H = ctypes.c_void_p                               # handles are pointer-sized on 64-bit
        for f, res, args in (
                (u.GetDC, H, [H]), (u.ReleaseDC, ctypes.c_int, [H, H]), (u.PrintWindow, wt.BOOL, [H, H, wt.UINT]),
                (u.GetClientRect, wt.BOOL, [H, ctypes.POINTER(wt.RECT)]), (u.IsWindowVisible, wt.BOOL, [H]),
                (u.IsIconic, wt.BOOL, [H]), (u.GetClassNameW, ctypes.c_int, [H, wt.LPWSTR, ctypes.c_int]),
                (u.GetWindowTextW, ctypes.c_int, [H, wt.LPWSTR, ctypes.c_int]),
                (u.GetWindowThreadProcessId, wt.DWORD, [H, ctypes.POINTER(wt.DWORD)]),
                (g.CreateCompatibleDC, H, [H]), (g.CreateCompatibleBitmap, H, [H, ctypes.c_int, ctypes.c_int]),
                (g.SelectObject, H, [H, H]), (g.DeleteObject, wt.BOOL, [H]), (g.DeleteDC, wt.BOOL, [H]),
                (g.GetDIBits, ctypes.c_int, [H, H, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_void_p, wt.UINT]),
                (k.OpenProcess, H, [wt.DWORD, wt.BOOL, wt.DWORD]), (k.CloseHandle, wt.BOOL, [H]),
                (k.QueryFullProcessImageNameW, wt.BOOL, [H, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)])):
            f.restype, f.argtypes = res, args
        _api = (ctypes, wt, u, g, k, H)
    return _api


def _windows_list():
    """Every visible top-level window: dict(hwnd, title, cls, exe ("" if its process won't say),
    w, h of the client area, minimized)."""
    ctypes, wt, u, g, k, H = _win_api()

    def text(fn, hwnd):
        buf = ctypes.create_unicode_buffer(256)
        fn(hwnd, buf, 256)
        return buf.value

    def exe_of(hwnd):
        pid = wt.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = k.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not proc:
            return ""
        try:
            buf, size = ctypes.create_unicode_buffer(1024), wt.DWORD(1024)
            ok = k.QueryFullProcessImageNameW(proc, 0, buf, ctypes.byref(size))
            return buf.value.replace("/", "\\").rsplit("\\", 1)[-1].lower() if ok else ""
        finally:
            k.CloseHandle(proc)

    out = []
    @ctypes.WINFUNCTYPE(wt.BOOL, H, H)
    def each(hwnd, _):
        if u.IsWindowVisible(hwnd):
            r = wt.RECT()
            u.GetClientRect(hwnd, ctypes.byref(r))
            out.append(dict(hwnd=hwnd, title=text(u.GetWindowTextW, hwnd), cls=text(u.GetClassNameW, hwnd),
                            exe=exe_of(hwnd), w=r.right, h=r.bottom, minimized=bool(u.IsIconic(hwnd))))
        return True
    ctypes.windll.user32.EnumWindows(each, None)
    return out


def _is_game(w):
    return w["exe"] == GAME_EXE or w["cls"] == GAME_CLASS


def _capture_windows():
    games = [w for w in _windows_list() if _is_game(w)]
    if not games:
        raise Problem("no MapleStory window was found")
    shown = [w for w in games if not w["minimized"] and w["w"] > 0 and w["h"] > 0]
    if not shown:
        raise Problem("the MapleStory window is minimised")
    game = max(shown, key=lambda w: w["w"] * w["h"])
    # 1. Windows Graphics Capture: frames of that one window straight from the compositor, as
    #    Discord's streaming does. Works for a game running as administrator, needs no rights.
    try:
        img = _graphics_capture(game)
        if img is not None and not is_blank(img):
            return img
        why = "no frame" if img is None else "black frame"
    except Exception as e:
        why = str(e) or type(e).__name__
    # 2. Ask Windows to draw the window on its own; refused for an administrator's window
    img = None
    for flags in (3, 1):                         # PW_CLIENTONLY with PW_RENDERFULLCONTENT, then without
        img = _print_window(game["hwnd"], game["w"], game["h"], flags)
        if img is not None and not is_blank(img):
            return img
    if img is None:
        raise Problem(f"Windows wouldn't let ms-overlay capture the MapleStory window (Graphics Capture: {why})")
    return img                                   # blank: capture() reports it


def _graphics_capture(game, timeout=3.0):
    """One frame of the game window via Windows Graphics Capture (the windows-capture package),
    cropped to the window's client area. None if no frame arrived."""
    import importlib.util
    import threading
    import types
    # windows-capture imports cv2 only for a save helper we never use, and the build leaves it out:
    # stand in for it (once; the stand-in has no import spec to look up later)
    if "cv2" not in sys.modules and importlib.util.find_spec("cv2") is None:
        sys.modules["cv2"] = types.ModuleType("cv2")
    from windows_capture import WindowsCapture
    got, done = {}, threading.Event()
    try:                                         # no yellow capture border (needs Windows 11)
        cap = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=int(game["hwnd"]))
    except Exception:                            # Windows 10: the border can't be turned off
        cap = WindowsCapture(cursor_capture=False, window_hwnd=int(game["hwnd"]))

    @cap.event
    def on_frame_arrived(frame, control):
        if "img" not in got:                     # copy out of the mapped frame: BGRA -> RGB
            got["img"] = Image.fromarray(frame.frame_buffer[:, :, 2::-1].copy())
        control.stop(); done.set()

    @cap.event
    def on_closed():
        done.set()

    control = cap.start_free_threaded()
    done.wait(timeout)
    if not control.is_finished():
        control.stop()
    img = got.get("img")
    return None if img is None else _crop_to_client(img, game)


def _crop_to_client(img, game):
    """Windows Graphics Capture returns the whole window (title bar and border too); keep the
    client area, like the other method. The whole window if the offsets don't add up."""
    try:
        ctypes, wt, u, g, k, H = _win_api()
        frame = wt.RECT()                        # the window's visible bounds = the captured frame
        ctypes.windll.dwmapi.DwmGetWindowAttribute(H(game["hwnd"]), 9, ctypes.byref(frame), ctypes.sizeof(frame))
        origin = wt.POINT(0, 0)                  # DWMWA_EXTENDED_FRAME_BOUNDS ^, client top-left v
        ctypes.windll.user32.ClientToScreen(H(game["hwnd"]), ctypes.byref(origin))
        x, y = origin.x - frame.left, origin.y - frame.top
        if x >= 0 and y >= 0 and x + game["w"] <= img.width and y + game["h"] <= img.height:
            return img.crop((x, y, x + game["w"], y + game["h"]))
    except Exception:
        pass
    return img


def _print_window(hwnd, w, h, flags):
    """The window drawn by Windows on its own into a bitmap, or None if Windows refused."""
    ctypes, wt, u, g, k, H = _win_api()
    screen_dc = u.GetDC(hwnd)
    mem_dc = g.CreateCompatibleDC(screen_dc)
    bmp = g.CreateCompatibleBitmap(screen_dc, w, h)
    try:
        old = g.SelectObject(mem_dc, bmp)
        drawn = u.PrintWindow(hwnd, mem_dc, flags)
        g.SelectObject(mem_dc, old)              # GetDIBits needs the bitmap deselected
        if not drawn:
            return None
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                        ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]
        bi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h,   # top-down rows
                              biPlanes=1, biBitCount=32, biCompression=0)                       # BI_RGB
        buf = ctypes.create_string_buffer(w * h * 4)
        if g.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bi), 0) != h:
            return None
        return Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    finally:
        g.DeleteObject(bmp); g.DeleteDC(mem_dc); u.ReleaseDC(hwnd, screen_dc)


# ------------------------------------------------------------------ macOS
def _mac_windows():
    """On-screen normal windows: dict(id, owner, title, w, h)."""
    import Quartz
    infos = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
    out = []
    for info in infos or []:
        if info.get("kCGWindowLayer", 0) != 0:
            continue
        b = info.get("kCGWindowBounds", {})
        out.append(dict(id=info["kCGWindowNumber"], owner=str(info.get("kCGWindowOwnerName", "")),
                        title=str(info.get("kCGWindowName", "") or ""), w=int(b.get("Width", 0)), h=int(b.get("Height", 0))))
    return out


def _capture_mac():
    import Quartz
    # by the app's name, never a window title: a browser tab titled "MapleStory" must not match
    games = [w for w in _mac_windows() if GAME_APP in w["owner"].lower() and w["w"] * w["h"] > 0]
    if not games:
        raise Problem("no MapleStory window was found")
    game = max(games, key=lambda w: w["w"] * w["h"])
    ref = Quartz.CGWindowListCreateImage(Quartz.CGRectNull, Quartz.kCGWindowListOptionIncludingWindow,
                                         game["id"], Quartz.kCGWindowImageBoundsIgnoreFraming)
    if ref is None:
        raise Problem("macOS gave no picture of the MapleStory window (is Screen Recording allowed?)")
    w, h = Quartz.CGImageGetWidth(ref), Quartz.CGImageGetHeight(ref)
    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(ref))
    return Image.frombuffer("RGB", (w, h), bytes(data), "raw", "BGRX", Quartz.CGImageGetBytesPerRow(ref), 1)
