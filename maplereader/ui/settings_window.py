"""The settings window. Every control writes straight into the shared settings dict and calls
overlay.apply(), so changes show at once and are saved automatically."""
import tkinter as tk
from tkinter import ttk

from ..settings import (ACCENTS, DEFAULTS, FONT_SCALES, GRAPH_MODES, GRAPH_STYLES, KINDS,
                        NUMBER_FORMATS, TEXT_COLORS)
from .theme import BG, BORDER, BUTTON, BUTTON_HOVER, DIM, FG, FIELD, FONT, SLIDER, TAB


TAB_PADDING = (14, 7)


class SettingsWindow:
    def __init__(self, overlay):
        self.ov, self.S = overlay, overlay.S
        root = overlay.root
        w = self.win = tk.Toplevel(root)
        w.title("MapleReader – Settings"); w.configure(bg=BG); w.resizable(False, False)
        w.attributes("-topmost", True)
        w.geometry(f"+{root.winfo_x() + 30}+{root.winfo_y() + 40}")
        self.style = self._style()
        self.nb = ttk.Notebook(w); self.nb.pack(fill="both", expand=True, padx=14, pady=(14, 6))
        self.webhook_status, self.presence_status = tk.StringVar(), tk.StringVar()
        for build in (self._general, self._rates, self._appearance, self._graph, self._data, self._discord):
            build()
        w.bind("<Destroy>", lambda e: root.after(30, overlay.fix_stack) if e.widget is w else None)
        foot = tk.Frame(w, bg=BG); foot.pack(fill="x", padx=14, pady=(0, 12))
        tk.Label(foot, text="Changes apply instantly and are saved automatically.", bg=BG, fg=DIM, font=(FONT, 9)).pack(side="left")
        ttk.Button(foot, text="Close", command=w.destroy).pack(side="right")

    # ---- window
    def exists(self):
        try: return bool(self.win.winfo_exists())
        except tk.TclError: return False

    def show(self):
        self.win.deiconify(); self.win.lift()

    def destroy(self):
        if self.exists(): self.win.destroy()

    def set_discord_status(self, webhook, presence):
        self.webhook_status.set(webhook); self.presence_status.set(presence)

    def _style(self):
        st = ttk.Style(self.win); st.theme_use("clam")
        acc = self.S["accent"]
        st.configure(".", background=BG, foreground=FG, fieldbackground=FIELD, bordercolor=BORDER,
                     lightcolor=BG, darkcolor=BG, troughcolor=FIELD, font=(FONT, 10), focuscolor=BG)
        st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
        st.configure("TNotebook.Tab", background=TAB, foreground=DIM, padding=TAB_PADDING, borderwidth=0)
        # clam gives the selected tab other padding and stretches it; keep every tab the same size
        # so the tabs don't shift when one is clicked
        st.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", FG)],
               padding=[("selected", TAB_PADDING)], expand=[("selected", (0, 0, 0, 0))])
        st.configure("TCheckbutton", background=BG, foreground=FG, indicatorbackground=FIELD, indicatorforeground=FG)
        st.configure("TRadiobutton", background=BG, foreground=FG, indicatorbackground=FIELD)
        self._accent_indicators(st, acc)
        st.configure("TButton", background=BUTTON, foreground=FG, padding=(12, 6), borderwidth=0)
        st.map("TButton", background=[("active", BUTTON_HOVER)])
        st.configure("TSpinbox", arrowsize=12, padding=3)
        st.configure("TEntry", insertcolor=FG, padding=4)
        st.configure("TCombobox", padding=4, arrowcolor=FG, background=BUTTON)
        st.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)],
               selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", FG)],
               background=[("readonly", BUTTON), ("active", BUTTON_HOVER)])
        w = self.win
        w.option_add("*TCombobox*Listbox.background", FIELD); w.option_add("*TCombobox*Listbox.foreground", FG)
        w.option_add("*TCombobox*Listbox.selectBackground", BUTTON_HOVER); w.option_add("*TCombobox*Listbox.selectForeground", FG)
        st.configure("Sec.TLabel", foreground=DIM, font=(FONT, 9))
        st.configure("Hint.TLabel", foreground=DIM, font=(FONT, 9))
        st.configure("Horizontal.TScale", background=SLIDER, troughcolor=FIELD, bordercolor=FIELD, lightcolor=SLIDER, darkcolor=SLIDER)
        return st

    @staticmethod
    def _accent_indicators(st, color):
        st.map("TCheckbutton", background=[("active", BG)], indicatorbackground=[("selected", color)])
        st.map("TRadiobutton", background=[("active", BG)], indicatorbackground=[("selected", color)])

    # ---- building blocks
    def _changed(self):
        self.ov.apply()

    def page(self, title):
        f = ttk.Frame(self.nb, padding=(18, 16)); self.nb.add(f, text=title); return f

    def head(self, f, text, row):
        ttk.Label(f, text=text.upper(), style="Sec.TLabel").grid(row=row, column=0, columnspan=4, sticky="w", pady=(12 if row else 0, 4))

    def hint(self, f, row, text, wrap=400, pady=0):
        ttk.Label(f, text=text, style="Hint.TLabel", wraplength=wrap, justify="left").grid(row=row, column=0, columnspan=4, sticky="w", pady=pady)

    def row_frame(self, f, row, column=0, span=None, padx=0, pady=3):
        """a frame for widgets packed side by side, spanning the rest of the row unless `span` says"""
        fr = tk.Frame(f, bg=BG); fr.grid(row=row, column=column, columnspan=span or 4 - column, sticky="w", padx=padx, pady=pady)
        return fr

    def bvar(self, key, after=None):
        v = tk.BooleanVar(value=self.S[key])
        def cb(*_):
            self.S[key] = v.get(); self._changed()
            if after: after()
        v.trace_add("write", cb); return v

    def ivar(self, key, lo, hi):
        v = tk.IntVar(value=self.S[key])
        def cb(*_):
            try: x = int(v.get())
            except (tk.TclError, ValueError): return
            self.S[key] = min(max(x, lo), hi); self._changed()
        v.trace_add("write", cb); return v

    def svar(self, key):
        v = tk.StringVar(value=self.S[key])
        def cb(*_): self.S[key] = v.get().strip(); self._changed()
        v.trace_add("write", cb); return v

    def check(self, f, row, text, key, after=None, pady=3):
        ttk.Checkbutton(f, text=text, variable=self.bvar(key, after)).grid(row=row, column=0, sticky="w", pady=pady, columnspan=4)

    def spin(self, f, row, label, key, lo, hi, unit=None, span=1):
        """label | [number] unit   (`span`: grid columns the number and unit may take)"""
        ttk.Label(f, text=label).grid(row=row, column=0, sticky="w", pady=3)
        fr = self.row_frame(f, row, column=1, span=span, padx=(10, 0), pady=0)
        ttk.Spinbox(fr, from_=lo, to=hi, width=5, textvariable=self.ivar(key, lo, hi)).pack(side="left")
        if unit: ttk.Label(fr, text=unit).pack(side="left", padx=(6, 0))

    def choice(self, f, row, label, key, options, column=1):
        """label | (o) a  (o) b ...  on one row; options: [(key, text)]"""
        if label: ttk.Label(f, text=label).grid(row=row, column=0, sticky="w", pady=(6, 3))
        v = tk.StringVar(value=self.S[key])
        def cb(*_): self.S[key] = v.get(); self._changed()
        for i, (k, text) in enumerate(options):
            ttk.Radiobutton(f, text=text, variable=v, value=k, command=cb).grid(row=row, column=column + i, sticky="w", padx=(10, 0), pady=(6, 3))

    def slider(self, f, row, label, key, lo, hi, fmt=lambda v: f"{v:.0f}%", scale=100.0):
        ttk.Label(f, text=label).grid(row=row, column=0, sticky="w", pady=4)
        v = tk.DoubleVar(value=self.S[key] * scale); t = tk.StringVar(value=fmt(self.S[key] * scale))
        def cb(*_):
            self.S[key] = v.get() / scale; t.set(fmt(v.get())); self._changed()
        ttk.Scale(f, from_=lo, to=hi, variable=v, command=cb, length=190).grid(row=row, column=1, columnspan=2, sticky="w", padx=(10, 6))
        ttk.Label(f, textvariable=t, width=5).grid(row=row, column=3, sticky="w")

    def swatches(self, f, row, colors, key, after=None):
        fr = self.row_frame(f, row, pady=4)
        items = []
        def paint():
            for c, c_ in items:
                c_.delete("all")
                c_.create_oval(3, 3, 25, 25, fill=c, outline=FG if c.lower() == self.S[key].lower() else BG, width=2)
        def pick(c):
            self.S[key] = c; self._changed(); paint()
            if after: after(c)
        for _, c in colors:
            c_ = tk.Canvas(fr, width=28, height=28, bg=BG, highlightthickness=0, cursor="hand2")
            c_.pack(side="left", padx=2); c_.bind("<Button-1>", lambda e, c=c: pick(c)); items.append((c, c_))
        paint()

    def radios(self, f, row, label, key, options, cols=4):
        """label, then the options in a grid below it; options: [(text, value)]"""
        ttk.Label(f, text=label).grid(row=row, column=0, sticky="w", pady=(6, 3))
        v = tk.StringVar(value=str(self.S[key]))
        def cb(*_): self.S[key] = type(DEFAULTS[key])(v.get()); self._changed()
        for i, (text, val) in enumerate(options):
            ttk.Radiobutton(f, text=text, variable=v, value=str(val), command=cb).grid(row=row + 1 + i // cols, column=i % cols, sticky="w", padx=(0, 12), pady=2)

    def combo(self, f, key, options, width):
        """a drop-down showing the descriptions of `options` ({key: description})"""
        v = tk.StringVar(value=options[self.S[key]])
        cb = ttk.Combobox(f, textvariable=v, values=list(options.values()), state="readonly", width=width)
        def pick(*_):
            self.S[key] = next(k for k, d in options.items() if d == v.get()); self._changed(); cb.selection_clear()
        cb.bind("<<ComboboxSelected>>", pick)
        return cb

    # ---- pages
    def _general(self):
        g = self.page("General")
        self.head(g, "Window", 0)
        self.check(g, 1, "Always on top", "topmost")
        self.check(g, 2, "Lock position (disable dragging)", "lock_position")
        self.check(g, 3, "Show character name", "show_name")
        self.head(g, "Session", 4)
        self.check(g, 5, "Start a new session when the character changes", "reset_on_char")
        self.head(g, "Reading", 6)
        self.spin(g, 7, "Screen reads per second", "reads_per_sec", 2, 20)
        self.hint(g, 8, "Higher = EXP updates sooner, slightly more CPU.")

    def _rates(self):
        r, S = self.page("Rates"), self.S
        self.hint(r, 0, "Choose which columns are shown, what each one displays, and how many minutes it covers.", pady=(0, 10))
        self.rate_vars = []
        descriptions = {k: d for k, (_, d) in KINDS.items()}
        for i in range(4):
            on = tk.BooleanVar(value=S["rate_on"][i]); mn = tk.IntVar(value=S["rate_minutes"][i])
            def cb(*_, i=i, on=on, mn=mn):
                S["rate_on"][i] = on.get()
                try: S["rate_minutes"][i] = min(max(int(mn.get()), 0), 720)
                except (tk.TclError, ValueError): return
                self._changed()
            kv = tk.StringVar(value=descriptions[S["rate_kind"][i]])
            def kcb(*_, i=i, kv=kv):
                S["rate_kind"][i] = next(k for k, d in descriptions.items() if d == kv.get()); self._changed()
            kv.trace_add("write", kcb)
            on.trace_add("write", cb); mn.trace_add("write", cb); self.rate_vars += [on, mn, kv]
            ttk.Combobox(r, state="readonly", width=34, textvariable=kv,
                         values=list(descriptions.values())).grid(row=i + 1, column=3, padx=(14, 0))
            ttk.Checkbutton(r, text=f"Column {i + 1}", variable=on).grid(row=i + 1, column=0, sticky="w", pady=5)
            ttk.Spinbox(r, from_=0, to=720, width=6, textvariable=mn).grid(row=i + 1, column=1, padx=(14, 6))
            ttk.Label(r, text="minutes").grid(row=i + 1, column=2, sticky="w")
        self.check(r, 6, "Dim the numbers until the window has filled up", "rate_dim", pady=(14, 0))
        self.hint(r, 7, "A dimmed number is based on less data than its header says (less time than the window covers since your first EXP gain). Headers are never dimmed. Set minutes to 0 to cover the whole session (since your first EXP gain; nothing is kept between runs).", wrap=560)

    def _appearance(self):
        ap = self.page("Appearance")
        self.head(ap, "Text colour", 0)
        self.swatches(ap, 1, TEXT_COLORS, "text_color")
        self.radios(ap, 2, "Text size", "font_scale", FONT_SCALES)
        self.check(ap, 5, "Text shadow (helps text stand out)", "text_shadow", pady=(6, 2))
        self.head(ap, "Accent colour", 6)
        self.swatches(ap, 7, ACCENTS, "accent", lambda c: self._accent_indicators(self.style, c))
        self.head(ap, "Opacity", 8)
        self.slider(ap, 9, "Background", "bg_opacity", 0, 100)
        self.slider(ap, 10, "Text", "fg_opacity", 20, 100)
        self.head(ap, "Number format", 11)
        self.combo(ap, "number_format", NUMBER_FORMATS, 28).grid(row=12, column=0, columnspan=4, sticky="w", pady=4)

    def _graph(self):
        gr = self.page("Graph")
        self.head(gr, "Display", 0)
        self.check(gr, 1, "Show graph", "graph", after=self.ov.resize)
        self.choice(gr, 2, "Plots", "mode", [(k, label) for k, (_, label) in GRAPH_MODES.items()])
        self.head(gr, "EXP per hour", 3)
        self.spin(gr, 4, "Rate over the last", "graph_rate_minutes", 1, 60, "minutes", span=3)
        self.check(gr, 5, "Also show the session average (dashed line)", "graph_avg")
        self.hint(gr, 6, "A short window shows every change of pace; a longer one is calmer. Above the dashed line you are beating your session average.")
        self.head(gr, "Line", 7)
        v = tk.StringVar(value=self.S["graph_style"])
        def set_style(*_): self.S["graph_style"] = v.get(); self._changed()
        for i, (k, label) in enumerate(GRAPH_STYLES.items()):
            ttk.Radiobutton(gr, text=label, variable=v, value=k, command=set_style).grid(row=8 + i, column=0, columnspan=4, sticky="w", pady=2)
        self.hint(gr, 11, "Stepped shows exactly when EXP arrived; straight joins the points; smooth averages them out. The EXP per hour graph is never stepped.", pady=(2, 0))
        self.slider(gr, 12, "Line thickness", "graph_width", 1, 4, fmt=lambda v: f"{v:.0f}px", scale=1.0)
        self.slider(gr, 13, "Line opacity", "graph_opacity", 0, 100)
        self.head(gr, "Fill", 14)
        self.check(gr, 15, "Fill the area under the line", "graph_fill")
        self.slider(gr, 16, "Fill opacity", "fill_opacity", 0, 100)

    def _data(self):
        d, ov = self.page("Data"), self.ov
        self.head(d, "Logging", 0)
        self.check(d, 1, "Save every EXP change to maple_log.csv", "log_csv")
        ttk.Button(d, text="Open data folder", command=ov.open_data_folder).grid(row=2, column=0, sticky="w", pady=(8, 3), columnspan=2)
        self.head(d, "Actions", 3)
        ttk.Button(d, text="Reset session now", command=ov.reset).grid(row=4, column=0, sticky="w", pady=3)
        ttk.Button(d, text="Reset window position", command=ov.reset_position).grid(row=4, column=1, sticky="w", padx=(10, 0), pady=3)
        self.head(d, "Defaults", 5)
        ttk.Button(d, text="Restore default settings", command=ov.restore_defaults).grid(row=6, column=0, sticky="w", pady=3, columnspan=2)

    def _discord(self):
        dc = self.page("Discord")
        self.head(dc, "Channel webhook", 0)
        self.hint(dc, 1, "Posts to a Discord channel. In Discord: Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL, then paste it here. It is hidden because anyone with it can post to the channel.", wrap=470, pady=(0, 4))
        ttk.Entry(dc, textvariable=self.svar("discord_webhook"), show="•", width=58).grid(row=2, column=0, columnspan=4, sticky="w", pady=4)
        self.check(dc, 3, "Post when you level up", "discord_levelups")
        self.check(dc, 4, "Attach a screenshot of the game to level-up posts", "discord_screenshot")
        self.hint(dc, 5, "Only the MapleStory window is captured, never anything else on the screen. If it can't be "
                         "captured on its own, the post goes without a picture. Mind that chat shows in the picture.", wrap=470, pady=(0, 4))
        self.check(dc, 6, "Post a summary when a session ends (5+ minutes of EXP)", "discord_sessions")
        self.hint(dc, 7, "A session ends when you reset it, switch character, or quit.", wrap=470, pady=(0, 4))
        tf = self.row_frame(dc, 8, pady=(4, 0))
        ttk.Button(tf, text="Send test message", command=self.ov.discord_test).pack(side="left")
        ttk.Label(tf, textvariable=self.webhook_status, style="Hint.TLabel", wraplength=330, justify="left").pack(side="left", padx=(10, 0))
        self.head(dc, "Rich Presence", 9)
        self.hint(dc, 10, "Shows your level, EXP per hour and session time on your Discord profile. Needs the Discord app running on this computer, "
                          "and the Application ID of an application you create at discord.com/developers/applications. "
                          "Discord shows the application's name after \u201cPlaying\u201d, so naming it MapleStory works well.", wrap=470, pady=(0, 4))
        self.check(dc, 11, "Show on my Discord profile", "discord_presence")
        af = self.row_frame(dc, 12)
        ttk.Label(af, text="Application ID").pack(side="left")
        ttk.Entry(af, textvariable=self.svar("discord_app_id"), width=24).pack(side="left", padx=(10, 0))
        ttk.Label(dc, textvariable=self.presence_status, style="Hint.TLabel").grid(row=13, column=0, columnspan=4, sticky="w", pady=(4, 0))
