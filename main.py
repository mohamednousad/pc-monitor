import sys
import os
import threading
import time
from datetime import datetime
from collections import deque

import psutil
import customtkinter as ctk
from tkinter import ttk

try:
    import GPUtil
    GPU_AVAILABLE = True
except (ImportError, Exception):
    GPU_AVAILABLE = False

PRIORITY_MAP = {}
try:
    PRIORITY_MAP = {
        psutil.IDLE_PRIORITY_CLASS: "Idle",
        psutil.BELOW_NORMAL_PRIORITY_CLASS: "Below Normal",
        psutil.NORMAL_PRIORITY_CLASS: "Normal",
        psutil.ABOVE_NORMAL_PRIORITY_CLASS: "Above Normal",
        psutil.HIGH_PRIORITY_CLASS: "High",
        psutil.REALTIME_PRIORITY_CLASS: "Realtime",
    }
except AttributeError:
    pass


def format_bytes(b, per_sec=False):
    suffix = "/s" if per_sec else ""
    if b < 1024:
        return f"{b:.0f} B{suffix}"
    if b < 1024 ** 2:
        return f"{b / 1024:.1f} KB{suffix}"
    if b < 1024 ** 3:
        return f"{b / 1024 ** 2:.1f} MB{suffix}"
    return f"{b / 1024 ** 3:.2f} GB{suffix}"


