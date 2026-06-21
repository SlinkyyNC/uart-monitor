"""
main.py
UART Serial Monitor & Protocol Analyser
Main application window built with tkinter + matplotlib.

Layout:
  - Top bar: port selector, baud rate, connect/disconnect, sim mode
  - Left panel: live terminal log with colour-coded message types
  - Right panel: live plot of extracted numeric values
  - Bottom bar: send command input + stats counter
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import collections
import sys
import os

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.ticker as ticker

sys.path.insert(0, os.path.dirname(__file__))
from core.parser import parse
from core.simulator import UARTSimulator

try:
    from core.serial_reader import SerialReader, list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

# ── Colour scheme ──────────────────────────────────────────────────────────────
BG       = "#0d1117"
SURFACE  = "#161b22"
BORDER   = "#21262d"
TEXT     = "#e6edf3"
MUTED    = "#7d8590"
GREEN    = "#69db7c"
YELLOW   = "#ffd43b"
RED      = "#ff6b6b"
BLUE     = "#4fc3f7"
ORANGE   = "#ff7b54"

TYPE_COLOURS = {
    "SENSOR": GREEN,
    "STATUS": BLUE,
    "DUMP":   YELLOW,
    "ERROR":  RED,
    "RAW":    MUTED,
}

PLOT_COLOURS = [GREEN, ORANGE, BLUE, YELLOW, RED, "#c084fc"]

MAX_POINTS = 80
MAX_LOG    = 500


class UARTMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("UART Serial Monitor")
        self.root.configure(bg=BG)
        self.root.geometry("1200x750")
        self.root.minsize(900, 600)

        self._reader = None
        self._sim    = None
        self._connected = False
        self._lock   = threading.Lock()

        # Data stores
        self._plot_data   = collections.defaultdict(lambda: collections.deque(maxlen=MAX_POINTS))
        self._plot_keys   = []
        self._msg_counts  = collections.defaultdict(int)
        self._total       = 0

        self._build_ui()
        self._refresh_ports()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_toolbar()
        self._build_main()
        self._build_statusbar()

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=SURFACE, pady=8, padx=12)
        bar.pack(fill=tk.X, side=tk.TOP)

        tk.Label(bar, text="Port", bg=SURFACE, fg=MUTED,
                 font=("Consolas", 9)).pack(side=tk.LEFT, padx=(0, 4))

        self._port_var = tk.StringVar(value="SIMULATOR")
        self._port_cb  = ttk.Combobox(bar, textvariable=self._port_var,
                                       width=14, state="readonly")
        self._port_cb.pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(bar, text="Baud", bg=SURFACE, fg=MUTED,
                 font=("Consolas", 9)).pack(side=tk.LEFT, padx=(0, 4))

        self._baud_var = tk.StringVar(value="115200")
        ttk.Combobox(bar, textvariable=self._baud_var, width=8, state="readonly",
                     values=["9600","19200","38400","57600","115200","230400","460800","921600"]
                     ).pack(side=tk.LEFT, padx=(0, 10))

        self._btn_connect = tk.Button(bar, text="Connect", bg=GREEN, fg=BG,
                                       font=("Consolas", 9, "bold"),
                                       relief=tk.FLAT, padx=12, pady=4,
                                       command=self._toggle_connect)
        self._btn_connect.pack(side=tk.LEFT, padx=(0, 10))

        tk.Button(bar, text="⟳ Refresh Ports", bg=SURFACE, fg=MUTED,
                  font=("Consolas", 9), relief=tk.FLAT, padx=8, pady=4,
                  command=self._refresh_ports).pack(side=tk.LEFT)

        tk.Button(bar, text="Clear Log", bg=SURFACE, fg=MUTED,
                  font=("Consolas", 9), relief=tk.FLAT, padx=8, pady=4,
                  command=self._clear_log).pack(side=tk.LEFT, padx=(6, 0))

        # Status pill (right side)
        self._status_var = tk.StringVar(value="● Disconnected")
        tk.Label(bar, textvariable=self._status_var, bg=SURFACE, fg=RED,
                 font=("Consolas", 9, "bold")).pack(side=tk.RIGHT, padx=8)

    def _build_main(self):
        pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=BG,
                              sashwidth=6, sashrelief=tk.FLAT)
        pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # ── Left: terminal log ─────────────────────────────────────────────
        left = tk.Frame(pane, bg=SURFACE, bd=1, relief=tk.FLAT)
        pane.add(left, minsize=400)

        tk.Label(left, text="SERIAL OUTPUT", bg=SURFACE, fg=MUTED,
                 font=("Consolas", 8), anchor="w", padx=8, pady=6).pack(fill=tk.X)

        # Tabs: Raw / Hex / ASCII
        self._tab = ttk.Notebook(left)
        self._tab.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        self._log_raw   = self._make_log_tab("Raw")
        self._log_hex   = self._make_log_tab("Hex")
        self._log_ascii = self._make_log_tab("ASCII")

        # Colour tags
        for widget in [self._log_raw, self._log_hex, self._log_ascii]:
            for t, c in TYPE_COLOURS.items():
                widget.tag_config(t, foreground=c)

        # ── Right: live plot ───────────────────────────────────────────────
        right = tk.Frame(pane, bg=SURFACE)
        pane.add(right, minsize=350)

        tk.Label(right, text="LIVE PLOT — numeric values", bg=SURFACE, fg=MUTED,
                 font=("Consolas", 8), anchor="w", padx=8, pady=6).pack(fill=tk.X)

        self._fig = Figure(figsize=(5, 4), dpi=96, facecolor=SURFACE)
        self._ax  = self._fig.add_subplot(111)
        self._style_ax()

        self._canvas = FigureCanvasTkAgg(self._fig, master=right)
        self._canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))

        # Stats row
        stats = tk.Frame(right, bg=SURFACE)
        stats.pack(fill=tk.X, padx=6, pady=(0, 6))

        self._stats_var = tk.StringVar(value="Waiting for data…")
        tk.Label(stats, textvariable=self._stats_var, bg=SURFACE, fg=MUTED,
                 font=("Consolas", 8), anchor="w").pack(side=tk.LEFT)

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=SURFACE, pady=6, padx=12)
        bar.pack(fill=tk.X, side=tk.BOTTOM)

        tk.Label(bar, text="TX ›", bg=SURFACE, fg=MUTED,
                 font=("Consolas", 9)).pack(side=tk.LEFT, padx=(0, 6))

        self._send_var = tk.StringVar()
        entry = tk.Entry(bar, textvariable=self._send_var, bg=BG, fg=TEXT,
                         insertbackground=TEXT, font=("Consolas", 10),
                         relief=tk.FLAT, width=40)
        entry.pack(side=tk.LEFT, padx=(0, 6))
        entry.bind("<Return>", lambda e: self._send_command())

        tk.Button(bar, text="Send", bg=BLUE, fg=BG, font=("Consolas", 9, "bold"),
                  relief=tk.FLAT, padx=10, command=self._send_command).pack(side=tk.LEFT)

        self._count_var = tk.StringVar(value="0 messages")
        tk.Label(bar, textvariable=self._count_var, bg=SURFACE, fg=MUTED,
                 font=("Consolas", 8)).pack(side=tk.RIGHT)

    def _make_log_tab(self, label):
        frame = tk.Frame(self._tab, bg=BG)
        self._tab.add(frame, text=label)
        widget = scrolledtext.ScrolledText(
            frame, bg=BG, fg=TEXT, font=("Consolas", 9),
            relief=tk.FLAT, state=tk.DISABLED, wrap=tk.NONE
        )
        widget.pack(fill=tk.BOTH, expand=True)
        return widget

    def _style_ax(self):
        ax = self._ax
        ax.set_facecolor(BG)
        ax.tick_params(colors=MUTED, labelsize=8)
        ax.spines["bottom"].set_color(BORDER)
        ax.spines["left"].set_color(BORDER)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.1f"))
        ax.set_xlabel("Samples", color=MUTED, fontsize=8)
        self._fig.tight_layout(pad=1.5)

    # ── Port management ────────────────────────────────────────────────────────

    def _refresh_ports(self):
        ports = ["SIMULATOR"]
        if SERIAL_AVAILABLE:
            ports += list_ports()
        self._port_cb["values"] = ports
        if self._port_var.get() not in ports:
            self._port_var.set("SIMULATOR")

    # ── Connect / disconnect ───────────────────────────────────────────────────

    def _toggle_connect(self):
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        port = self._port_var.get()
        baud = int(self._baud_var.get())

        if port == "SIMULATOR":
            self._sim = UARTSimulator(callback=self._on_line)
            self._sim.start()
        else:
            if not SERIAL_AVAILABLE:
                messagebox.showerror("Error", "pyserial not installed.\nRun: pip install pyserial")
                return
            try:
                self._reader = SerialReader(port, baud, self._on_line, self._on_error)
                self._reader.connect()
            except Exception as e:
                messagebox.showerror("Connection failed", str(e))
                return

        self._connected = True
        self._btn_connect.config(text="Disconnect", bg=RED, fg=BG)
        self._status_var.set(f"● Connected — {port} @ {baud}")
        self.root.nametowidget(self._status_var)  # force label colour update
        self._update_status_colour(GREEN)

    def _disconnect(self):
        if self._sim:
            self._sim.stop()
            self._sim = None
        if self._reader:
            self._reader.disconnect()
            self._reader = None
        self._connected = False
        self._btn_connect.config(text="Connect", bg=GREEN, fg=BG)
        self._status_var.set("● Disconnected")
        self._update_status_colour(RED)

    def _update_status_colour(self, colour):
        for w in self.root.winfo_children():
            if isinstance(w, tk.Frame):
                for c in w.winfo_children():
                    if isinstance(c, tk.Label) and "Connected" in (self._status_var.get()):
                        c.config(fg=colour)

    def _on_error(self, msg):
        self.root.after(0, lambda: messagebox.showerror("Serial error", msg))
        self.root.after(0, self._disconnect)

    # ── Data handling ──────────────────────────────────────────────────────────

    def _on_line(self, line: str):
        parsed = parse(line)
        self.root.after(0, lambda p=parsed: self._update_ui(p))

    def _update_ui(self, p):
        self._total += 1
        self._msg_counts[p["type"]] += 1
        self._append_log(p)
        self._update_plot(p)
        self._update_stats()

    def _append_log(self, p):
        tag  = p["type"]
        ts   = p["timestamp"]

        def write(widget, text):
            widget.config(state=tk.NORMAL)
            widget.insert(tk.END, f"[{ts}] ", "RAW")
            widget.insert(tk.END, text + "\n", tag)
            # trim
            lines = int(widget.index("end-1c").split(".")[0])
            if lines > MAX_LOG:
                widget.delete("1.0", f"{lines - MAX_LOG}.0")
            widget.see(tk.END)
            widget.config(state=tk.DISABLED)

        write(self._log_raw,   p["raw"])
        write(self._log_hex,   p["hex"])
        write(self._log_ascii, p["ascii"])

    def _update_plot(self, p):
        nums = p["numerics"]
        if not nums:
            return

        for key, val in nums.items():
            self._plot_data[key].append(val)
            if key not in self._plot_keys:
                self._plot_keys.append(key)

        self._ax.cla()
        self._style_ax()

        for i, key in enumerate(self._plot_keys[:6]):
            data = list(self._plot_data[key])
            colour = PLOT_COLOURS[i % len(PLOT_COLOURS)]
            self._ax.plot(data, color=colour, linewidth=1.5, label=key)

        self._ax.legend(loc="upper left", fontsize=7,
                        facecolor=SURFACE, edgecolor=BORDER,
                        labelcolor=TEXT)
        self._canvas.draw_idle()

    def _update_stats(self):
        parts = " · ".join(f"{t}:{n}" for t, n in self._msg_counts.items())
        self._stats_var.set(parts)
        self._count_var.set(f"{self._total} messages")

    def _send_command(self):
        cmd = self._send_var.get().strip()
        if not cmd:
            return
        if self._reader:
            self._reader.send(cmd)
        # Echo to log
        self._on_line(f"[TX] {cmd}")
        self._send_var.set("")

    def _clear_log(self):
        for w in [self._log_raw, self._log_hex, self._log_ascii]:
            w.config(state=tk.NORMAL)
            w.delete("1.0", tk.END)
            w.config(state=tk.DISABLED)
        with self._lock:
            self._plot_data.clear()
            self._plot_keys.clear()
            self._msg_counts.clear()
            self._total = 0
        self._ax.cla()
        self._style_ax()
        self._canvas.draw_idle()
        self._stats_var.set("Waiting for data…")
        self._count_var.set("0 messages")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()

    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TCombobox", fieldbackground=BG, background=SURFACE,
                    foreground=TEXT, selectbackground=SURFACE,
                    selectforeground=TEXT, bordercolor=BORDER)
    style.configure("TNotebook", background=SURFACE, bordercolor=BORDER)
    style.configure("TNotebook.Tab", background=BORDER, foreground=MUTED,
                    padding=[10, 4])
    style.map("TNotebook.Tab", background=[("selected", BG)],
              foreground=[("selected", TEXT)])

    app = UARTMonitorApp(root)
    root.mainloop()
