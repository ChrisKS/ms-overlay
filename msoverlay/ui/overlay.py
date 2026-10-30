"""The overlay window: four stacked see-through layers, the header and rate columns, and the loop
that feeds the reader's results into the session."""
import os
import queue
import subprocess
import time
import tkinter as tk
from tkinter import font as tkfont

from .. import fmt, settings
from ..capture import Reader
from ..datalog import log_row
from ..discord import DiscordLink
from ..paths import DATA, MAC, WIN
from ..session import Session, different_character
from ..updates import REPO, UpdateChecker
from ..settings import GRAPH_MODES, KINDS
from . import columns, graph, screens
from .settings_window import SettingsWindow
from .theme import BAD, BG, BORDER, CLEAR, DIM2, FG, FONT, GOOD, WARN, mix, rrect, see_through

POLL_MS = 250
GRAB = 10                       # pixels at the right edge where dragging resizes instead of moving
EDGE = 16                       # pixels between the overlay and a screen edge it's placed at


class Overlay:
    H, GH = 128, 230             # collapsed height, extra height for the graph (the width is a setting)

    def __init__(self, demo=False):
        self.demo = demo
        self.S = settings.load()
        self.W = self.S["width"]
        self.session = Session()
        self.q = queue.Queue()
        self.reader = Reader(self.q, self.S, self.session, demo)
        self.discord = DiscordLink(self.S, lambda text: self.q.put(("discord", text)), posts=not demo)
        self.updates = UpdateChecker(lambda: self.S["check_updates"])
        self.drag = None
        self.sizing = None          # while dragging the right edge: pointer's distance from that edge
        self.settings_win = None
        self._fonts = {}
        self.name_seen = False
        self.job = None             # read from the status bar; None until it reads as a real job
        self.acc = self.acc_fill = None
        self._topmost = None        # the "always on top" state last given to the layers
        self.c_fg = self.c_label = self.c_sub = self.c_faint = FG

        # Four stacked, borderless windows so each part can have its own opacity (Windows can only
        # fade a whole window): background (root) < fill < graph line < text/UI. Everything above the
        # background is drawn on a colour-keyed transparent canvas.
        r = self.root = tk.Tk()
        r.title("ms-overlay")
        r.overrideredirect(True)
        r.configure(bg=CLEAR)
        see_through(r)                                # rounded corners
        def layer():
            w = tk.Toplevel(r)
            w.overrideredirect(True); w.configure(bg=CLEAR)
            see_through(w)
            try: w.transient(r)                       # an owned window stays above its owner
            except tk.TclError: pass
            return w
        self.fillw, self.linew, self.fg = layer(), layer(), layer()
        self.layers = [r, self.fillw, self.linew, self.fg]
        def canvas(w):
            c = tk.Canvas(w, bg=CLEAR, highlightthickness=0, width=self.W, height=self.H); c.pack(); return c
        self.bgcv, self.fillcv, self.linecv, self.cv = (canvas(w) for w in self.layers)
        self.canvases = [self.bgcv, self.fillcv, self.linecv, self.cv]
        for w in self.layers:
            for ev in ("<FocusIn>", "<Map>", "<Visibility>"):
                w.bind(ev, lambda e: self.fix_stack())
        for c in self.canvases:
            c.bind("<ButtonPress-1>", self.on_press)
            c.bind("<B1-Motion>", self.on_drag)
            c.bind("<ButtonRelease-1>", self.on_release)
            c.bind("<Motion>", self.on_motion)
            for b in ("<Button-2>", "<Control-Button-1>") if MAC else ("<Button-3>",):   # right-click
                c.bind(b, self.on_menu)
        self.resize(initial=True)
        self.apply(save=False)

    @property
    def tracker(self):
        return self.session.tracker

    def apply(self, save=True):
        """Push the current settings into the live window."""
        S = settings.sanitize(self.S)
        fmt.set_style(S["number_format"])
        self.acc = S["accent"]; self.acc_fill = mix(self.acc, BG, 0.16)      # for the small graph buttons
        tc = S["text_color"]                           # text colour + brightness steps derived from it
        self.c_fg, self.c_label, self.c_sub, self.c_faint = tc, mix(tc, BG, 0.80), mix(tc, BG, 0.62), mix(tc, BG, 0.38)
        alphas = (S["bg_opacity"], S["fill_opacity"], S["graph_opacity"], S["fg_opacity"])
        if S["width"] != self.W:
            self.set_width(S["width"])
        if self._topmost != S["topmost"]:      # re-applying it raises the overlay above the settings window
            self._topmost = S["topmost"]
            for w in self.layers: w.attributes("-topmost", self._topmost)
        for w, alpha in zip(self.layers, alphas):
            try: w.attributes("-alpha", float(alpha))
            except tk.TclError: pass
        self.fix_stack()
        if save: self.save()
        self.redraw()

    # ---- window
    def height(self): return self.H + (self.GH if self.S["graph"] else 0)

    def resize(self, initial=False):
        h = self.height()
        if initial and self.S["x"] is not None:
            x, y = self.S["x"], self.S["y"]
        elif initial:
            x, y = self.home()
        else:                          # at the bottom of the screen, or about to run off it: grow upwards
            (x, y), old_h = self.pos, self.shown_h
            _, top, _, bottom = self.screen_area()
            if y + old_h >= bottom - EDGE - 2: y += old_h - h
            y = max(top, min(y, bottom - h))
        for c in self.canvases: c.config(height=h)
        self.move(x, y, h)
        self.bgcv.delete("all")
        rrect(self.bgcv, 3, 3, self.W - 3, h - 3, 26, fill=BG, outline=BORDER, width=2)

    def home(self):
        """The default position: centred at the top of the main screen."""
        return self.spot("tc", screens.work_area(self.root, 0, 0))

    def screen_area(self):
        """The usable area of the screen the overlay is on (by its centre)."""
        x, y = self.pos
        return screens.work_area(self.root, x + self.W // 2, y + self.shown_h // 2)

    def spot(self, where, area, y=None):
        """Top-left corner that puts the overlay at `where` in `area` (left, top, right, bottom):
        "tl", "tc", "tr", "bl", "bc", "br" (top/bottom, left/centre/right), or "c": centred
        across, at height `y`."""
        left, top, right, bottom = area
        x = {"l": left + EDGE, "c": (left + right - self.W) // 2, "r": right - self.W - EDGE}[where[-1]]
        if where == "c":
            return x, y
        return x, top + EDGE if where[0] == "t" else bottom - self.height() - EDGE

    def place(self, where):
        """Move to `where` (see spot) on the screen the overlay is on, and remember it."""
        x, y = self.spot(where, self.screen_area(), y=self.pos[1])
        self.move(x, y); self.save()

    def fix_stack(self):
        """Keep the layers in order: background < fill < line < text, and the settings window
        above them all. Windows can reorder topmost windows (e.g. when the settings window closes
        or another app grabs focus), which would hide the text under the background or the
        settings under the overlay - so re-assert the order whenever it is wrong."""
        L = self.layers
        if self.settings_win is not None and self.settings_win.exists():
            L = L + [self.settings_win.win]
        for lo, hi in zip(L, L[1:]):
            try:
                if int(self.root.tk.call("wm", "stackorder", str(lo), "isabove", str(hi))):
                    hi.lift(lo)
            except tk.TclError:
                try: hi.lift()
                except tk.TclError: pass

    def win32_own(self):
        """Make the text window an *owned* window of the background window (Windows only). Windows
        keeps owned windows above their owner no matter what gets activated or closed."""
        if not WIN:
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            u.GetAncestor.restype = ctypes.c_void_p; u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            setptr = getattr(u, "SetWindowLongPtrW", None) or u.SetWindowLongW
            setptr.restype = ctypes.c_void_p; setptr.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            h_root = u.GetAncestor(self.root.winfo_id(), 2)       # GA_ROOT
            for w in self.layers[1:]:
                setptr(u.GetAncestor(w.winfo_id(), 2), -8, h_root)   # GWLP_HWNDPARENT = owner
        except Exception:
            pass

    def set_width(self, w):
        """Resize to width w (kept within the allowed range); the left edge stays put."""
        self.W = self.S["width"] = int(min(max(w, settings.WIDTH_MIN), settings.WIDTH_MAX))
        for c in self.canvases: c.config(width=self.W)
        self.resize(); self.redraw()

    def at_edge(self, e):
        """Is the pointer on the right edge, where dragging resizes?"""
        return not self.S["lock_position"] and e.x_root - self.pos[0] >= self.W - GRAB

    def move(self, x, y, h=None):
        """Place all layers. The overlay keeps its own position and height (pos, shown_h) rather
        than asking Tk, which may not have applied a move yet."""
        h = h or self.height()
        self.pos, self.shown_h = (int(x), int(y)), h
        for w in self.layers:
            w.geometry(f"{self.W}x{h}+{int(x)}+{int(y)}")

    def save(self):
        self.S["x"], self.S["y"] = self.pos
        settings.save(self.S)

    def quit(self):
        self.save()
        for w in self.layers: w.withdraw()            # disappear at once; the summary may take a moment
        self.root.update()
        self.discord.session_ended(self.session, wait=True)
        self.root.destroy()

    # ---- interaction
    def on_press(self, e):
        self.drag = None
        tags = e.widget.gettags("current")
        if "toggle" in tags: return self.toggle_graph()
        if "update" in tags: return self.open_update()
        for k in GRAPH_MODES:
            if f"mode_{k}" in tags: self.S["mode"] = k; return self.redraw()
        self.fix_stack()
        if self.at_edge(e):
            self.sizing = self.pos[0] + self.W - e.x_root
        elif not self.S["lock_position"]:
            self.drag = (e.x_root - self.pos[0], e.y_root - self.pos[1])

    def on_drag(self, e):
        if self.sizing is not None:
            self.set_width(e.x_root + self.sizing - self.pos[0])
        elif self.drag and not self.S["lock_position"]:
            self.move(e.x_root - self.drag[0], e.y_root - self.drag[1])

    def on_motion(self, e):
        cur = "sb_h_double_arrow" if self.at_edge(e) else ""
        for c in self.canvases:
            if c.cget("cursor") != cur: c.config(cursor=cur)

    def on_release(self, e):
        changed = self.drag is not None or self.sizing is not None
        self.drag = self.sizing = None
        if changed: self.save()

    def on_menu(self, e):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Resume" if self.session.paused else "Pause", command=self.toggle_pause)
        m.add_command(label="Reset session", command=self.reset)
        m.add_separator()
        m.add_command(label="Settings…", command=self.open_settings)
        if self.update_available():
            m.add_command(label=f"Download update {self.update_available()[0]}…", command=self.open_update)
        m.add_separator()
        m.add_command(label="Quit", command=self.quit)
        m.tk_popup(e.x_root, e.y_root)

    def toggle_graph(self):
        self.S["graph"] = not self.S["graph"]; self.resize(); self.redraw(); self.save()

    def toggle_pause(self):
        self.session.toggle_pause(); self.redraw()

    def end_session(self):
        """The session is over (reset or new character): post its summary and start a new one."""
        self.discord.session_ended(self.session)
        self.session.reset()

    def reset(self):
        self.end_session(); self.redraw()

    def open_settings(self):
        if self.settings_win is not None and self.settings_win.exists():
            return self.settings_win.show()
        self.settings_win = SettingsWindow(self)
        self.update_discord()

    def open_data_folder(self):
        try:
            if WIN: os.startfile(DATA)
            else: subprocess.Popen(["open" if MAC else "xdg-open", DATA])
        except Exception:
            pass

    def restore_defaults(self):
        settings.restore_defaults(self.S)
        self.resize(); self.apply()
        if self.settings_win is not None: self.settings_win.destroy(); self.settings_win = None
        self.open_settings()

    def discord_test(self):
        self.discord.test(); self.update_discord()

    def update_discord(self):
        self.discord.update_presence(self.session, time.time())
        if self.settings_win is not None and self.settings_win.exists():
            self.settings_win.set_discord_status(self.discord.webhook_status, self.discord.presence_status())
            self.settings_win.update_status.set(self.updates.status)

    # ---- updates
    def update_available(self):
        """(tag, url) of a newer release, while checking is on."""
        return self.updates.available if self.S["check_updates"] else None

    def open_update(self):
        """Open the release's download page, only ever on this repository's GitHub releases."""
        avail = self.update_available()
        if avail and avail[1].startswith(f"https://github.com/{REPO}/releases/"):
            import webbrowser
            webbrowser.open(avail[1])

    # ---- drawing
    def txt(self, x, y, text, size, color, bold=False, anchor="center", tags="dyn"):
        """Text with the configured size/colour and an optional dark shadow so it stands out."""
        f = (FONT, max(6, round(size * self.S["font_scale"])), "bold" if bold else "normal")
        if self.S["text_shadow"]:
            self.cv.create_text(x + 1, y + 1, text=text, anchor=anchor, fill="#000000", font=f, tags="dyn")
        return self.cv.create_text(x, y, text=text, anchor=anchor, fill=color, font=f, tags=tags)

    def measure(self, text, size, bold=True):
        """Width in pixels of text drawn by txt()."""
        key = (max(6, round(size * self.S["font_scale"])), bold)
        f = self._fonts.setdefault(key, tkfont.Font(family=FONT, size=key[0], weight="bold" if bold else "normal"))
        return f.measure(text)

    def fitting(self, options, size, room, bold=True):
        """The first of `options` (longest first) that fits in `room` pixels, or None."""
        return next((t for t in options if self.measure(t, size, bold) <= room), None)

    def redraw(self):
        cv, W, H, S, ses = self.cv, self.W, self.H, self.S, self.session
        for c in (self.cv, self.fillcv, self.linecv): c.delete("dyn")

        # header: status dot, name, % and level
        dot = {"ok": GOOD, "bad": BAD, "paused": WARN}.get(ses.state, DIM2)
        cv.create_oval(24, 21, 34, 31, fill=dot, outline="", tags="dyn")
        # (on a narrow overlay: a long name is shortened, the % and the hint are left out if they don't fit)
        lvl, exp, pct = ses.cur or (None, None, None)
        right = cv.bbox(self.txt(W - 28, 26, f"Lv {lvl}" if lvl else f"Lv {fmt.DASH}", 12, self.c_fg, True, "e"))[0]
        left, name = 34, S["name"]
        if S["show_name"]:
            name = self.fitting([name] + [name[:n] + "\u2026" for n in range(len(name) - 1, 0, -1)], 12, right - 52) or ""
            if name: left = cv.bbox(self.txt(42, 26, name, 12, self.c_fg, True, "w"))[2]
        if pct is not None and right - 14 - self.measure(f"{pct:.2f}%", 10, False) > left + 10:
            right = cv.bbox(self.txt(right - 14, 27, f"{pct:.2f}%", 10, self.c_label, False, "e"))[0]
        note = None                                      # a problem reading the game matters more
        if ses.hint and not ses.paused: note = (ses.hint, BAD, "dyn")
        elif self.update_available(): note = (f"Update {self.update_available()[0]} available", self.acc, ("dyn", "update"))
        if note and self.measure(note[0], 9, False) < right - left - 20:
            self.txt((left + right) / 2, 26, note[0], 9, note[1], False, "center", note[2])

        # divider doubles as the level-progress bar
        cv.create_line(22, 49, W - 22, 49, fill=BORDER, width=3, capstyle="round", tags="dyn")
        if pct:
            cv.create_line(22, 49, 22 + (W - 44) * pct / 100, 49, fill=self.acc, width=3, capstyle="round", tags="dyn")

        # rate columns
        now = ses.clock()
        cols = settings.enabled_columns(S, "rate")
        cw = (W - 44) / len(cols)
        for i, (win, kind) in enumerate(cols):
            cx = 22 + cw * (i + 0.5)
            head = columns.header(kind, win)               # shrink (or shorten) headers that don't fit
            size = next((z for z in (8, 7, 6) if self.measure(head, z) <= cw - 6), 6)
            if self.measure(head, size) > cw - 6: head = KINDS[kind][0]
            self.txt(cx, 68, head, size, self.c_fg, True)
            r = columns.value(self.tracker, kind, now, win, pct)
            if r:
                t, col = r[0], self.c_fg if (r[1] or not S["rate_dim"]) else self.c_sub   # dimmer until the window has filled up
            else:
                t, col = fmt.DASH, self.c_faint
            room, size = cw - 14, 17                           # shrink long numbers so columns never overlap,
            while size > 7 and self.measure(t, size) > room:   # and write them shorter (1,2M, then 1M) if
                size -= 1                                      # even the smallest text is too wide
            style = 0
            while r and self.measure(t, size) > room and style + 1 < len(columns.STYLES):
                style += 1
                t = columns.value(self.tracker, kind, now, win, pct, style=style)[0]
                size = next((z for z in range(17, 6, -1) if self.measure(t, z) <= room), 7)
            self.txt(cx, 93, t, size, col, True)
            if i:
                cv.create_line(22 + cw * i, 60, 22 + cw * i, 104, fill=BORDER, width=3, capstyle="round", tags="dyn")

        # graph toggle chevron
        self.txt(W / 2, H - 11, "▴" if S["graph"] else "▾", 9, self.c_label, False, "center", ("dyn", "toggle"))
        cv.create_rectangle(W / 2 - 30, H - 22, W / 2 + 30, H - 2, outline="", fill="", tags=("dyn", "toggle"))

        if S["graph"]:
            graph.draw(self, 22, H + 4, W - 22, self.height() - 16, now)

    # ---- data feed
    def handle(self, msg):
        """One message from the reader (or a finished Discord post)."""
        kind = msg[0]
        if kind == "error":
            self.session.capture_error()
        elif kind == "discord":
            self.discord.webhook_status = msg[1]
        elif kind == "name":
            name = msg[1]
            if name != self.S["name"]:
                if self.name_seen and different_character(name, self.S["name"]):
                    self.job = None               # a different character: its job is read anew
                    if self.S["reset_on_char"]:
                        self.end_session()        # (not just an OCR wobble)
                self.S["name"] = name; self.save()
            self.name_seen = True
        elif kind == "job":
            self.job = msg[1]
        elif kind == "read":
            _, t, r = msg
            changed, new_level = self.session.read(t, r)
            if changed and self.S["log_csv"]:
                log_row(t, *self.session.cur)
            if new_level:
                self.discord.level_up(new_level, self.job)

    def poll(self):
        try:
            while True:
                self.handle(self.q.get_nowait())
        except queue.Empty:
            pass
        self.update_discord()
        self.fix_stack()
        self.redraw()
        self.root.after(POLL_MS, self.poll)

    def run(self):
        for w in self.layers: w.update_idletasks()
        self.win32_own(); self.fix_stack()
        self.reader.start()
        self.updates.start()
        self.root.after(300, self.poll)
        self.root.mainloop()