class SystemDataCollector:

    def __init__(self):
        self.cpu_percent = 0.0
        self.cpu_per_core = []
        self.cpu_freq = None
        self.ram = None
        self.swap = None
        self.disk_partitions = []
        self.gpu_info = None
        self.processes = []
        self.diagnostics = []
        self.cpu_history = deque(maxlen=60)
        self.ram_history = deque(maxlen=60)
        self._prev_net = None
        self._prev_disk_io = None
        self._prev_time = None
        self.net_speed = {"sent": 0.0, "recv": 0.0}
        self.disk_speed = {"read": 0.0, "write": 0.0}
        self._lock = threading.Lock()

    def collect_system(self):
        try:
            self.cpu_percent = psutil.cpu_percent(interval=0)
            self.cpu_per_core = psutil.cpu_percent(percpu=True)
            self.cpu_freq = psutil.cpu_freq()
            self.ram = psutil.virtual_memory()
            self.swap = psutil.swap_memory()

            parts = []
            for p in psutil.disk_partitions():
                try:
                    u = psutil.disk_usage(p.mountpoint)
                    parts.append({
                        "device": p.device, "mountpoint": p.mountpoint,
                        "total": u.total, "used": u.used, "free": u.free, "percent": u.percent,
                    })
                except (PermissionError, OSError):
                    pass
            self.disk_partitions = parts

            now = time.time()
            cur_disk = psutil.disk_io_counters()
            cur_net = psutil.net_io_counters()

            if self._prev_time and self._prev_disk_io and self._prev_net:
                dt = now - self._prev_time
                if dt > 0:
                    self.disk_speed = {
                        "read": (cur_disk.read_bytes - self._prev_disk_io.read_bytes) / dt,
                        "write": (cur_disk.write_bytes - self._prev_disk_io.write_bytes) / dt,
                    }
                    self.net_speed = {
                        "recv": (cur_net.bytes_recv - self._prev_net.bytes_recv) / dt,
                        "sent": (cur_net.bytes_sent - self._prev_net.bytes_sent) / dt,
                    }

            self._prev_disk_io = cur_disk
            self._prev_net = cur_net
            self._prev_time = now

            if GPU_AVAILABLE:
                try:
                    gpus = GPUtil.getGPUs()
                    if gpus:
                        g = gpus[0]
                        self.gpu_info = {
                            "name": g.name,
                            "load": g.load * 100,
                            "mem_used": g.memoryUsed,
                            "mem_total": g.memoryTotal,
                            "mem_pct": (g.memoryUsed / g.memoryTotal * 100) if g.memoryTotal > 0 else 0,
                            "temp": g.temperature,
                        }
                    else:
                        self.gpu_info = None
                except Exception:
                    self.gpu_info = None

            self.cpu_history.append(self.cpu_percent)
            self.ram_history.append(self.ram.percent if self.ram else 0)
        except Exception:
            pass

    def collect_processes(self):
        procs = []
        attrs = ["pid", "name", "cpu_percent", "memory_percent", "memory_info",
                 "nice", "create_time", "status"]
        for proc in psutil.process_iter(attrs):
            try:
                info = proc.info
                io = None
                try:
                    io = proc.io_counters()
                except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
                    pass

                net_conns = 0
                try:
                    net_conns = len(proc.connections())
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass

                nice_val = info.get("nice")
                priority = PRIORITY_MAP.get(nice_val, str(nice_val) if nice_val is not None else "N/A")

                ct = info.get("create_time", 0)
                try:
                    start_str = datetime.fromtimestamp(ct).strftime("%Y-%m-%d %H:%M")
                except (ValueError, OSError, OverflowError):
                    start_str = "N/A"

                mem = info.get("memory_info")
                mem_mb = mem.rss / (1024 ** 2) if mem else 0

                procs.append({
                    "pid": info.get("pid", 0),
                    "name": info.get("name", "Unknown"),
                    "cpu": info.get("cpu_percent", 0.0) or 0.0,
                    "mem_pct": info.get("memory_percent", 0.0) or 0.0,
                    "mem_mb": round(mem_mb, 1),
                    "disk_r": io.read_bytes if io else 0,
                    "disk_w": io.write_bytes if io else 0,
                    "net_conns": net_conns,
                    "priority": priority,
                    "start": start_str,
                    "status": info.get("status", "unknown"),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        with self._lock:
            self.processes = sorted(procs, key=lambda x: x["cpu"], reverse=True)

    def run_diagnostics(self):
        issues = []

        if self.cpu_percent > 90:
            issues.append(("CRITICAL", "CPU Usage Extremely High",
                           f"CPU is at {self.cpu_percent:.0f}%. Your system may freeze or become "
                           "unresponsive. Open the Processes tab to find and close resource-heavy "
                           "applications. Background tasks like updates, antivirus scans, or "
                           "runaway processes are common culprits."))
        elif self.cpu_percent > 75:
            issues.append(("WARNING", "High CPU Usage",
                           f"CPU is at {self.cpu_percent:.0f}%. Performance may degrade under "
                           "sustained load. Consider closing applications you are not actively using."))

        if self.ram and self.ram.percent > 90:
            avail = self.ram.available / (1024 ** 3)
            issues.append(("CRITICAL", "Memory Nearly Exhausted",
                           f"RAM usage is {self.ram.percent:.0f}% with only {avail:.1f} GB free. "
                           "Windows is forced to use the page file on disk, which is orders of "
                           "magnitude slower. Close browser tabs and heavy applications. "
                           "Browsers with many tabs are the most common cause."))
        elif self.ram and self.ram.percent > 75:
            issues.append(("WARNING", "Elevated Memory Usage",
                           f"RAM usage is {self.ram.percent:.0f}%. Performance will degrade if "
                           "usage climbs further."))

        for d in self.disk_partitions:
            if d["percent"] > 95:
                issues.append(("CRITICAL", f"Disk Almost Full — {d['device']}",
                               f"{d['device']} is {d['percent']}% full with only "
                               f"{format_bytes(d['free'])} remaining. Low disk space causes "
                               "failed updates, swap file starvation, and application crashes. "
                               "Delete temporary files or move data to free space immediately."))
            elif d["percent"] > 85:
                issues.append(("WARNING", f"Disk Space Low — {d['device']}",
                               f"{d['device']} is {d['percent']}% full. Plan to free space soon."))

        if self.gpu_info:
            if self.gpu_info["load"] > 90:
                issues.append(("WARNING", "High GPU Load",
                               f"{self.gpu_info['name']} is at {self.gpu_info['load']:.0f}% utilization. "
                               "GPU-intensive applications like games, video editors, or crypto miners "
                               "may slow other graphics operations."))
            temp = self.gpu_info.get("temp", 0)
            if temp and temp > 85:
                issues.append(("CRITICAL", "GPU Overheating",
                               f"GPU temperature is {temp}°C. Sustained heat causes thermal "
                               "throttling, reduced performance, and potential hardware damage. "
                               "Check fan operation and case airflow."))

        if self.swap and self.swap.percent > 50:
            issues.append(("WARNING", "Heavy Page File Usage",
                           f"Swap is at {self.swap.percent:.0f}% "
                           f"({format_bytes(self.swap.used)} used). This confirms physical RAM is "
                           "insufficient for the current workload. Disk-backed virtual memory is "
                           "dramatically slower than RAM."))

        with self._lock:
            proc_snap = self.processes[:]

        high_cpu = [p for p in proc_snap if p["cpu"] > 20]
        if high_cpu:
            items = ", ".join(f"{p['name']} ({p['cpu']:.0f}%)" for p in high_cpu[:5])
            issues.append(("INFO", "CPU-Heavy Processes",
                           f"These processes are consuming significant CPU time: {items}. "
                           "If any are unexpected, they may be worth investigating."))

        high_mem = sorted([p for p in proc_snap if p["mem_mb"] > 500],
                          key=lambda x: x["mem_mb"], reverse=True)
        if high_mem:
            items = ", ".join(f"{p['name']} ({p['mem_mb']:.0f} MB)" for p in high_mem[:5])
            issues.append(("INFO", "Memory-Heavy Processes",
                           f"Large memory consumers: {items}. "
                           "Browsers and IDEs with many open files are typical."))

        n = len(proc_snap)
        if n > 300:
            issues.append(("WARNING", f"Very High Process Count ({n})",
                           "Each process carries scheduling overhead. Consider disabling "
                           "unnecessary startup programs via Task Manager → Startup tab."))
        elif n > 200:
            issues.append(("INFO", f"Elevated Process Count ({n})",
                           "Process count is above average. Not necessarily a problem, but worth "
                           "checking for unneeded background services."))

        if not issues:
            issues.append(("OK", "System Running Smoothly",
                           "No performance issues detected. All metrics are within normal limits."))

        with self._lock:
            self.diagnostics = issues


class MetricCard(ctk.CTkFrame):

    def __init__(self, master, title, **kwargs):
        super().__init__(master, corner_radius=12, **kwargs)
        self._title = ctk.CTkLabel(
            self, text=title, font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray30", "gray70"),
        )
        self._title.pack(padx=14, pady=(12, 0), anchor="w")

        self._value = ctk.CTkLabel(self, text="—", font=ctk.CTkFont(size=30, weight="bold"))
        self._value.pack(padx=14, pady=(2, 0), anchor="w")

        self._detail = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
        )
        self._detail.pack(padx=14, pady=(0, 4), anchor="w")

        self._bar = ctk.CTkProgressBar(self, height=8, corner_radius=4)
        self._bar.pack(padx=14, pady=(0, 12), fill="x")
        self._bar.set(0)

    def update(self, value_text, detail_text, fraction):
        self._value.configure(text=value_text)
        self._detail.configure(text=detail_text)
        f = max(0.0, min(1.0, fraction))
        self._bar.set(f)
        if f > 0.9:
            color = "#e74c3c"
        elif f > 0.75:
            color = "#f39c12"
        else:
            color = "#2ecc71"
        self._bar.configure(progress_color=color)


class SpeedCard(ctk.CTkFrame):

    def __init__(self, master, title, **kwargs):
        super().__init__(master, corner_radius=12, **kwargs)
        self._title = ctk.CTkLabel(
            self, text=title, font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray30", "gray70"),
        )
        self._title.pack(padx=14, pady=(12, 4), anchor="w")
        self.line1 = ctk.CTkLabel(self, text="—", font=ctk.CTkFont(size=20, weight="bold"))
        self.line1.pack(padx=14, pady=(2, 0), anchor="w")
        self.line2 = ctk.CTkLabel(self, text="—", font=ctk.CTkFont(size=20, weight="bold"))
        self.line2.pack(padx=14, pady=(2, 12), anchor="w")


class MiniGraph(ctk.CTkFrame):

    def __init__(self, master, title, color="#3498db", **kwargs):
        super().__init__(master, corner_radius=12, **kwargs)
        self._color = color
        label = ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=12, weight="bold"),
                             text_color=("gray30", "gray70"))
        label.pack(padx=14, pady=(10, 2), anchor="w")
        self._canvas = ctk.CTkCanvas(self, height=60, highlightthickness=0,
                                     bg=self._get_bg())
        self._canvas.pack(padx=14, pady=(0, 10), fill="x")
        self._data = deque(maxlen=60)

    def _get_bg(self):
        return "#2b2b2b" if ctk.get_appearance_mode() == "Dark" else "#e8e8e8"

    def set_data(self, data_deque):
        self._data = data_deque
        self._draw()

    def _draw(self):
        c = self._canvas
        c.configure(bg=self._get_bg())
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 10 or h < 10 or len(self._data) < 2:
            return
        pts = list(self._data)
        n = len(pts)
        x_step = w / max(n - 1, 1)
        coords = []
        for i, v in enumerate(pts):
            x = i * x_step
            y = h - (v / 100.0) * h
            coords.append((x, y))
        fill_coords = [(0, h)] + coords + [(w, h)]
        fill_flat = [c for pt in fill_coords for c in pt]
        c.create_polygon(fill_flat, fill=self._color, stipple="gray25", outline="")
        line_flat = [c for pt in coords for c in pt]
        if len(line_flat) >= 4:
            c.create_line(line_flat, fill=self._color, width=2, smooth=True)


class PerformanceMonitorApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("PC Performance Monitor")
        self.geometry("1150x750")
        self.minsize(950, 600)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.collector = SystemDataCollector()
        self._running = True
        self._process_cache_display = []

        self._build_ui()
        self._start_threads()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(self, corner_radius=10)
        self.tabs.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")

        self._tab_dash = self.tabs.add("  Dashboard  ")
        self._tab_proc = self.tabs.add("  Processes  ")
        self._tab_diag = self.tabs.add("  Diagnostics  ")

        self._build_dashboard()
        self._build_processes()
        self._build_diagnostics()

        status = ctk.CTkFrame(self, height=28, corner_radius=0,
                              fg_color=("gray90", "#1a1a1a"))
        status.grid(row=1, column=0, sticky="ew")
        self._status_label = ctk.CTkLabel(
            status, text="Starting up…", font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
        )
        self._status_label.pack(side="left", padx=12, pady=2)
        self._appearance_btn = ctk.CTkButton(
            status, text="☀ Light", width=70, height=22,
            font=ctk.CTkFont(size=11), command=self._toggle_appearance,
        )
        self._appearance_btn.pack(side="right", padx=8, pady=2)

    def _toggle_appearance(self):
        if ctk.get_appearance_mode() == "Dark":
            ctk.set_appearance_mode("light")
            self._appearance_btn.configure(text="🌙 Dark")
        else:
            ctk.set_appearance_mode("dark")
            self._appearance_btn.configure(text="☀ Light")

    def _build_dashboard(self):
        tab = self._tab_dash
        tab.grid_columnconfigure((0, 1, 2), weight=1, uniform="col")

        self.card_cpu = MetricCard(tab, "CPU USAGE")
        self.card_cpu.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")

        self.card_ram = MetricCard(tab, "MEMORY (RAM)")
        self.card_ram.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")

        self.card_disk = MetricCard(tab, "PRIMARY DISK")
        self.card_disk.grid(row=0, column=2, padx=5, pady=5, sticky="nsew")

        self.card_gpu = MetricCard(tab, "GPU")
        self.card_gpu.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")

        self.card_net = SpeedCard(tab, "NETWORK")
        self.card_net.grid(row=1, column=1, padx=5, pady=5, sticky="nsew")

        self.card_dio = SpeedCard(tab, "DISK I/O")
        self.card_dio.grid(row=1, column=2, padx=5, pady=5, sticky="nsew")

        graph_frame = ctk.CTkFrame(tab, corner_radius=12)
        graph_frame.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="nsew")
        graph_frame.grid_columnconfigure((0, 1), weight=1, uniform="g")
        graph_frame.grid_rowconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        self.graph_cpu = MiniGraph(graph_frame, "CPU HISTORY (60s)", color="#3498db")
        self.graph_cpu.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")

        self.graph_ram = MiniGraph(graph_frame, "RAM HISTORY (60s)", color="#e67e22")
        self.graph_ram.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")

        info_frame = ctk.CTkFrame(tab, corner_radius=12)
        info_frame.grid(row=2, column=2, padx=5, pady=5, sticky="nsew")
        self._info_label = ctk.CTkLabel(
            info_frame, text="Collecting data…",
            font=ctk.CTkFont(size=11), justify="left", anchor="nw",
        )
        self._info_label.pack(padx=12, pady=10, fill="both", expand=True, anchor="nw")

    def _build_processes(self):
        tab = self._tab_proc
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(tab, corner_radius=8, height=44)
        toolbar.grid(row=0, column=0, padx=5, pady=(5, 2), sticky="ew")

        self._search_var = ctk.StringVar()
        ctk.CTkEntry(
            toolbar, placeholder_text="Filter processes…",
            textvariable=self._search_var, width=240,
        ).pack(side="left", padx=8, pady=8)

        self._proc_count = ctk.CTkLabel(toolbar, text="", font=ctk.CTkFont(size=11))
        self._proc_count.pack(side="right", padx=8, pady=8)

        self._sort_var = ctk.StringVar(value="CPU %")
        ctk.CTkOptionMenu(
            toolbar, variable=self._sort_var, width=130,
            values=["CPU %", "Memory %", "Memory MB", "Name", "PID", "Disk I/O"],
        ).pack(side="right", padx=4, pady=8)
        ctk.CTkLabel(toolbar, text="Sort:", font=ctk.CTkFont(size=11)).pack(
            side="right", padx=(8, 0), pady=8)

        tree_frame = ctk.CTkFrame(tab, corner_radius=8)
        tree_frame.grid(row=1, column=0, padx=5, pady=(2, 5), sticky="nsew")
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        cols = ("pid", "name", "cpu", "mem_pct", "mem_mb", "disk_io",
                "net", "priority", "start", "status")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=20)

        heads = {
            "pid": "PID", "name": "Process Name", "cpu": "CPU %",
            "mem_pct": "RAM %", "mem_mb": "RAM (MB)", "disk_io": "Disk I/O",
            "net": "Net", "priority": "Priority",
            "start": "Started", "status": "Status",
        }
        widths = {
            "pid": 58, "name": 195, "cpu": 60, "mem_pct": 60, "mem_mb": 78,
            "disk_io": 135, "net": 50, "priority": 90, "start": 125, "status": 68,
        }
        for c in cols:
            self._tree.heading(c, text=heads[c])
            a = "w" if c == "name" else "center"
            self._tree.column(c, width=widths[c], anchor=a, minwidth=40)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._apply_tree_style()

    def _apply_tree_style(self):
        s = ttk.Style()
        s.theme_use("default")
        s.configure(
            "Treeview", background="#2b2b2b", foreground="white",
            fieldbackground="#2b2b2b", borderwidth=0,
            font=("Segoe UI", 10), rowheight=26,
        )
        s.configure(
            "Treeview.Heading", background="#1f1f1f", foreground="white",
            font=("Segoe UI", 10, "bold"), borderwidth=0, relief="flat",
        )
        s.map("Treeview", background=[("selected", "#1a73e8")])
        s.configure("Vertical.TScrollbar", background="#3b3b3b", troughcolor="#2b2b2b")

    def _build_diagnostics(self):
        tab = self._tab_diag
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        self._diag_scroll = ctk.CTkScrollableFrame(tab, corner_radius=10)
        self._diag_scroll.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self._diag_scroll.grid_columnconfigure(0, weight=1)
        self._diag_cards = []

    def _start_threads(self):
        def sys_loop():
            psutil.cpu_percent(interval=0)
            time.sleep(0.5)
            while self._running:
                self.collector.collect_system()
                time.sleep(2)

        def proc_loop():
            for p in psutil.process_iter(["cpu_percent"]):
                try:
                    p.cpu_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            time.sleep(1.5)
            while self._running:
                self.collector.collect_processes()
                time.sleep(3)

        def diag_loop():
            time.sleep(6)
            while self._running:
                self.collector.run_diagnostics()
                time.sleep(8)

        for fn in (sys_loop, proc_loop, diag_loop):
            threading.Thread(target=fn, daemon=True).start()

        self._tick()

    def _tick(self):
        if not self._running:
            return
        try:
            self._refresh_dashboard()
            self._refresh_processes()
            self._refresh_diagnostics()
            ts = datetime.now().strftime("%H:%M:%S")
            self._status_label.configure(text=f"Last update: {ts}")
        except Exception:
            pass
        self.after(2000, self._tick)

    def _refresh_dashboard(self):
        c = self.collector

        freq = f"{c.cpu_freq.current:.0f} MHz" if c.cpu_freq else ""
        threads = psutil.cpu_count(logical=True) or "?"
        self.card_cpu.update(f"{c.cpu_percent:.1f}%",
                             f"{freq}  •  {threads} threads",
                             c.cpu_percent / 100)

        if c.ram:
            used = c.ram.used / (1024 ** 3)
            total = c.ram.total / (1024 ** 3)
            self.card_ram.update(f"{c.ram.percent:.1f}%",
                                f"{used:.1f} / {total:.1f} GB",
                                c.ram.percent / 100)

        if c.disk_partitions:
            d = c.disk_partitions[0]
            self.card_disk.update(
                f"{d['percent']:.0f}%",
                f"{format_bytes(d['used'])} / {format_bytes(d['total'])}  •  {d['device']}",
                d["percent"] / 100,
            )

        if c.gpu_info:
            g = c.gpu_info
            temp_str = f"  •  {g['temp']}°C" if g.get("temp") else ""
            self.card_gpu.update(f"{g['load']:.0f}%",
                                f"{g['name']}{temp_str}",
                                g["load"] / 100)
        else:
            self.card_gpu.update("N/A", "No compatible GPU detected", 0)

        self.card_net.line1.configure(
            text=f"↓  {format_bytes(c.net_speed['recv'], True)}")
        self.card_net.line2.configure(
            text=f"↑  {format_bytes(c.net_speed['sent'], True)}")

        self.card_dio.line1.configure(
            text=f"Read   {format_bytes(c.disk_speed['read'], True)}")
        self.card_dio.line2.configure(
            text=f"Write  {format_bytes(c.disk_speed['write'], True)}")

        self.graph_cpu.set_data(c.cpu_history)
        self.graph_ram.set_data(c.ram_history)

        phys = psutil.cpu_count(logical=False) or "?"
        logical = psutil.cpu_count(logical=True) or "?"
        boot = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M")
        cores = "  ".join(f"C{i}:{v:.0f}%" for i, v in enumerate(c.cpu_per_core[:6]))
        if len(c.cpu_per_core) > 6:
            cores += f"  +{len(c.cpu_per_core) - 6}"
        nt = psutil.net_io_counters()
        extras = ""
        if len(c.disk_partitions) > 1:
            extras = "\n" + "  |  ".join(
                f"{d['device']} {d['percent']}%" for d in c.disk_partitions[1:4])
        self._info_label.configure(
            text=(f"Cores: {phys}P / {logical}L\n"
                  f"Boot: {boot}\n"
                  f"Per-core: {cores}\n"
                  f"Net total: ↓{format_bytes(nt.bytes_recv)} "
                  f"↑{format_bytes(nt.bytes_sent)}"
                  f"{extras}"))

    def _refresh_processes(self):
        with self.collector._lock:
            procs = self.collector.processes[:]

        filt = self._search_var.get().lower().strip()
        if filt:
            procs = [p for p in procs if filt in p["name"].lower() or filt in str(p["pid"])]

        sort_key = self._sort_var.get()
        key_map = {
            "CPU %": ("cpu", True), "Memory %": ("mem_pct", True),
            "Memory MB": ("mem_mb", True), "Name": ("name", False),
            "PID": ("pid", False), "Disk I/O": ("disk_r", True),
        }
        k, rev = key_map.get(sort_key, ("cpu", True))
        try:
            procs.sort(key=lambda x: x.get(k, 0) if isinstance(x.get(k, 0), (int, float))
                       else str(x.get(k, "")).lower(), reverse=rev)
        except TypeError:
            pass

        scroll = self._tree.yview()
        self._tree.delete(*self._tree.get_children())

        for p in procs:
            dio = f"R:{format_bytes(p['disk_r'])} W:{format_bytes(p['disk_w'])}"
            tags = ("high",) if (p["cpu"] > 25 or p["mem_mb"] > 500) else ()
            self._tree.insert("", "end", values=(
                p["pid"], p["name"], f"{p['cpu']:.1f}", f"{p['mem_pct']:.1f}",
                f"{p['mem_mb']:.0f}", dio, p["net_conns"],
                p["priority"], p["start"], p["status"],
            ), tags=tags)

        self._tree.tag_configure("high", foreground="#ff6b6b")
        try:
            self._tree.yview_moveto(scroll[0])
        except Exception:
            pass

        self._proc_count.configure(text=f"{len(procs)} processes")

    def _refresh_diagnostics(self):
        with self.collector._lock:
            diags = self.collector.diagnostics[:]
        if not diags:
            return

        for w in self._diag_cards:
            w.destroy()
        self._diag_cards.clear()

        colors = {"CRITICAL": "#e74c3c", "WARNING": "#f39c12",
                  "INFO": "#3498db", "OK": "#2ecc71"}
        icons = {"CRITICAL": "⛔", "WARNING": "⚠️", "INFO": "ℹ️", "OK": "✅"}

        for severity, title, desc in diags:
            card = ctk.CTkFrame(
                self._diag_scroll, corner_radius=10,
                border_width=2, border_color=colors.get(severity, "#555"),
            )
            card.grid(sticky="ew", padx=4, pady=4)
            card.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                card,
                text=f"  {icons.get(severity, '')}   {title}",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=colors.get(severity, "white"), anchor="w",
            ).pack(padx=14, pady=(10, 2), anchor="w")

            ctk.CTkLabel(
                card, text=desc, font=ctk.CTkFont(size=12),
                wraplength=850, justify="left", anchor="nw",
                text_color=("gray20", "gray80"),
            ).pack(padx=14, pady=(2, 10), anchor="w", fill="x")

            self._diag_cards.append(card)

    def _on_close(self):
        self._running = False
        self.destroy()


if __name__ == "__main__":
    app = PerformanceMonitorApp()
    app.mainloop()
