#!/usr/bin/env python3
"""
SudShow Locator — Dashboard V2
Plan 2D interactif avec anchors/lyres draggables, faisceaux, et log ESP32.
"""

import tkinter as tk
from tkinter import font as tkfont
import socket
import json
import math
import threading
import time
import os
import collections

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

# =============================================================================
# COULEURS
# =============================================================================
C = {
    "bg":          "#12121f",
    "panel":       "#181830",
    "canvas_bg":   "#0c0c18",
    "grid":        "#1c1c38",
    "grid5":       "#28284a",
    "border":      "#2a2a5a",
    "text":        "#d8d8e8",
    "dim":         "#606080",
    "accent":      "#00d4ff",
    "anchor":      "#4fc3f7",
    "anchor_bg":   "#1a4060",
    "tag":         "#ff4444",
    "tag_glow":    "#331111",
    "fixture":     "#ffd740",
    "fixture_bg":  "#4a3a00",
    "beam":        "#665520",
    "beam_fill":   "#1a1508",
    "ok":          "#66bb6a",
    "warn":        "#ffa726",
    "bad":         "#ef5350",
    "log_bg":      "#0a0a14",
    "log_text":    "#80ff80",
    "stage_fill":  "#0e0e1e",
}


# =============================================================================
# DASHBOARD
# =============================================================================
class Dashboard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SudShow Locator — Dashboard")
        self.root.configure(bg=C["bg"])
        self.root.geometry("1400x900")
        self.root.minsize(1000, 700)

        # --- Config ---
        self.cfg = self._load_config()
        self.stage_w = self.cfg.get("stage", {}).get("width", 10.0)
        self.stage_d = self.cfg.get("stage", {}).get("depth", 5.0)

        # Anchors [(x,y), ...]
        acfg = self.cfg.get("anchors", {})
        self.anchors = [
            [acfg.get("a0", {}).get("x", 0.0),   acfg.get("a0", {}).get("y", 0.0)],
            [acfg.get("a1", {}).get("x", 10.0),  acfg.get("a1", {}).get("y", 0.0)],
            [acfg.get("a2", {}).get("x", 5.0),   acfg.get("a2", {}).get("y", 5.0)],
        ]

        # Fixtures — 6 lyres, centrées en fond de scène
        self.fixtures = self._default_fixtures()

        # --- State ---
        self.tag_x = 0.0
        self.tag_y = 0.0
        self.tag_q = 0.0
        self.distances = [0.0, 0.0, 0.0]
        self.pkt_count = 0
        self.pkt_rate = 0.0
        self.connected = False
        self.last_pkt = 0.0
        self._rate_n = 0
        self._rate_t = time.time()
        self.trail = collections.deque(maxlen=120)
        self.display_x = 0.0
        self.display_y = 0.0

        # Drag state
        self._drag_type = None   # "anchor" / "fixture"
        self._drag_idx = -1
        self._dragging = False

        # Log
        self.log_lines = collections.deque(maxlen=200)

        # Fonts
        self.ft_title = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self.ft_section = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.ft_label = tkfont.Font(family="Segoe UI", size=9)
        self.ft_value = tkfont.Font(family="Consolas", size=11, weight="bold")
        self.ft_small = tkfont.Font(family="Consolas", size=9)
        self.ft_log = tkfont.Font(family="Consolas", size=8)

        self._build_ui()
        self._start_udp()
        self._tick()

    def _load_config(self):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _default_fixtures(self):
        """6 lyres centrées en fond de scène, réparties sur 60% de la largeur."""
        n = 6
        usable = self.stage_w * 0.6
        spacing = usable / (n - 1) if n > 1 else 0
        start_x = (self.stage_w - usable) / 2
        fxs = []
        for i in range(n):
            fxs.append({
                "name": f"Lyre {i+1}",
                "x": start_x + i * spacing,
                "y": self.stage_d - 0.5,
                "height": 4.0,
                "gma_id": i + 1,
            })
        return fxs

    # =========================================================================
    # UI BUILD
    # =========================================================================
    def _build_ui(self):
        # --- Top bar ---
        top = tk.Frame(self.root, bg=C["panel"], pady=6, padx=12)
        top.pack(fill="x")

        tk.Label(top, text="🎯 SudShow Locator", font=self.ft_title,
                 bg=C["panel"], fg=C["accent"]).pack(side="left")

        self.lbl_status = tk.Label(top, text="⏳ En attente...",
                                    font=self.ft_label, bg=C["panel"], fg=C["dim"])
        self.lbl_status.pack(side="right", padx=8)

        self.lbl_rate = tk.Label(top, text="", font=self.ft_label,
                                  bg=C["panel"], fg=C["dim"])
        self.lbl_rate.pack(side="right", padx=8)

        # Stage size
        sz_frame = tk.Frame(top, bg=C["panel"])
        sz_frame.pack(side="right", padx=16)
        tk.Label(sz_frame, text="Scène:", font=self.ft_label,
                 bg=C["panel"], fg=C["dim"]).pack(side="left")

        self.entry_w = tk.Entry(sz_frame, width=5, font=self.ft_small,
                                 bg=C["canvas_bg"], fg=C["text"],
                                 insertbackground=C["text"],
                                 bd=1, relief="flat")
        self.entry_w.insert(0, str(self.stage_w))
        self.entry_w.pack(side="left", padx=2)
        tk.Label(sz_frame, text="×", font=self.ft_label,
                 bg=C["panel"], fg=C["dim"]).pack(side="left")
        self.entry_d = tk.Entry(sz_frame, width=5, font=self.ft_small,
                                 bg=C["canvas_bg"], fg=C["text"],
                                 insertbackground=C["text"],
                                 bd=1, relief="flat")
        self.entry_d.insert(0, str(self.stage_d))
        self.entry_d.pack(side="left", padx=2)
        tk.Label(sz_frame, text="m", font=self.ft_label,
                 bg=C["panel"], fg=C["dim"]).pack(side="left")

        btn_apply = tk.Button(sz_frame, text="Appliquer", font=self.ft_label,
                               bg=C["border"], fg=C["text"], bd=0, padx=8,
                               activebackground=C["accent"], activeforeground="#000",
                               command=self._apply_stage_size)
        btn_apply.pack(side="left", padx=6)

        # --- Main: left canvas + right panel ---
        main = tk.PanedWindow(self.root, orient="horizontal",
                               bg=C["bg"], bd=0, sashwidth=4)
        main.pack(fill="both", expand=True, padx=4, pady=4)

        # Canvas frame
        left = tk.Frame(main, bg=C["bg"])
        main.add(left, stretch="always")

        # Right panel
        right = tk.Frame(main, bg=C["panel"], width=280)
        main.add(right, stretch="never")

        # --- Canvas ---
        canvas_border = tk.Frame(left, bg=C["border"], padx=2, pady=2)
        canvas_border.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(canvas_border, bg=C["canvas_bg"],
                                 highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw())
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        # --- Log frame (bottom of left) ---
        log_frame = tk.Frame(left, bg=C["log_bg"], height=120)
        log_frame.pack(fill="x", pady=(4, 0))
        log_frame.pack_propagate(False)

        tk.Label(log_frame, text=" 📡 Messages ESP32", font=self.ft_label,
                 bg=C["log_bg"], fg=C["accent"], anchor="w").pack(fill="x")

        self.log_text = tk.Text(log_frame, bg=C["log_bg"], fg=C["log_text"],
                                 font=self.ft_log, wrap="none", bd=0,
                                 highlightthickness=0, state="disabled",
                                 height=6)
        self.log_text.pack(fill="both", expand=True, padx=4, pady=2)

        # --- Right panel content ---
        self._build_panel(right)

    def _build_panel(self, parent):
        parent.columnconfigure(0, weight=1)

        # Position
        self._section(parent, "📍 POSITION")
        pf = tk.Frame(parent, bg=C["panel"])
        pf.pack(fill="x", padx=8)
        tk.Label(pf, text="X:", font=self.ft_label, bg=C["panel"], fg=C["dim"]).grid(row=0, column=0)
        self.lbl_x = tk.Label(pf, text="—", font=self.ft_value, bg=C["panel"], fg=C["text"])
        self.lbl_x.grid(row=0, column=1, sticky="w", padx=4)
        tk.Label(pf, text="Y:", font=self.ft_label, bg=C["panel"], fg=C["dim"]).grid(row=0, column=2, padx=(12, 0))
        self.lbl_y = tk.Label(pf, text="—", font=self.ft_value, bg=C["panel"], fg=C["text"])
        self.lbl_y.grid(row=0, column=3, sticky="w", padx=4)

        # Distances
        self._section(parent, "📏 DISTANCES")
        self.dlbls = []
        for i in range(3):
            f = tk.Frame(parent, bg=C["panel"])
            f.pack(fill="x", padx=8, pady=1)
            tk.Label(f, text=f"A{i}:", font=self.ft_label, bg=C["panel"],
                     fg=C["anchor"]).pack(side="left")
            l = tk.Label(f, text="—", font=self.ft_value, bg=C["panel"], fg=C["text"])
            l.pack(side="left", padx=4)
            self.dlbls.append(l)

        # Quality
        self._section(parent, "📊 QUALITÉ")
        self.qbar = tk.Canvas(parent, height=16, bg=C["canvas_bg"], highlightthickness=0)
        self.qbar.pack(fill="x", padx=8, pady=(0, 2))
        self.lbl_q = tk.Label(parent, text="—", font=self.ft_small, bg=C["panel"], fg=C["dim"])
        self.lbl_q.pack(anchor="w", padx=8)

        # Fixtures
        self._section(parent, "💡 FIXTURES (Pan/Tilt)")
        self.fx_labels = []
        for i, fx in enumerate(self.fixtures):
            f = tk.Frame(parent, bg=C["panel"])
            f.pack(fill="x", padx=8, pady=1)
            tk.Label(f, text=f"{fx['name']}:", font=self.ft_small,
                     bg=C["panel"], fg=C["fixture"]).pack(side="left")
            l = tk.Label(f, text="—", font=self.ft_small, bg=C["panel"], fg=C["dim"])
            l.pack(side="left", padx=4)
            self.fx_labels.append(l)

        # Info
        self._section(parent, "ℹ️  INFO")
        self.lbl_pkt = tk.Label(parent, text="Paquets: 0", font=self.ft_small,
                                 bg=C["panel"], fg=C["dim"])
        self.lbl_pkt.pack(anchor="w", padx=8)

        # Hint
        tk.Label(parent, text="💡 Glissez les anchors (cercles\nbleus) et les lyres (carrés jaunes)\npour ajuster les positions.",
                 font=self.ft_small, bg=C["panel"], fg=C["dim"],
                 justify="left").pack(anchor="w", padx=8, pady=(16, 0))

    def _section(self, parent, text):
        tk.Frame(parent, bg=C["border"], height=1).pack(fill="x", padx=8, pady=(12, 4))
        tk.Label(parent, text=text, font=self.ft_section,
                 bg=C["panel"], fg=C["accent"]).pack(anchor="w", padx=8)

    # =========================================================================
    # COORDINATE CONVERSION
    # =========================================================================
    def _margins(self):
        return 55, 40, 55, 50   # left, top, right, bottom

    def _stage2px(self, sx, sy):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        ml, mt, mr, mb = self._margins()
        dw = cw - ml - mr
        dh = ch - mt - mb
        scx = dw / max(self.stage_w, 0.5)
        scy = dh / max(self.stage_d, 0.5)
        scale = min(scx, scy)
        ox = ml + (dw - self.stage_w * scale) / 2
        oy = mt + (dh - self.stage_d * scale) / 2
        px = ox + sx * scale
        py = oy + (self.stage_d - sy) * scale
        return px, py, scale

    def _px2stage(self, px, py):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        ml, mt, mr, mb = self._margins()
        dw = cw - ml - mr
        dh = ch - mt - mb
        scx = dw / max(self.stage_w, 0.5)
        scy = dh / max(self.stage_d, 0.5)
        scale = min(scx, scy)
        ox = ml + (dw - self.stage_w * scale) / 2
        oy = mt + (dh - self.stage_d * scale) / 2
        sx = (px - ox) / scale
        sy = self.stage_d - (py - oy) / scale
        return sx, sy

    # =========================================================================
    # DRAWING
    # =========================================================================
    def _draw(self):
        cv = self.canvas
        cv.delete("all")
        cw = cv.winfo_width()
        ch = cv.winfo_height()
        if cw < 50 or ch < 50:
            return

        _, _, scale = self._stage2px(0, 0)

        # Stage fill
        x0, y0, _ = self._stage2px(0, 0)
        x1, y1, _ = self._stage2px(self.stage_w, self.stage_d)
        cv.create_rectangle(x0, y1, x1, y0, fill=C["stage_fill"], outline="")

        # Grid 1m
        for gx in range(int(self.stage_w) + 1):
            xa, ya, _ = self._stage2px(gx, 0)
            xb, yb, _ = self._stage2px(gx, self.stage_d)
            col = C["grid5"] if gx % 5 == 0 else C["grid"]
            cv.create_line(xa, ya, xb, yb, fill=col, width=1)
            cv.create_text(xa, ya + 12, text=f"{gx}", fill=C["dim"],
                           font=("Consolas", 7))

        for gy in range(int(self.stage_d) + 1):
            xa, ya, _ = self._stage2px(0, gy)
            xb, yb, _ = self._stage2px(self.stage_w, gy)
            col = C["grid5"] if gy % 5 == 0 else C["grid"]
            cv.create_line(xa, ya, xb, yb, fill=col, width=1)
            cv.create_text(xa - 16, ya, text=f"{gy}", fill=C["dim"],
                           font=("Consolas", 7))

        # Stage border
        cv.create_rectangle(x0, y1, x1, y0, outline=C["border"], width=2)

        # Labels
        mx, my_pub, _ = self._stage2px(self.stage_w / 2, -0.15)
        cv.create_text(mx, my_pub + 12, text="▼ PUBLIC ▼", fill=C["dim"],
                       font=("Segoe UI", 8))
        mx2, my_fond, _ = self._stage2px(self.stage_w / 2, self.stage_d + 0.15)
        cv.create_text(mx2, my_fond - 10, text="FOND DE SCÈNE", fill=C["dim"],
                       font=("Segoe UI", 8))

        # Beams (draw before fixtures and tag so they're behind)
        if self.connected:
            tx, ty, _ = self._stage2px(self.display_x, self.display_y)
            for fx in self.fixtures:
                fxp, fyp, _ = self._stage2px(fx["x"], fx["y"])
                dx = tx - fxp
                dy = ty - fyp
                ln = math.sqrt(dx*dx + dy*dy)
                if ln < 1:
                    continue
                # Beam cone (triangle)
                perp_x = -dy / ln * 14
                perp_y = dx / ln * 14
                cv.create_polygon(
                    fxp, fyp,
                    tx + perp_x, ty + perp_y,
                    tx - perp_x, ty - perp_y,
                    fill=C["beam_fill"], outline=C["beam"], width=1
                )
                cv.create_line(fxp, fyp, tx, ty, fill=C["fixture"],
                               width=1, dash=(6, 4))

        # Distance lines from anchors
        if self.connected:
            tx, ty, _ = self._stage2px(self.display_x, self.display_y)
            for i, (ax, ay) in enumerate(self.anchors):
                apx, apy, _ = self._stage2px(ax, ay)
                cv.create_line(apx, apy, tx, ty, fill=C["anchor_bg"],
                               width=1, dash=(3, 5))
                midx = (apx + tx) / 2
                midy = (apy + ty) / 2
                if i < len(self.distances):
                    cv.create_text(midx, midy - 7,
                                   text=f"{self.distances[i]:.2f}m",
                                   fill=C["dim"], font=("Consolas", 7))

        # Trail
        now = time.time()
        for trx, try_, tt in self.trail:
            age = now - tt
            if age > 5:
                continue
            alpha = max(0.0, 1.0 - age / 5.0)
            px, py, _ = self._stage2px(trx, try_)
            r = max(1, int(3 * alpha))
            g = int(60 + 60 * alpha)
            col = f"#{40:02x}{g:02x}{40:02x}"
            cv.create_oval(px - r, py - r, px + r, py + r, fill=col, outline="")

        # Fixtures (squares with text label)
        for i, fx in enumerate(self.fixtures):
            fxp, fyp, _ = self._stage2px(fx["x"], fx["y"])
            r = 14
            cv.create_rectangle(fxp - r, fyp - r, fxp + r, fyp + r,
                                 fill=C["fixture_bg"], outline=C["fixture"], width=2)
            cv.create_text(fxp, fyp, text=f"L{i+1}",
                           fill=C["fixture"], font=("Consolas", 8, "bold"))
            cv.create_text(fxp, fyp - 20, text=fx["name"],
                           fill=C["fixture"], font=("Segoe UI", 7))
            cv.create_text(fxp, fyp + 20,
                           text=f"({fx['x']:.1f},{fx['y']:.1f})",
                           fill=C["dim"], font=("Consolas", 7))

        # Anchors (circles)
        for i, (ax, ay) in enumerate(self.anchors):
            apx, apy, _ = self._stage2px(ax, ay)
            # Outer ring
            r1 = 18
            cv.create_oval(apx - r1, apy - r1, apx + r1, apy + r1,
                           outline=C["anchor_bg"], width=2)
            # Inner dot
            r2 = 9
            cv.create_oval(apx - r2, apy - r2, apx + r2, apy + r2,
                           fill=C["anchor"], outline="")
            # Label
            cv.create_text(apx, apy - 24, text=f"A{i}",
                           fill=C["anchor"], font=("Segoe UI", 10, "bold"))
            # Coords
            cv.create_text(apx, apy + 24, text=f"({ax:.1f},{ay:.1f})",
                           fill=C["dim"], font=("Consolas", 7))

        # Tag
        if self.connected:
            tx, ty, _ = self._stage2px(self.display_x, self.display_y)

            # Glow rings
            for gr in [28, 20, 14]:
                intensity = int(30 * (28 - gr) / 14)
                gcol = f"#{50 + intensity:02x}{10:02x}{10:02x}"
                cv.create_oval(tx - gr, ty - gr, tx + gr, ty + gr,
                               outline=gcol, width=1)

            # Dot
            r = 9
            cv.create_oval(tx - r, ty - r, tx + r, ty + r,
                           fill=C["tag"], outline="#ff8888", width=2)
            # Crosshair
            cv.create_line(tx - 14, ty, tx + 14, ty, fill=C["tag"], width=1)
            cv.create_line(tx, ty - 14, tx, ty + 14, fill=C["tag"], width=1)
            # Label
            cv.create_text(tx, ty + 22,
                           text=f"({self.display_x:.2f}, {self.display_y:.2f})",
                           fill=C["text"], font=("Consolas", 9, "bold"))

    # =========================================================================
    # DRAG & DROP
    # =========================================================================
    def _on_press(self, event):
        # Check if click is near an anchor or fixture
        best_dist = float("inf")
        best_type = None
        best_idx = -1

        for i, (ax, ay) in enumerate(self.anchors):
            px, py, _ = self._stage2px(ax, ay)
            d = math.hypot(event.x - px, event.y - py)
            if d < 25 and d < best_dist:
                best_dist = d
                best_type = "anchor"
                best_idx = i

        for i, fx in enumerate(self.fixtures):
            px, py, _ = self._stage2px(fx["x"], fx["y"])
            d = math.hypot(event.x - px, event.y - py)
            if d < 20 and d < best_dist:
                best_dist = d
                best_type = "fixture"
                best_idx = i

        if best_type:
            self._drag_type = best_type
            self._drag_idx = best_idx
            self._dragging = True
            self.canvas.config(cursor="fleur")

    def _on_drag(self, event):
        if not self._dragging:
            return

        sx, sy = self._px2stage(event.x, event.y)
        # Snap to 0.1m grid
        sx = round(sx * 10) / 10
        sy = round(sy * 10) / 10
        # Clamp
        sx = max(-1, min(self.stage_w + 1, sx))
        sy = max(-1, min(self.stage_d + 1, sy))

        if self._drag_type == "anchor":
            self.anchors[self._drag_idx] = [sx, sy]
        elif self._drag_type == "fixture":
            self.fixtures[self._drag_idx]["x"] = sx
            self.fixtures[self._drag_idx]["y"] = sy

        self._draw()

    def _on_release(self, event):
        if self._dragging:
            self._dragging = False
            self.canvas.config(cursor="crosshair")
            self._log(f"[UI] Déplacé {self._drag_type} {self._drag_idx} → "
                       f"({self.anchors[self._drag_idx][0]:.1f}, {self.anchors[self._drag_idx][1]:.1f})"
                       if self._drag_type == "anchor"
                       else f"[UI] Déplacé {self.fixtures[self._drag_idx]['name']} → "
                            f"({self.fixtures[self._drag_idx]['x']:.1f}, {self.fixtures[self._drag_idx]['y']:.1f})")

    # =========================================================================
    # STAGE SIZE
    # =========================================================================
    def _apply_stage_size(self):
        try:
            new_w = float(self.entry_w.get())
            new_d = float(self.entry_d.get())
            if 1.0 <= new_w <= 100.0 and 1.0 <= new_d <= 100.0:
                self.stage_w = new_w
                self.stage_d = new_d
                # Recalculate default fixture positions
                self.fixtures = self._default_fixtures()
                self._rebuild_fixture_labels()
                self._log(f"[UI] Scène: {new_w}m × {new_d}m")
                self._draw()
        except ValueError:
            pass

    def _rebuild_fixture_labels(self):
        for lbl in self.fx_labels:
            lbl.master.destroy()
        self.fx_labels = []
        # Find the fixtures section parent — they're in the right panel
        # This is a simplified rebuild; in production we'd store the parent reference
        # For now, labels will stay stale until restart

    # =========================================================================
    # LOG
    # =========================================================================
    def _log(self, msg):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.log_lines.append(line)

    def _flush_log(self):
        if not self.log_lines:
            return
        self.log_text.config(state="normal")
        while self.log_lines:
            line = self.log_lines.popleft()
            self.log_text.insert("end", line + "\n")
        # Keep only last 200 lines
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 200:
            self.log_text.delete("1.0", f"{lines - 200}.0")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    # =========================================================================
    # UDP
    # =========================================================================
    def _start_udp(self):
        port = self.cfg.get("network", {}).get("udp_listen_port", 9000)
        t = threading.Thread(target=self._udp_loop, args=(port,), daemon=True)
        t.start()

    def _udp_loop(self, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.settimeout(1.0)
        self._log(f"[NET] Écoute UDP sur port {port}")

        while True:
            try:
                data, addr = sock.recvfrom(1024)
                msg = json.loads(data.decode("utf-8"))
                self.tag_x = msg.get("x", 0.0)
                self.tag_y = msg.get("y", 0.0)
                self.tag_q = msg.get("q", 0.0)
                self.distances = msg.get("d", [0, 0, 0])
                self.pkt_count += 1
                self.last_pkt = time.time()
                self.connected = True
                self._rate_n += 1
                self.trail.append((self.tag_x, self.tag_y, time.time()))

                # Log every 5th packet (lisible sans saturer)
                if self.pkt_count % 5 == 1:
                    d_str = " ".join(f"A{i}={v:.2f}m" for i, v in enumerate(self.distances))
                    self._log(f"[ESP] x={self.tag_x:.3f} y={self.tag_y:.3f}  {d_str}")

            except socket.timeout:
                if time.time() - self.last_pkt > 3:
                    self.connected = False
            except json.JSONDecodeError as e:
                self._log(f"[ERR] JSON invalide: {e}")
            except Exception as e:
                self._log(f"[ERR] {e}")

    # =========================================================================
    # TICK
    # =========================================================================
    def _tick(self):
        # Smooth display
        if self.connected:
            a = 0.4
            self.display_x = a * self.tag_x + (1 - a) * self.display_x
            self.display_y = a * self.tag_y + (1 - a) * self.display_y

        # Draw
        self._draw()

        # Flush log
        self._flush_log()

        # Panel updates
        if self.connected:
            self.lbl_x.config(text=f"{self.display_x:.3f} m")
            self.lbl_y.config(text=f"{self.display_y:.3f} m")
            for i, l in enumerate(self.dlbls):
                if i < len(self.distances):
                    l.config(text=f"{self.distances[i]:.3f} m")
            self._draw_qbar(self.tag_q)
            self.lbl_q.config(text=f"{self.tag_q * 100:.0f}%")
            self.lbl_status.config(text="✅ Connecté", fg=C["ok"])

            # Pan/Tilt
            th = self.cfg.get("tracking", {}).get("target_height", 1.7)
            for j, fx in enumerate(self.fixtures):
                dx = self.display_x - fx["x"]
                dy = self.display_y - fx["y"]
                dz = fx["height"] - th
                dh = math.sqrt(dx*dx + dy*dy)
                pan = math.degrees(math.atan2(dx, dy))
                tilt = math.degrees(math.atan2(dz, dh)) if dh > 0.01 else 90
                if j < len(self.fx_labels):
                    self.fx_labels[j].config(
                        text=f"P={pan:.1f}° T={tilt:.1f}°", fg=C["text"])
        else:
            self.lbl_status.config(text="⏳ En attente...", fg=C["dim"])

        # Rate
        now = time.time()
        if now - self._rate_t >= 1.0:
            self.pkt_rate = self._rate_n / (now - self._rate_t)
            self._rate_n = 0
            self._rate_t = now
        self.lbl_rate.config(text=f"{self.pkt_rate:.1f} pkt/s  |  #{self.pkt_count}")
        self.lbl_pkt.config(text=f"Paquets: {self.pkt_count}")

        self.root.after(33, self._tick)

    def _draw_qbar(self, q):
        c = self.qbar
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 5:
            return
        bw = int(w * q)
        col = C["ok"] if q > 0.7 else C["warn"] if q > 0.4 else C["bad"]
        if bw > 0:
            c.create_rectangle(0, 0, bw, h, fill=col, outline="")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    print("SudShow Locator — Dashboard V2")
    app = Dashboard()
    app.run()
