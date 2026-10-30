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
from ..settings import GRAPH_MODES
from . import columns, graph
from .settings_window import SettingsWindow
from .theme import BAD, BG, BORDER, CLEAR, DIM2, FG, FONT, GOOD, WARN, mix, rrect, see_through

POLL_MS = 250


class Overlay:
    W, H, GH = 580, 128, 230     # width, collapsed height, extra height for the graph

    def __init__(self, demo=False):
        self.demo = demo
        self.S = settings.load()
        self.session = Session()
        self.q = queue.Queue()
        self.reader = Reader(self.q, self.S, self.session, demo)
        self.discord = DiscordLink(self.S, lambda text: self.q.put(("discord", text)), posts=not demo)
        self.updates = UpdateChecker(lambda: self.S["check_updates"])
        self.drag = None
        self.settings_win = None
        self._fonts = {}
        self.name_seen = False
        self.job = None             # read from the status bar; None until it reads as a real job
        self.acc = self.acc_fill = None
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
        for w, alpha in zip(self.layers, alphas):
            w.attributes("-topmost", bool(S["topmost"]))
            try: w.attributes("-alpha", float(alpha))
            except tk.TclError: pass
        self.fix_stack()
        if save: self.save()
        self.redraw()

    # ---- window
    def height(self): return self.H + (self.GH if self.S["graph"] else 0)

    def resize(self, initial=False):
        h = self.height()
        for c in self.canvases: c.config(height=h)
        if initial and self.S["x"] is not None:
            x, y = self.S["x"], self.S["y"]
        elif initial:
            x, y = self.home()
        else:
            x, y = self.root.winfo_x(), self.root.winfo_y()
        self.move(x, y, h)
        self.bgcv.delete("all")
        rrect(self.bgcv, 3, 3, self.W - 3, h - 3, 26, fill=BG, outline=BORDER, width=2)

    def home(self):
        """The default position: centred at the top of the main screen."""
        return (self.root.winfo_screenwidth() - self.W) // 2, 40

    def fix_stack(self):
        """Keep the layers in order: background < fill < line < text. Windows can reorder topmost
        windows (e.g. when the settings window closes or another app grabs focus), which would hide
        the text under the background - so re-assert the order whenever it is wrong."""
        L = self.layers
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

    def move(self, x, y, h=None):
        h = h or self.height()
        for w in self.layers:
            w.geometry(f"{self.W}x{h}+{int(x)}+{int(y)}")

    def save(self):
        try:
            self.S["x"], self.S["y"] = self.root.winfo_x(), self.root.winfo_y()
        except tk.TclError:
            return
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
        if not self.S["lock_position"]:
            self.drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def on_drag(self, e):
        if self.drag and not self.S["lock_position"]:
            self.move(e.x_root - self.drag[0], e.y_root - self.drag[1])

    def on_release(self, e):
        moved = self.drag is not None
        self.drag = None
        if moved: self.save()

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

    def reset_position(self):
        self.S["x"], self.S["y"] = self.home()
        self.move(self.S["x"], self.S["y"]); self.save()

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

    def measure(self, text, size):
        key = max(6, round(size * self.S["font_scale"]))
        f = self._fonts.setdefault(key, tkfont.Font(family=FONT, size=key, weight="bold"))
        return f.measure(text)

    def redraw(self):
        cv, W, H, S, ses = self.cv, self.W, self.H, self.S, self.session
        for c in (self.cv, self.fillcv, self.linecv): c.delete("dyn")

        # header: status dot, name, % and level
        dot = {"ok": GOOD, "bad": BAD, "paused": WARN}.get(ses.state, DIM2)
        cv.create_oval(24, 21, 34, 31, fill=dot, outline="", tags="dyn")
        if S["show_name"]:
            self.txt(42, 26, S["name"], 12, self.c_fg, True, "w")
        lvl, exp, pct = ses.cur or (None, None, None)
        if ses.hint and not ses.paused:
            self.txt(W / 2 + 10, 26, ses.hint, 9, BAD)
        elif self.update_available():                    # a problem reading the game matters more
            self.txt(W / 2 + 10, 26, f"Update {self.update_available()[0]} available", 9, self.acc, False, "center", ("dyn", "update"))
        lv = self.txt(W - 28, 26, f"Lv {lvl}" if lvl else f"Lv {fmt.DASH}", 12, self.c_fg, True, "e")
        if pct is not None:
            x = cv.bbox(lv)[0] - 14
            self.txt(x, 27, f"{pct:.2f}%", 10, self.c_label, False, "e")

        # divider doubles as the level-progress bar
        cv.create_line(22, 49, W - 22, 49, fill=BORDER, width=3, capstyle="round", tags="dyn")
        if pct:
            cv.create_line(22, 49, 22 + (W - 44) * pct / 100, 49, fill=self.acc, width=3, capstyle="round", tags="dyn")

        # rate columns
        now = ses.clock()
        cols = [(m * 60, k) for m, k, on in zip(S["rate_minutes"], S["rate_kind"], S["rate_on"]) if on]
        cw = (W - 44) / len(cols)
        for i, (win, kind) in enumerate(cols):
            cx = 22 + cw * (i + 0.5)
            self.txt(cx, 68, columns.header(kind, win), 8, self.c_fg, True)
            r = columns.value(self.tracker, kind, now, win, pct)
            if r:
                t, col = r[0], self.c_fg if (r[1] or not S["rate_dim"]) else self.c_sub   # dimmer until the window has filled up
            else:
                t, col = fmt.DASH, self.c_faint
            size = 17                                          # shrink long numbers so columns never overlap
            while size > 9 and self.measure(t, size) > cw - 14:
                size -= 1
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
