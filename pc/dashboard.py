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
        self.stage_h = self.cfg.get("stage", {}).get("height", 3.0)
        self.target_z = self.cfg.get("tracking", {}).get("target_height", 1.7)

        # Anchors [(x,y,z), ...]
        acfg = self.cfg.get("anchors", {})
        self.anchors = [
            [acfg.get("a0", {}).get("x", 0.0),   acfg.get("a0", {}).get("y", 0.0),   acfg.get("a0", {}).get("z", 2.0)],
            [acfg.get("a1", {}).get("x", 10.0),  acfg.get("a1", {}).get("y", 0.0),   acfg.get("a1", {}).get("z", 2.0)],
            [acfg.get("a2", {}).get("x", 5.0),   acfg.get("a2", {}).get("y", 5.0),   acfg.get("a2", {}).get("z", 2.0)],
        ]

        # Fixtures
        cfg_fixtures = self.cfg.get("fixtures", [])
        if cfg_fixtures:
            self.fixtures = cfg_fixtures
            defaults_list = self._default_fixtures()
            def_fx = defaults_list[0]
            
            # Apply defaults for any missing advanced parameters
            for fx in self.fixtures:
                for k, v in def_fx.items():
                    if k not in fx:
                        fx[k] = v
                        
            # (Removed the forced padding to 6 fixtures to allow dynamic count)
        else:
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
        self.esp32_ip = None

        # --- Velocity prediction (dead-reckoning between UWB packets) ---
        self._pos_history = collections.deque(maxlen=5)  # (x, y, t)
        self._vel_x = 0.0   # m/s estimated
        self._vel_y = 0.0
        self._last_predict_t = time.time()

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
        self.ft_large_btn = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        
        self.test_mode = tk.BooleanVar(value=False)
        self.group_toggles = {i: True for i in range(1, 6)}

        # Telnet MA2 state
        self.ma2_socket = None
        self.ma2_connected = False
        self.ma2_targets = {}  # {gma_id: (pan, tilt)}
        self.ma2_lock = threading.Lock()

        # Battery monitoring
        self.bat_voltage = 0.0
        # Historique: (timestamp, voltage) — 1 sample/2s = 3600 samples pour 2h
        self.bat_history = collections.deque(maxlen=3600)

        self._build_ui()
        self._start_udp()
        self._start_telnet()
        self._start_heartbeat()
        self._tick()

    def _load_config(self):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_config(self):
        """Sauvegarde la config courante (scène, anchors, fixtures) dans config.json."""
        # Charger le fichier existant pour préserver les champs non gérés
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

        # Mettre à jour les champs gérés par le dashboard
        data["stage"] = {"width": self.stage_w, "depth": self.stage_d, "height": self.stage_h}
        data["anchors"] = {
            f"a{i}": {"x": round(a[0], 2), "y": round(a[1], 2), "z": round(a[2], 2)}
            for i, a in enumerate(self.anchors)
        }
        # Mettre à jour les positions des fixtures
        for i, fx in enumerate(self.fixtures):
            fx["x"] = round(fx["x"], 2)
            fx["y"] = round(fx["y"], 2)
            try:
                fx["gma_id"] = int(self.fx_ma2_entries[i].get())
            except:
                pass
            try:
                if hasattr(self, 'fx_grp_entries') and i < len(self.fx_grp_entries):
                    fx["group"] = max(1, min(5, int(self.fx_grp_entries[i].get())))
            except:
                pass
        data["fixtures"] = self.fixtures
        
        data["tracking"] = self.cfg.get("tracking", {})
        data["tracking"]["target_height"] = round(self.target_z, 2)
        
        data["calibration"] = self.cfg.get("calibration", {"a0": 0.8, "a1": 0.8, "a2": 0.8, "alpha": 0.85, "tag_z": 1.0})
        
        # MA2
        try:
            data["ma2"] = {
                "ip": self.ent_ma2_ip.get(),
                "port": int(self.ent_ma2_port.get()),
                "user": self.ent_ma2_user.get(),
                "pass": self.ent_ma2_pass.get()
            }
        except:
            pass

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            self._log("[CFG] ✓ Configuration sauvegardée")
        except Exception as e:
            self._log(f"[CFG] ✗ Erreur sauvegarde: {e}")

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
                "group": 1,
                "x": start_x + i * spacing,
                "y": self.stage_d - 0.5,
                "height": 4.0,
                "gma_id": i + 1,
                "pan_min": 0.0,
                "pan_max": 540.0,
                "pan_offset": 0.0,
                "pan_invert": False,
                "tilt_min": -95.0,
                "tilt_max": 95.0,
                "tilt_offset": 90.0,
                "tilt_invert": False,
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

        # Bouton MA2 dans la top bar
        self.btn_ma2_top = tk.Button(top, text="🎬 MA2", font=self.ft_large_btn,
                                     bg="#aa6600", fg="#fff", bd=0, padx=16, pady=4,
                                     activebackground="#cc8800", activeforeground="#fff",
                                     cursor="hand2",
                                     command=self._toggle_ma2)
        self.btn_ma2_top.pack(side="left", padx=(16, 0))

        # Bouton Manual mode dans la top bar
        self.btn_manual = tk.Button(top, text="✋ Manual", font=self.ft_large_btn,
                                    bg="#555555", fg="#ccc", bd=0, padx=16, pady=4,
                                    activebackground="#777777", activeforeground="#fff",
                                    cursor="hand2",
                                    command=self._toggle_manual)
        self.btn_manual.pack(side="left", padx=(8, 0))
        


        # Bouton pour masquer/afficher le panneau droit
        self.btn_toggle_panel = tk.Button(top, text="[>] Panneau", font=self.ft_label,
                                          bg=C["border"], fg=C["text"], bd=0, padx=10,
                                          activebackground=C["accent"], activeforeground="#000",
                                          cursor="hand2",
                                          command=self._toggle_right_panel)
        self.btn_toggle_panel.pack(side="right", padx=8)



        # Frame pour les boutons de groupes alignés à droite
        grp_frame = tk.Frame(top, bg=C["panel"])
        grp_frame.pack(side="right", padx=(16, 8))
        
        # Boutons de groupes G1-G5
        self.btn_groups = {}
        for i in range(1, 6):
            btn = tk.Button(grp_frame, text=f"G{i}", font=self.ft_large_btn,
                            bd=0, padx=16, pady=4, cursor="hand2",
                            command=lambda grp=i: self._toggle_group(grp))
            btn.pack(side="left", padx=(0, 4) if i < 5 else 0)
            self.btn_groups[i] = btn
            self._update_group_btn_color(i)

        # --- Bandeau du bas ---
        bot = tk.Frame(self.root, bg=C["panel"], pady=2, padx=12)
        bot.pack(side="bottom", fill="x")
        
        # Qualité (tout à droite)
        q_frame = tk.Frame(bot, bg=C["panel"])
        q_frame.pack(side="right", padx=8)
        tk.Label(q_frame, text="Qualité :", font=self.ft_small, bg=C["panel"], fg=C["dim"]).pack(side="left")
        self.qbar = tk.Canvas(q_frame, width=40, height=10, bg=C["canvas_bg"], highlightthickness=0)
        self.qbar.pack(side="left", padx=(4, 0))
        self.lbl_q = tk.Label(q_frame, text="—", font=self.ft_small, bg=C["panel"], fg=C["dim"], width=4, anchor="w")
        self.lbl_q.pack(side="left", padx=(4, 0))

        # Battery voltage label (clickable)
        self.lbl_bat = tk.Label(bot, text="🔋 --", font=self.ft_label,
                                bg=C["panel"], fg=C["dim"], cursor="hand2")
        self.lbl_bat.pack(side="right", padx=8)
        self.lbl_bat.bind("<Button-1>", lambda e: self._show_bat_history())

        # Rate
        self.lbl_rate = tk.Label(bot, text="", font=self.ft_label,
                                  bg=C["panel"], fg=C["dim"])
        self.lbl_rate.pack(side="right", padx=8)

        # ESP32 connection indicator
        self.lbl_esp32 = tk.Label(bot, text="📡 ESP32: --",
                                   font=self.ft_label, bg=C["panel"], fg=C["dim"])
        self.lbl_esp32.pack(side="right", padx=8)

        # Status
        self.lbl_status = tk.Label(bot, text="⏳ En attente...",
                                    font=self.ft_label, bg=C["panel"], fg=C["dim"])
        self.lbl_status.pack(side="right", padx=8)

        # --- Main: left canvas + right panel ---
        self.main_panes = tk.PanedWindow(self.root, orient="horizontal",
                               bg=C["bg"], bd=0, sashwidth=4)
        self.main_panes.pack(fill="both", expand=True, padx=4, pady=4)

        # Canvas frame
        left = tk.Frame(self.main_panes, bg=C["bg"])
        self.main_panes.add(left, stretch="always")

        # Right panel
        self.right_panel = tk.Frame(self.main_panes, bg=C["panel"], width=280)
        self.main_panes.add(self.right_panel, stretch="never")

        # --- Canvases ---
        panes = tk.PanedWindow(left, orient="vertical", bg=C["border"], bd=0, sashwidth=4)
        panes.pack(fill="both", expand=True)

        top_border = tk.Frame(panes, bg=C["border"], padx=2, pady=2)
        panes.add(top_border, stretch="always")
        self.canvas_top = tk.Canvas(top_border, bg=C["canvas_bg"], highlightthickness=0, cursor="crosshair")
        self.canvas_top.pack(fill="both", expand=True)
        self.canvas_top.bind("<Configure>", lambda e: self._draw())
        self.canvas_top.bind("<ButtonPress-1>", lambda e: self._on_press(e, "top"))
        self.canvas_top.bind("<B1-Motion>", lambda e: self._on_drag(e, "top"))
        self.canvas_top.bind("<ButtonRelease-1>", self._on_release)

        front_border = tk.Frame(panes, bg=C["border"], padx=2, pady=2)
        panes.add(front_border, stretch="always")
        self.canvas_front = tk.Canvas(front_border, bg=C["canvas_bg"], highlightthickness=0, cursor="crosshair")
        self.canvas_front.pack(fill="both", expand=True)
        self.canvas_front.bind("<Configure>", lambda e: self._draw())
        self.canvas_front.bind("<ButtonPress-1>", lambda e: self._on_press(e, "front"))
        self.canvas_front.bind("<B1-Motion>", lambda e: self._on_drag(e, "front"))
        self.canvas_front.bind("<ButtonRelease-1>", self._on_release)

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
        self._build_panel(self.right_panel)

    def _build_panel(self, parent):
        parent.columnconfigure(0, weight=1)

        # Stage size & Save (Moved from Top Bar)
        self._section(parent, "📐 SCÈNE & SAUVEGARDE")
        sz_frame = tk.Frame(parent, bg=C["panel"])
        sz_frame.pack(fill="x", padx=8, pady=2)
        
        # Row 1: Dimensions
        f_dim = tk.Frame(sz_frame, bg=C["panel"])
        f_dim.pack(fill="x", pady=2)
        tk.Label(f_dim, text="W:", font=self.ft_small, bg=C["panel"], fg=C["dim"]).pack(side="left")
        self.entry_w = tk.Entry(f_dim, width=4, font=self.ft_small, bg=C["canvas_bg"], fg=C["text"], insertbackground=C["text"], bd=1, relief="flat")
        self.entry_w.insert(0, str(self.stage_w))
        self.entry_w.pack(side="left", padx=1)
        
        tk.Label(f_dim, text="D:", font=self.ft_small, bg=C["panel"], fg=C["dim"]).pack(side="left", padx=(4,0))
        self.entry_d = tk.Entry(f_dim, width=4, font=self.ft_small, bg=C["canvas_bg"], fg=C["text"], insertbackground=C["text"], bd=1, relief="flat")
        self.entry_d.insert(0, str(self.stage_d))
        self.entry_d.pack(side="left", padx=1)
        
        tk.Label(f_dim, text="H:", font=self.ft_small, bg=C["panel"], fg=C["dim"]).pack(side="left", padx=(4,0))
        self.entry_h = tk.Entry(f_dim, width=4, font=self.ft_small, bg=C["canvas_bg"], fg=C["text"], insertbackground=C["text"], bd=1, relief="flat")
        self.entry_h.insert(0, str(self.stage_h))
        self.entry_h.pack(side="left", padx=1)

        # Row 2: Buttons
        f_btns = tk.Frame(sz_frame, bg=C["panel"])
        f_btns.pack(fill="x", pady=4)
        btn_apply = tk.Button(f_btns, text="Appliquer", font=self.ft_label,
                               bg=C["border"], fg=C["text"], bd=0, padx=8,
                               activebackground=C["accent"], activeforeground="#000",
                               command=self._apply_stage_size)
        btn_apply.pack(side="left", fill="x", expand=True, padx=(0, 2))
        
        btn_save = tk.Button(f_btns, text="💾 Sauver", font=self.ft_label,
                              bg=C["border"], fg=C["ok"], bd=0, padx=8,
                              activebackground=C["ok"], activeforeground="#000",
                              command=self._save_config)
        btn_save.pack(side="left", fill="x", expand=True, padx=(2, 0))

        # Position
        self._section(parent, "📍 POSITION")
        pf = tk.Frame(parent, bg=C["panel"])
        pf.pack(fill="x", padx=8)
        tk.Label(pf, text="X:", font=self.ft_label, bg=C["panel"], fg=C["dim"]).grid(row=0, column=0)
        self.lbl_x = tk.Label(pf, text="—", font=self.ft_value, bg=C["panel"], fg=C["text"])
        self.lbl_x.grid(row=0, column=1, sticky="w", padx=4)
        tk.Label(pf, text="Y:", font=self.ft_label, bg=C["panel"], fg=C["dim"]).grid(row=0, column=2, padx=(8, 0))
        self.lbl_y = tk.Label(pf, text="—", font=self.ft_value, bg=C["panel"], fg=C["text"])
        self.lbl_y.grid(row=0, column=3, sticky="w", padx=4)
        tk.Label(pf, text="Z:", font=self.ft_label, bg=C["panel"], fg=C["dim"]).grid(row=0, column=4, padx=(8, 0))
        self.lbl_z = tk.Label(pf, text="—", font=self.ft_value, bg=C["panel"], fg=C["text"])
        self.lbl_z.grid(row=0, column=5, sticky="w", padx=4)

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

        # Fixtures
        self._section(parent, "💡 FIXTURES (Pan/Tilt)")
        self.frm_fixtures = tk.Frame(parent, bg=C["panel"])
        self.frm_fixtures.pack(fill="x")
        self._build_fixtures_list()
        
        btn_add_fx = tk.Button(parent, text="[+] Ajouter Lyre", font=("Segoe UI", 8), bg=C["border"], fg=C["text"], bd=0, command=self._add_fixture)
        btn_add_fx.pack(pady=(2, 8))

        # Cible Z est maintenant ajustable via la vue de face

        # Calibration
        self._section(parent, "🔧 CALIBRATION UWB")
        self.cal_entries = []
        for i in range(3):
            f = tk.Frame(parent, bg=C["panel"])
            f.pack(fill="x", padx=8, pady=1)
            tk.Label(f, text=f"A{i} Offset:", font=self.ft_small, bg=C["panel"], fg=C["dim"]).pack(side="left")
            ent = tk.Entry(f, width=5, font=self.ft_small, bg=C["canvas_bg"], fg=C["text"], insertbackground=C["text"], bd=1)
            off_val = self.cfg.get("calibration", {}).get(f"a{i}", 0.8)
            ent.insert(0, str(off_val))
            ent.pack(side="left", padx=4)
            tk.Label(f, text="m  | Z:", font=self.ft_small, bg=C["panel"], fg=C["dim"]).pack(side="left")
            ent_z = tk.Entry(f, width=5, font=self.ft_small, bg=C["canvas_bg"], fg=C["text"], insertbackground=C["text"], bd=1)
            ent_z.insert(0, str(self.anchors[i][2]))
            ent_z.pack(side="left", padx=4)
            tk.Label(f, text="m", font=self.ft_small, bg=C["panel"], fg=C["dim"]).pack(side="left")
            self.cal_entries.append((ent, ent_z))
            
        f_alpha = tk.Frame(parent, bg=C["panel"])
        f_alpha.pack(fill="x", padx=8, pady=(4, 0))
        tk.Label(f_alpha, text="Lissage:", font=self.ft_small, bg=C["panel"], fg=C["dim"]).pack(side="left")
        self.ent_alpha = tk.Entry(f_alpha, width=5, font=self.ft_small, bg=C["canvas_bg"], fg=C["text"], insertbackground=C["text"], bd=1)
        alpha_val = self.cfg.get("calibration", {}).get("alpha", 0.85)
        self.ent_alpha.insert(0, str(alpha_val))
        self.ent_alpha.pack(side="left", padx=4)
        tk.Label(f_alpha, text="(0.1=Lent)", font=("Segoe UI", 7), bg=C["panel"], fg=C["dim"]).pack(side="left")
        
        f_tag = tk.Frame(parent, bg=C["panel"])
        f_tag.pack(fill="x", padx=8, pady=(2, 4))
        tk.Label(f_tag, text="Tag Z:  ", font=self.ft_small, bg=C["panel"], fg=C["dim"]).pack(side="left")
        self.ent_tag_z = tk.Entry(f_tag, width=5, font=self.ft_small, bg=C["canvas_bg"], fg=C["text"], insertbackground=C["text"], bd=1)
        tag_val = self.cfg.get("calibration", {}).get("tag_z", 1.0)
        self.ent_tag_z.insert(0, str(tag_val))
        self.ent_tag_z.pack(side="left", padx=4)
        tk.Label(f_tag, text="m (Ceinture)", font=("Segoe UI", 7), bg=C["panel"], fg=C["dim"]).pack(side="left")
            
        btn_cal = tk.Button(parent, text="Appliquer Calibration", font=self.ft_small, bg=C["border"], fg=C["accent"], bd=0, activebackground=C["accent"], activeforeground="#000", command=self._send_calibration)
        btn_cal.pack(pady=8)
        
        # GrandMA2 Telnet
        self._section(parent, "🎛️ GRANDMA2 TELNET")
        
        f_ma2_ip = tk.Frame(parent, bg=C["panel"])
        f_ma2_ip.pack(fill="x", padx=8, pady=1)
        tk.Label(f_ma2_ip, text="IP:", font=self.ft_small, bg=C["panel"], fg=C["dim"], width=4, anchor="e").pack(side="left")
        self.ent_ma2_ip = tk.Entry(f_ma2_ip, width=12, font=self.ft_small, bg=C["canvas_bg"], fg=C["text"], insertbackground=C["text"], bd=1)
        self.ent_ma2_ip.insert(0, self.cfg.get("ma2", {}).get("ip", "127.0.0.1"))
        self.ent_ma2_ip.pack(side="left", padx=4)
        
        tk.Label(f_ma2_ip, text="Port:", font=self.ft_small, bg=C["panel"], fg=C["dim"]).pack(side="left")
        self.ent_ma2_port = tk.Entry(f_ma2_ip, width=6, font=self.ft_small, bg=C["canvas_bg"], fg=C["text"], insertbackground=C["text"], bd=1)
        self.ent_ma2_port.insert(0, str(self.cfg.get("ma2", {}).get("port", 30000)))
        self.ent_ma2_port.pack(side="left", padx=4)
        
        f_ma2_auth = tk.Frame(parent, bg=C["panel"])
        f_ma2_auth.pack(fill="x", padx=8, pady=1)
        tk.Label(f_ma2_auth, text="User:", font=self.ft_small, bg=C["panel"], fg=C["dim"], width=4, anchor="e").pack(side="left")
        self.ent_ma2_user = tk.Entry(f_ma2_auth, width=8, font=self.ft_small, bg=C["canvas_bg"], fg=C["text"], insertbackground=C["text"], bd=1)
        self.ent_ma2_user.insert(0, self.cfg.get("ma2", {}).get("user", "administrator"))
        self.ent_ma2_user.pack(side="left", padx=4)
        
        tk.Label(f_ma2_auth, text="Pass:", font=self.ft_small, bg=C["panel"], fg=C["dim"]).pack(side="left")
        self.ent_ma2_pass = tk.Entry(f_ma2_auth, width=8, font=self.ft_small, bg=C["canvas_bg"], fg=C["text"], insertbackground=C["text"], bd=1)
        self.ent_ma2_pass.insert(0, self.cfg.get("ma2", {}).get("pass", "admin"))
        self.ent_ma2_pass.pack(side="left", padx=4)
        
        f_ma2_btn = tk.Frame(parent, bg=C["panel"])
        f_ma2_btn.pack(fill="x", padx=8, pady=(4, 8))
        self.btn_ma2_connect = tk.Button(f_ma2_btn, text="Connecter", font=self.ft_small, bg=C["border"], fg=C["accent"], bd=0, activebackground=C["accent"], activeforeground="#000", command=self._toggle_ma2)
        self.btn_ma2_connect.pack(side="left")
        self.lbl_ma2_status = tk.Label(f_ma2_btn, text="✗ Déconnecté", font=self.ft_small, bg=C["panel"], fg="#ff8888")
        self.lbl_ma2_status.pack(side="left", padx=8)

        # Info
        self._section(parent, "ℹ️  INFO")

                       
        self.lbl_pkt = tk.Label(parent, text="Paquets: 0", font=self.ft_small,
                                 bg=C["panel"], fg=C["dim"])
        self.lbl_pkt.pack(anchor="w", padx=8)
        self.lbl_vel = tk.Label(parent, text="Vitesse: —", font=self.ft_small,
                                 bg=C["panel"], fg=C["dim"])
        self.lbl_vel.pack(anchor="w", padx=8)
        self.lbl_predict = tk.Label(parent, text="", font=self.ft_small,
                                     bg=C["panel"], fg=C["dim"])
        self.lbl_predict.pack(anchor="w", padx=8)

        # Hint
        tk.Label(parent, text="💡 Glissez les anchors (cercles\nbleus) et les lyres (carrés jaunes)\npour ajuster les positions.",
                 font=self.ft_small, bg=C["panel"], fg=C["dim"],
                 justify="left").pack(anchor="w", padx=8, pady=(16, 0))

    def _open_fixture_settings(self, idx):
        fx = self.fixtures[idx]
        top = tk.Toplevel(self.root)
        top.title(f"⚙️ {fx['name']}")
        top.configure(bg=C["bg"])
        top.geometry("280x420")
        top.transient(self.root)
        top.grab_set()

        def _row(parent, label, key, default):
            f = tk.Frame(parent, bg=C["bg"])
            f.pack(fill="x", padx=10, pady=5)
            tk.Label(f, text=label, font=self.ft_label, bg=C["bg"], fg=C["text"], width=14, anchor="w").pack(side="left")
            ent = tk.Entry(f, width=8, font=self.ft_small, bg=C["canvas_bg"], fg=C["text"], insertbackground=C["text"])
            ent.insert(0, str(fx.get(key, default)))
            ent.pack(side="right")
            return ent
            
        def _check(parent, label, key, default):
            f = tk.Frame(parent, bg=C["bg"])
            f.pack(fill="x", padx=10, pady=2)
            var = tk.BooleanVar(value=fx.get(key, default))
            cb = tk.Checkbutton(f, text=label, font=self.ft_label, bg=C["bg"], fg=C["text"],
                                selectcolor=C["canvas_bg"], activebackground=C["bg"],
                                activeforeground=C["text"], variable=var)
            cb.pack(side="left")
            return var

        e_h = _row(top, "Hauteur Z (m)", "height", 4.0)
        e_pmin = _row(top, "Pan Min (°)", "pan_min", 0.0)
        e_pmax = _row(top, "Pan Max (°)", "pan_max", 540.0)
        e_poff = _row(top, "Pan Offset (°)", "pan_offset", 0.0)
        v_pinv = _check(top, "Inverser Pan", "pan_invert", False)
        
        e_tmin = _row(top, "Tilt Min (°)", "tilt_min", -95.0)
        e_tmax = _row(top, "Tilt Max (°)", "tilt_max", 95.0)
        e_toff = _row(top, "Tilt Offset (°)", "tilt_offset", 90.0)
        v_tinv = _check(top, "Inverser Tilt", "tilt_invert", False)
        
        e_grp = _row(top, "Groupe (1-5)", "group", 1)
        
        def _save():
            try:
                fx["height"] = float(e_h.get())
                fx["pan_min"] = float(e_pmin.get())
                fx["pan_max"] = float(e_pmax.get())
                fx["pan_offset"] = float(e_poff.get())
                fx["pan_invert"] = v_pinv.get()
                fx["tilt_min"] = float(e_tmin.get())
                fx["tilt_max"] = float(e_tmax.get())
                fx["tilt_offset"] = float(e_toff.get())
                fx["tilt_invert"] = v_tinv.get()
                fx["group"] = max(1, min(5, int(e_grp.get())))
                self._save_config()
                self._draw()
                top.destroy()
            except ValueError:
                pass
                
        tk.Button(top, text="Sauvegarder", font=self.ft_small, bg=C["border"], fg=C["accent"], bd=0, command=_save).pack(pady=15)

    def _build_fixtures_list(self):
        for widget in self.frm_fixtures.winfo_children():
            widget.destroy()
            
        self.fx_labels = []
        self.fx_ma2_entries = []
        self.fx_grp_entries = []
        
        for i, fx in enumerate(self.fixtures):
            f = tk.Frame(self.frm_fixtures, bg=C["panel"])
            f.pack(fill="x", padx=8, pady=1)
            
            # Trash button
            btn_del = tk.Button(f, text="🗑️", font=("Segoe UI", 8), bg=C["panel"], fg="#ff4444", bd=0, command=lambda idx=i: self._remove_fixture(idx))
            btn_del.pack(side="right", padx=2)
            
            # Gear button
            btn_gear = tk.Button(f, text="⚙️", font=("Segoe UI", 8), bg=C["panel"], fg=C["text"], bd=0, command=lambda idx=i: self._open_fixture_settings(idx))
            btn_gear.pack(side="right", padx=2)
            
            # MA2 ID entry
            tk.Label(f, text="ID:", font=self.ft_small, bg=C["panel"], fg=C["dim"]).pack(side="left")
            ent_id = tk.Entry(f, width=3, font=self.ft_small, bg=C["canvas_bg"], fg=C["text"], insertbackground=C["text"], bd=1)
            ent_id.insert(0, str(fx.get("gma_id", i+1)))
            ent_id.pack(side="left", padx=4)
            self.fx_ma2_entries.append(ent_id)
            
            # Group entry
            tk.Label(f, text=" G:", font=self.ft_small, bg=C["panel"], fg=C["dim"]).pack(side="left")
            ent_grp = tk.Entry(f, width=2, font=self.ft_small, bg=C["canvas_bg"], fg=C["text"], insertbackground=C["text"], bd=1)
            ent_grp.insert(0, str(fx.get("group", 1)))
            ent_grp.pack(side="left", padx=4)
            self.fx_grp_entries.append(ent_grp)
            
            tk.Label(f, text=f"{fx['name']}:", font=self.ft_small,
                     bg=C["panel"], fg=C["fixture"]).pack(side="left")
            l = tk.Label(f, text="—", font=self.ft_small, bg=C["panel"], fg=C["dim"])
            l.pack(side="left", padx=4)
            self.fx_labels.append(l)

    def _add_fixture(self):
        new_id = len(self.fixtures) + 1
        new_fx = self._default_fixtures()[0].copy()
        new_fx["name"] = f"Lyre {new_id}"
        new_fx["gma_id"] = new_id
        new_fx["x"] = self.stage_w / 2
        new_fx["y"] = self.stage_d - 0.5
        self.fixtures.append(new_fx)
        self._save_config()
        self._build_fixtures_list()
        self._draw()

    def _remove_fixture(self, idx):
        if 0 <= idx < len(self.fixtures):
            del self.fixtures[idx]
            self._save_config()
            self._build_fixtures_list()
            self._draw()

    def _section(self, parent, text):
        tk.Frame(parent, bg=C["border"], height=1).pack(fill="x", padx=8, pady=(12, 4))
        tk.Label(parent, text=text, font=self.ft_section,
                 bg=C["panel"], fg=C["accent"]).pack(anchor="w", padx=8)

    def _toggle_right_panel(self):
        if str(self.right_panel) in [str(p) for p in self.main_panes.panes()]:
            self.main_panes.forget(self.right_panel)
            self.btn_toggle_panel.config(text="[<] Panneau")
        else:
            self.main_panes.add(self.right_panel, stretch="never")
            self.btn_toggle_panel.config(text="[>] Panneau")

    def _toggle_group(self, grp):
        self.group_toggles[grp] = not self.group_toggles[grp]
        self._update_group_btn_color(grp)
        self._draw()

    def _update_group_btn_color(self, grp):
        btn = self.btn_groups[grp]
        if self.group_toggles[grp]:
            col = self._get_group_color(grp)
            btn.config(bg=col, activebackground=col, fg="#000")
        else:
            btn.config(bg="#2a2a5a", activebackground="#4a4a8a", fg="#888")

    # =========================================================================
    # COORDINATE CONVERSION
    # =========================================================================
    def _margins(self):
        return 55, 40, 55, 50   # left, top, right, bottom

    def _get_group_color(self, grp):
        colors = {
            1: "#ff5555", # Rouge
            2: "#55ff55", # Vert
            3: "#5555ff", # Bleu
            4: "#ffff55", # Jaune
            5: "#ff55ff"  # Magenta
        }
        return colors.get(grp, C["fixture"])

    def _get_global_scale_ox(self):
        # Align X dimension for both views
        if not hasattr(self, 'canvas_top') or not hasattr(self, 'canvas_front'):
            return 1.0, 0.0
            
        cw = self.canvas_top.winfo_width()
        ch_top = self.canvas_top.winfo_height()
        ch_front = self.canvas_front.winfo_height()
        
        ml, mt, mr, mb = self._margins()
        dw = cw - ml - mr
        dh_top = max(1, ch_top - mt - mb)
        dh_front = max(1, ch_front - mt - mb)
        
        scx = dw / max(self.stage_w, 0.5)
        scy_top = dh_top / max(self.stage_d, 0.5)
        scy_front = dh_front / max(self.stage_h, 0.5)
        
        scale = min(scx, scy_top, scy_front)
        ox = ml + (dw - self.stage_w * scale) / 2
        return scale, ox

    def _s2p(self, sx, sy, cv, view):
        scale, ox = self._get_global_scale_ox()
        ch = cv.winfo_height()
        ml, mt, mr, mb = self._margins()
        dh = ch - mt - mb
        max_y = self.stage_d if view == "top" else self.stage_h
        oy = mt + (dh - max_y * scale) / 2
        px = ox + sx * scale
        py = oy + (max_y - sy) * scale
        return px, py, scale

    def _p2s(self, px, py, cv, view):
        scale, ox = self._get_global_scale_ox()
        ch = cv.winfo_height()
        ml, mt, mr, mb = self._margins()
        dh = ch - mt - mb
        max_y = self.stage_d if view == "top" else self.stage_h
        oy = mt + (dh - max_y * scale) / 2
        sx = (px - ox) / scale
        sy = max_y - (py - oy) / scale
        return sx, sy

    # =========================================================================
    # DRAWING
    # =========================================================================
    def _draw(self):
        if not hasattr(self, 'canvas_top'):
            return
        self._draw_view(self.canvas_top, "top")
        self._draw_view(self.canvas_front, "front")

    def _get_group_color(self, grp):
        colors = {
            1: "#ff5555", # Rouge
            2: "#55ff55", # Vert
            3: "#5555ff", # Bleu
            4: "#ffff55", # Jaune
            5: "#ff55ff"  # Magenta
        }
        return colors.get(grp, C["fixture"])

    def _draw_view(self, cv, view):
        cv.delete("all")
        cw = cv.winfo_width()
        ch = cv.winfo_height()
        if cw < 50 or ch < 50:
            return

        def s2p(sx, syz):
            return self._s2p(sx, syz, cv, view)

        # Stage fill
        x0, y0, _ = s2p(0, 0)
        max_y = self.stage_d if view == "top" else self.stage_h
        x1, y1, _ = s2p(self.stage_w, max_y)
        cv.create_rectangle(x0, y1, x1, y0, fill=C["stage_fill"], outline="")

        # Grid 1m
        for gx in range(int(self.stage_w) + 1):
            xa, ya, _ = s2p(gx, 0)
            xb, yb, _ = s2p(gx, max_y)
            col = C["grid5"] if gx % 5 == 0 else C["grid"]
            cv.create_line(xa, ya, xb, yb, fill=col, width=1)
            cv.create_text(xa, ya + 12, text=f"{gx}", fill=C["dim"], font=("Consolas", 7))

        for gy in range(int(max_y) + 1):
            xa, ya, _ = s2p(0, gy)
            xb, yb, _ = s2p(self.stage_w, gy)
            col = C["grid5"] if gy % 5 == 0 else C["grid"]
            cv.create_line(xa, ya, xb, yb, fill=col, width=1)
            cv.create_text(xa - 16, ya, text=f"{gy}", fill=C["dim"], font=("Consolas", 7))

        # Stage border
        cv.create_rectangle(x0, y1, x1, y0, outline=C["border"], width=2)

        # Labels
        if view == "top":
            mx, my_pub, _ = s2p(self.stage_w / 2, -0.15)
            cv.create_text(mx, my_pub + 12, text="▼ PUBLIC ▼", fill=C["dim"], font=("Segoe UI", 8))
            mx2, my_fond, _ = s2p(self.stage_w / 2, self.stage_d + 0.15)
            cv.create_text(mx2, my_fond - 10, text="FOND DE SCÈNE", fill=C["dim"], font=("Segoe UI", 8))
        else:
            mx, my_pub, _ = s2p(self.stage_w / 2, -0.15)
            cv.create_text(mx, my_pub + 12, text="▼ SOL ▼", fill=C["dim"], font=("Segoe UI", 8))
            mx2, my_fond, _ = s2p(self.stage_w / 2, self.stage_h + 0.15)
            cv.create_text(mx2, my_fond - 10, text="PLAFOND", fill=C["dim"], font=("Segoe UI", 8))

        def get_fx_pos(fx):
            return (fx["x"], fx["y"]) if view == "top" else (fx["x"], fx["height"])
            
        def get_tag_pos():
            return (self.display_x, self.display_y) if view == "top" else (self.display_x, self.target_z)

        # Beams
        if self.connected:
            tx, ty_z = get_tag_pos()
            txp, typ, _ = s2p(tx, ty_z)
            for fx in self.fixtures:
                grp = fx.get("group", 1)
                if not self.group_toggles.get(grp, True):
                    continue
                    
                fxx, fxy_z = get_fx_pos(fx)
                fxp, fyp, _ = s2p(fxx, fxy_z)
                dx = txp - fxp
                dy = typ - fyp
                ln = math.sqrt(dx*dx + dy*dy)
                if ln < 1:
                    continue
                perp_x = -dy / ln * 14
                perp_y = dx / ln * 14
                cv.create_polygon(
                    fxp, fyp,
                    txp + perp_x, typ + perp_y,
                    txp - perp_x, typ - perp_y,
                    fill=C["beam_fill"], outline=C["beam"], width=1
                )
                cv.create_line(fxp, fyp, txp, typ, fill=C["fixture"], width=1, dash=(6, 4))

        # Distance lines from anchors
        if self.connected and view == "top":
            tx, ty = get_tag_pos()
            txp, typ, _ = s2p(tx, ty)
            for i, a in enumerate(self.anchors):
                ax, ay = a[:2]
                apx, apy, _ = s2p(ax, ay)
                cv.create_line(apx, apy, txp, typ, fill=C["anchor_bg"], width=1, dash=(3, 5))
                midx = (apx + txp) / 2
                midy = (apy + typ) / 2
                if i < len(self.distances):
                    cv.create_text(midx, midy - 7, text=f"{self.distances[i]:.2f}m", fill=C["dim"], font=("Consolas", 7))

        # Trail
        if view == "top":
            now = time.time()
            for trx, try_, tt in list(self.trail):
                age = now - tt
                if age > 5:
                    continue
                alpha = max(0.0, 1.0 - age / 5.0)
                px, py, _ = s2p(trx, try_)
                r = max(1, int(3 * alpha))
                g = int(60 + 60 * alpha)
                col = f"#{40:02x}{g:02x}{40:02x}"
                cv.create_oval(px - r, py - r, px + r, py + r, fill=col, outline="")

        # Fixtures
        for i, fx in enumerate(self.fixtures):
            fxx, fxy_z = get_fx_pos(fx)
            fxp, fyp, _ = s2p(fxx, fxy_z)
            r = 14
            grp = fx.get("group", 1)
            is_active = self.group_toggles.get(grp, True)
            grp_col = self._get_group_color(grp) if is_active else C["dim"]
            bg_col = C["fixture_bg"] if is_active else C["panel"]
            text_col = C["fixture"] if is_active else C["dim"]
            
            cv.create_rectangle(fxp - r, fyp - r, fxp + r, fyp + r, fill=bg_col, outline=grp_col, width=2)
            cv.create_text(fxp, fyp, text=f"L{i+1}", fill=text_col, font=("Consolas", 8, "bold"))
            cv.create_text(fxp, fyp - 20, text=fx["name"], fill=text_col, font=("Segoe UI", 7))
            cv.create_text(fxp, fyp + 20, text=f"({fxx:.1f},{fxy_z:.1f})", fill=C["dim"], font=("Consolas", 7))

        # Anchors
        for i, a in enumerate(self.anchors):
            ax, ay_z = (a[0], a[1]) if view == "top" else (a[0], a[2])
            apx, apy, _ = s2p(ax, ay_z)
            r1 = 18
            cv.create_oval(apx - r1, apy - r1, apx + r1, apy + r1, outline=C["anchor_bg"], width=2)
            r2 = 9
            cv.create_oval(apx - r2, apy - r2, apx + r2, apy + r2, fill=C["anchor"], outline="")
            cv.create_text(apx, apy - 24, text=f"A{i}", fill=C["anchor"], font=("Segoe UI", 10, "bold"))
            cv.create_text(apx, apy + 24, text=f"({ax:.1f},{ay_z:.1f})", fill=C["dim"], font=("Consolas", 7))

        # Tag
        if self.connected:
            tx, ty_z = get_tag_pos()
            txp, typ, _ = s2p(tx, ty_z)

            for gr in [28, 20, 14]:
                intensity = int(30 * (28 - gr) / 14)
                gcol = f"#{50 + intensity:02x}{10:02x}{10:02x}"
                cv.create_oval(txp - gr, typ - gr, txp + gr, typ + gr, outline=gcol, width=1)

            r = 9
            cv.create_oval(txp - r, typ - r, txp + r, typ + r, fill=C["tag"], outline="#ff8888", width=2)
            cv.create_line(txp - 14, typ, txp + 14, typ, fill=C["tag"], width=1)
            cv.create_line(txp, typ - 14, txp, typ + 14, fill=C["tag"], width=1)
            cv.create_text(txp, typ + 22, text=f"({tx:.2f}, {ty_z:.2f})", fill=C["text"], font=("Consolas", 9, "bold"))

    # =========================================================================
    # DRAG & DROP
    # =========================================================================
    def _on_press(self, event, view):
        cv = self.canvas_top if view == "top" else self.canvas_front
        best_dist = float("inf")
        best_type = None
        best_idx = -1

        for i, a in enumerate(self.anchors):
            ax, ay_z = (a[0], a[1]) if view == "top" else (a[0], a[2])
            px, py, _ = self._s2p(ax, ay_z, cv, view)
            d = math.hypot(event.x - px, event.y - py)
            if d < 25 and d < best_dist:
                best_dist = d
                best_type = "anchor"
                best_idx = i

        for i, fx in enumerate(self.fixtures):
            fxx, fxy_z = (fx["x"], fx["y"]) if view == "top" else (fx["x"], fx["height"])
            px, py, _ = self._s2p(fxx, fxy_z, cv, view)
            d = math.hypot(event.x - px, event.y - py)
            if d < 20 and d < best_dist:
                best_dist = d
                best_type = "fixture"
                best_idx = i

        tx, ty_z = (self.display_x, self.display_y) if view == "top" else (self.display_x, self.target_z)
        px, py, _ = self._s2p(tx, ty_z, cv, view)
        d = math.hypot(event.x - px, event.y - py)
        if d < 25 and d < best_dist:
            if view == "front" or self.test_mode.get():
                best_dist = d
                best_type = "tag"
                best_idx = -1

        if best_type:
            self._drag_type = best_type
            self._drag_idx = best_idx
            self._dragging = True
            self._drag_view = view
            cv.config(cursor="fleur")
        elif self.test_mode.get() or view == "front":
            self._drag_type = "tag"
            self._dragging = True
            self._drag_view = view
            self._on_drag(event, view)

    def _on_drag(self, event, view):
        if not self._dragging or self._drag_view != view:
            return

        cv = self.canvas_top if view == "top" else self.canvas_front
        sx, sy = self._p2s(event.x, event.y, cv, view)
        sx = round(sx * 10) / 10
        sy = round(sy * 10) / 10

        max_y = self.stage_d if view == "top" else self.stage_h
        sx = max(-1, min(self.stage_w + 1, sx))
        sy = max(-1, min(max_y + 1, sy))

        if self._drag_type == "anchor":
            self.anchors[self._drag_idx][0] = sx
            if view == "top":
                self.anchors[self._drag_idx][1] = sy
            else:
                self.anchors[self._drag_idx][2] = sy
        elif self._drag_type == "fixture":
            self.fixtures[self._drag_idx]["x"] = sx
            if view == "top":
                self.fixtures[self._drag_idx]["y"] = sy
            else:
                self.fixtures[self._drag_idx]["height"] = sy
        elif self._drag_type == "tag":
            if self.test_mode.get():
                self.tag_x = sx
                self.display_x = sx
                self.connected = True
                self.last_pkt = time.time()
                self.tag_q = 1.0

            if view == "top" and self.test_mode.get():
                self.tag_y = sy
                self.display_y = sy
            elif view == "front":
                self.target_z = sy

        self._draw()

    def _on_release(self, event):
        if self._dragging:
            self._dragging = False
            self.canvas_top.config(cursor="crosshair")
            self.canvas_front.config(cursor="crosshair")
            if self._drag_type in ["anchor", "fixture", "tag"]:
                self._save_config()
                self._log(f"[UI] Déplacé {self._drag_type}")

    # =========================================================================
    # STAGE SIZE
    # =========================================================================
    def _apply_stage_size(self):
        try:
            new_w = float(self.entry_w.get())
            new_d = float(self.entry_d.get())
            new_h = float(self.entry_h.get())
            if 1.0 <= new_w <= 100.0 and 1.0 <= new_d <= 100.0 and 1.0 <= new_h <= 100.0:
                old_w = self.stage_w
                old_d = self.stage_d
                old_h = self.stage_h
                # Proportionally rescale anchors
                for a in self.anchors:
                    a[0] = a[0] * new_w / old_w
                    a[1] = a[1] * new_d / old_d
                    a[2] = a[2] * new_h / old_h
                # Proportionally rescale fixtures
                for fx in self.fixtures:
                    fx["x"] = fx["x"] * new_w / old_w
                    fx["y"] = fx["y"] * new_d / old_d
                    fx["height"] = fx["height"] * new_h / old_h
                self.stage_w = new_w
                self.stage_d = new_d
                self.stage_h = new_h
                self._log(f"[UI] Scène: {new_w}m × {new_d}m × {new_h}m (anchors/fixtures recadrés)")
                self._save_config()
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

    def _send_calibration(self):
        try:
            o0 = float(self.cal_entries[0][0].get())
            o1 = float(self.cal_entries[1][0].get())
            o2 = float(self.cal_entries[2][0].get())
            z0 = float(self.cal_entries[0][1].get())
            z1 = float(self.cal_entries[1][1].get())
            z2 = float(self.cal_entries[2][1].get())
            a  = float(self.ent_alpha.get())
            tz = float(self.ent_tag_z.get())
            
            self.anchors[0][2] = z0
            self.anchors[1][2] = z1
            self.anchors[2][2] = z2
            
            # Save to cfg
            if "calibration" not in self.cfg:
                self.cfg["calibration"] = {}
            self.cfg["calibration"]["a0"] = o0
            self.cfg["calibration"]["a1"] = o1
            self.cfg["calibration"]["a2"] = o2
            self.cfg["calibration"]["alpha"] = a
            self.cfg["calibration"]["tag_z"] = tz
            self._save_config()
            
            # Send UDP
            if self.esp32_ip:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                msg = json.dumps({"off0": o0, "off1": o1, "off2": o2, "alpha": a})
                sock.sendto(msg.encode("utf-8"), (self.esp32_ip, 5001))
                self._log(f"[CFG] Calibration envoyée à {self.esp32_ip}:5001")
            else:
                self._log("[CFG] ⚠ Attente du premier paquet ESP32 pour connaître son IP...")
        except ValueError:
            self._log("[CFG] ✗ Valeurs de calibration invalides")

    # =========================================================================
    # TRILATERATION (PC-side, weighted least-squares)
    # =========================================================================
    def _trilaterate(self, distances):
        """
        Trilatération 2D pondérée.
        1) Solution initiale par linéarisation (Cramer)
        2) Raffinement par gradient descent pondéré (1/d²)
           → les anchors proches (plus précises) ont plus de poids.
        Retourne (x, y) ou None si impossible.
        """
        if len(distances) < 3 or len(self.anchors) < 3:
            return None

        d0, d1, d2 = distances[0], distances[1], distances[2]
        x1, y1 = self.anchors[0][:2]
        x2, y2 = self.anchors[1][:2]
        x3, y3 = self.anchors[2][:2]

        # --- Étape 1 : Solution initiale par Cramer ---
        a1 = 2.0 * (x2 - x1)
        b1 = 2.0 * (y2 - y1)
        c1 = d0**2 - d1**2 - x1**2 + x2**2 - y1**2 + y2**2

        a2 = 2.0 * (x3 - x1)
        b2 = 2.0 * (y3 - y1)
        c2 = d0**2 - d2**2 - x1**2 + x3**2 - y1**2 + y3**2

        det = a1 * b2 - a2 * b1
        if abs(det) < 1e-6:
            return None  # Anchors colinéaires

        x = (c1 * b2 - c2 * b1) / det
        y = (a1 * c2 - a2 * c1) / det

        # --- Étape 2 : Raffinement pondéré (gradient descent) ---
        # Poids = 1/(d+0.05)² normalisés → la distance la plus courte domine
        dists = [d0, d1, d2]
        anchors = [(x1, y1), (x2, y2), (x3, y3)]
        weights = [1.0 / (d + 0.05) ** 2 for d in dists]
        wsum = sum(weights)
        weights = [w / wsum for w in weights]  # Normaliser

        for _ in range(50):
            gx, gy = 0.0, 0.0
            for i, (ax, ay) in enumerate(anchors):
                dx = x - ax
                dy = y - ay
                computed_d = math.sqrt(dx * dx + dy * dy)
                if computed_d < 0.001:
                    continue
                error = computed_d - dists[i]
                gx += weights[i] * error * dx / computed_d
                gy += weights[i] * error * dy / computed_d
            x -= 0.5 * gx
            y -= 0.5 * gy

        return (x, y)

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
    # GRANDMA2 TELNET
    # =========================================================================
    def _start_telnet(self):
        t = threading.Thread(target=self._telnet_loop, daemon=True)
        t.start()
        
    def _toggle_ma2(self):
        if self.ma2_connected:
            self.ma2_connected = False
            self.btn_ma2_connect.config(text="Connecter")
            self.lbl_ma2_status.config(text="✗ Déconnecté", fg="#ff8888")
            self.btn_ma2_top.config(bg="#aa6600", text="🎬 MA2")
            if self.ma2_socket:
                try:
                    self.ma2_socket.close()
                except:
                    pass
                self.ma2_socket = None
        else:
            self.btn_ma2_connect.config(text="Déconnecter")
            self.lbl_ma2_status.config(text="... Connexion", fg="#ffaa00")
            self.btn_ma2_top.config(bg="#227722", text="🎬 MA2 ●")
            self._save_config()
            self.ma2_connected = True

    def _toggle_manual(self):
        current = self.test_mode.get()
        self.test_mode.set(not current)
        if not current:
            self.btn_manual.config(fg="#fff")
            self._log("[UI] Mode manuel activé (clic sur scène)")
        else:
            self.btn_manual.config(bg="#555555", fg="#ccc", text="✋ Manual")
            self._log("[UI] Mode manuel désactivé")
            
    def _telnet_loop(self):
        while True:
            if not self.ma2_connected:
                time.sleep(0.5)
                continue
                
            try:
                ip = self.ent_ma2_ip.get()
                port = int(self.ent_ma2_port.get())
                user = self.ent_ma2_user.get()
                pw = self.ent_ma2_pass.get()
                
                self._log(f"[MA2] Connexion à {ip}:{port}...")
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3.0)
                s.connect((ip, port))
                s.settimeout(None)
                
                # Login
                login_cmd = f'login "{user}" "{pw}"\r\n'
                s.sendall(login_cmd.encode("utf-8"))
                
                self.ma2_socket = s
                self.lbl_ma2_status.config(text="✓ Connecté", fg="#88ff88")
                self._log("[MA2] ✓ Telnet connecté et authentifié")
                
                # Main loop at 15Hz (0.066s)
                last_cmd = ""
                while self.ma2_connected:
                    time.sleep(0.066)
                    
                    with self.ma2_lock:
                        targets = list(self.ma2_targets.items())
                        
                    if not targets:
                        continue
                        
                    # Build MA2 command
                    # Correct syntax to avoid "Error: Fixture X": Fixture X Attribute "Pan" At Y ; Fixture X Attribute "Tilt" At Z
                    parts = []
                    for gid, (pan, tilt) in targets:
                        parts.append(f'Fixture {gid} Attribute "Pan" At {pan:.1f} ; Fixture {gid} Attribute "Tilt" At {tilt:.1f}')
                        
                    cmd = " ; ".join(parts) + "\r\n"
                    
                    if cmd == last_cmd:
                        continue
                    last_cmd = cmd
                    
                    try:
                        s.sendall(cmd.encode("utf-8"))
                        
                        # Vider le buffer de réception pour éviter que la MA2 ne freeze
                        try:
                            s.setblocking(False)
                            while True:
                                data = s.recv(4096)
                                if not data:
                                    break
                        except BlockingIOError:
                            pass  # Plus rien à lire
                        finally:
                            s.setblocking(True)
                            
                    except Exception as e:
                        self._log(f"[MA2] ✗ Erreur envoi: {e}")
                        break
                        
            except Exception as e:
                self._log(f"[MA2] ✗ Echec: {e}")
                
            if self.ma2_socket:
                try:
                    self.ma2_socket.close()
                except:
                    pass
                self.ma2_socket = None
                
            if self.ma2_connected:
                self.lbl_ma2_status.config(text="⚠ Reconnexion...", fg="#ffaa00")
                time.sleep(2.0)

    # =========================================================================
    # UDP
    # =========================================================================
    def _start_udp(self):
        port = self.cfg.get("network", {}).get("udp_listen_port", 9000)
        t = threading.Thread(target=self._udp_loop, args=(port,), daemon=True)
        t.start()

    def _start_heartbeat(self):
        """Envoie un ping UDP périodique à l'ESP32 pour qu'il sache que le dashboard est connecté."""
        t = threading.Thread(target=self._heartbeat_loop, daemon=True)
        t.start()

    def _heartbeat_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ping_msg = json.dumps({"ping": 1}).encode("utf-8")
        while True:
            try:
                if self.esp32_ip:
                    sock.sendto(ping_msg, (self.esp32_ip, 5001))
            except Exception:
                pass
            time.sleep(2.0)

    def _udp_loop(self, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.settimeout(1.0)
        self._log(f"[NET] Écoute UDP sur port {port}")

        while True:
            try:
                data, addr = sock.recvfrom(1024)
                self.esp32_ip = addr[0]
                msg = json.loads(data.decode("utf-8"))
                now = time.time()

                # --- Heartbeat packet (ESP32 annonce sa présence) ---
                if "heartbeat" in msg:
                    self.last_pkt = now
                    if "bat" in msg:
                        self.bat_voltage = msg["bat"]
                        self.bat_history.append((now, self.bat_voltage))
                    if not self.connected:
                        self._log(f"[NET] 📡 ESP32 détecté à {addr[0]}")
                    continue

                esp32_q = msg.get("q", 0.0)
                self.distances = msg.get("d", [0, 0, 0])
                self.pkt_count += 1
                self.last_pkt = now
                self.connected = True
                self._rate_n += 1
                if "bat" in msg:
                    self.bat_voltage = msg["bat"]
                    self.bat_history.append((now, self.bat_voltage))

                # --- PC-side trilateration using dashboard anchor positions ---
                if len(self.distances) >= 3:
                    # PROJECTION 3D -> 2D
                    try:
                        tagz = float(self.ent_tag_z.get())
                    except:
                        tagz = self.cfg.get("calibration", {}).get("tag_z", 1.0)
                        
                    dist_2d = []
                    for i in range(3):
                        az = self.anchors[i][2]
                        dz = az - tagz
                        d3d = self.distances[i]
                        d2d = math.sqrt(max(0.0, d3d*d3d - dz*dz))
                        dist_2d.append(d2d)
                        
                    pos = self._trilaterate(dist_2d)
                    if pos is not None:
                        raw_x, raw_y = pos
                        
                        try:
                            a = float(self.ent_alpha.get())
                        except:
                            a = self.cfg.get("calibration", {}).get("alpha", 0.85)
                            
                        if self.tag_x == 0.0 and self.tag_y == 0.0:
                            new_x, new_y = raw_x, raw_y
                        else:
                            new_x = self.tag_x * (1.0 - a) + raw_x * a
                            new_y = self.tag_y * (1.0 - a) + raw_y * a
                        
                        # Recalculate quality PC-side based on actual UI anchors
                        err = 0.0
                        for i in range(3):
                            ax, ay = self.anchors[i][:2]
                            cd = math.sqrt((new_x - ax)**2 + (new_y - ay)**2)
                            err += abs(cd - dist_2d[i])
                        err /= 3.0
                        # 0m error = 100%, 1m+ error = 0%
                        new_q = max(0.0, min(1.0, 1.0 - err))
                        # Lissage de l'affichage qualité pour éviter le clignotement
                        self.tag_q = (self.tag_q * 0.8) + (new_q * 0.2)
                    else:
                        # Fallback to ESP32-computed position
                        new_x = msg.get("x", 0.0)
                        new_y = msg.get("y", 0.0)
                        self.tag_q = (self.tag_q * 0.8) + (esp32_q * 0.2)
                else:
                    new_x = msg.get("x", 0.0)
                    new_y = msg.get("y", 0.0)
                    self.tag_q = (self.tag_q * 0.8) + (esp32_q * 0.2)

                self.tag_x = new_x
                self.tag_y = new_y
                self.trail.append((new_x, new_y, now))

                # --- Velocity estimation ---
                self._pos_history.append((new_x, new_y, now))
                if len(self._pos_history) >= 2:
                    oldest = self._pos_history[0]
                    dt = now - oldest[2]
                    if dt > 0.05:  # Avoid division by tiny dt
                        self._vel_x = (new_x - oldest[0]) / dt
                        self._vel_y = (new_y - oldest[1]) / dt
                        # Clamp velocity to reasonable range (max 3 m/s walk/run)
                        max_v = 3.0
                        self._vel_x = max(-max_v, min(max_v, self._vel_x))
                        self._vel_y = max(-max_v, min(max_v, self._vel_y))

                # Snap display to real position on new packet
                self.display_x = new_x
                self.display_y = new_y
                self._last_predict_t = now

                # Log every 5th packet (lisible sans saturer)
                if self.pkt_count % 5 == 1:
                    d_str = " ".join(f"A{i}={v:.2f}m" for i, v in enumerate(self.distances))
                    vel = math.sqrt(self._vel_x**2 + self._vel_y**2)
                    self._log(f"[TRI] x={new_x:.3f} y={new_y:.3f}  {d_str}  v={vel:.2f}m/s")

            except socket.timeout:
                if time.time() - self.last_pkt > 3 and not self.test_mode.get():
                    self.connected = False
            except json.JSONDecodeError as e:
                self._log(f"[ERR] JSON invalide: {e}")
            except Exception as e:
                self._log(f"[ERR] {e}")

    # =========================================================================
    # TICK
    # =========================================================================
    def _tick(self):
        # Direct display: tag_x/y is set by the UDP thread (trilaterated)
        # display_x/y just tracks it directly for instant response
        if self.connected:
            self.display_x = self.tag_x
            self.display_y = self.tag_y

        # Draw
        self._draw()

        # Flush log
        self._flush_log()

        # Panel updates
        if self.connected:
            self.lbl_x.config(text=f"{self.display_x:.3f} m")
            self.lbl_y.config(text=f"{self.display_y:.3f} m")
            self.lbl_z.config(text=f"{self.target_z:.3f} m")
            for i, l in enumerate(self.dlbls):
                if i < len(self.distances):
                    l.config(text=f"{self.distances[i]:.3f} m")
            self._draw_qbar(self.tag_q)
            self.lbl_q.config(text=f"{self.tag_q * 100:.0f}%")
            self.lbl_status.config(text="✅ Connecté", fg=C["ok"])

            # Pan/Tilt
            th = self.target_z
                
            new_targets = {}
            for j, fx in enumerate(self.fixtures):
                dx = self.display_x - fx["x"]
                dy = self.display_y - fx["y"]
                dz = fx["height"] - th
                dh = math.sqrt(dx*dx + dy*dy)
                pan_math = math.degrees(math.atan2(dx, dy))
                tilt_math = math.degrees(math.atan2(dz, dh)) if dh > 0.01 else 90
                
                # Inversion si accrochée à l'envers
                if fx.get("pan_invert", False):
                    pan_math = -pan_math
                if fx.get("tilt_invert", False):
                    tilt_math = -tilt_math
                
                # Normalisation Pan (0-360)
                if pan_math < 0:
                    pan_math += 360.0
                    
                # Application des offsets et limites
                ma_pan = pan_math + float(fx.get("pan_offset", 0.0))
                ma_pan = max(float(fx.get("pan_min", 0.0)), min(float(fx.get("pan_max", 540.0)), ma_pan))
                
                ma_tilt = tilt_math + float(fx.get("tilt_offset", 90.0))
                ma_tilt = max(float(fx.get("tilt_min", -95.0)), min(float(fx.get("tilt_max", 95.0)), ma_tilt))
                
                # Visual warning if hitting bounds
                if (ma_pan <= float(fx.get("pan_min", 0.0)) or 
                    ma_pan >= float(fx.get("pan_max", 540.0)) or 
                    ma_tilt <= float(fx.get("tilt_min", -95.0)) or 
                    ma_tilt >= float(fx.get("tilt_max", 95.0))):
                    status_col = "#aa4444"
                else:
                    status_col = C["text"]
                    
                if j < len(self.fx_labels):
                    self.fx_labels[j].config(
                        text=f"P={ma_pan:.1f}° T={ma_tilt:.1f}°", fg=status_col)
                        
                try:
                    if hasattr(self, 'fx_grp_entries') and j < len(self.fx_grp_entries):
                        fx["group"] = max(1, min(5, int(self.fx_grp_entries[j].get())))
                except:
                    pass
                        
                # Store for MA2 Telnet thread (only if group is enabled)
                grp = fx.get("group", 1)
                if self.group_toggles.get(grp, True):
                    try:
                        gma_id = int(self.fx_ma2_entries[j].get())
                    except:
                        gma_id = fx.get("gma_id", j + 1)
                        
                    new_targets[gma_id] = (ma_pan, ma_tilt)
                
            with self.ma2_lock:
                self.ma2_targets = new_targets
        else:
            self.lbl_status.config(text="⏳ En attente données UWB...", fg=C["dim"])

        # ESP32 indicator (basé sur heartbeat, indépendant du tracking UWB)
        esp32_age = time.time() - self.last_pkt if self.last_pkt > 0 else 999
        if self.esp32_ip and esp32_age < 5:
            self.lbl_esp32.config(
                text=f"📡 ESP32: {self.esp32_ip}",
                fg=C["ok"])
        elif self.esp32_ip:
            self.lbl_esp32.config(
                text=f"📡 ESP32: {self.esp32_ip} (perdu)",
                fg=C["bad"])
        else:
            self.lbl_esp32.config(
                text="📡 ESP32: --",
                fg=C["dim"])

        # Rate
        now = time.time()
        if now - self._rate_t >= 1.0:
            self.pkt_rate = self._rate_n / (now - self._rate_t)
            self._rate_n = 0
            self._rate_t = now
        self.lbl_rate.config(text=f"{self.pkt_rate:.1f} pkt/s  |  #{self.pkt_count}")
        self.lbl_pkt.config(text=f"Paquets: {self.pkt_count}")

        # Battery voltage
        if self.bat_voltage > 0.1:
            self.lbl_bat.config(text=f"🔋 {self.bat_voltage:.2f}V", fg=C["ok"] if self.bat_voltage > 3.5 else C["warn"] if self.bat_voltage > 3.2 else C["bad"])
        else:
            self.lbl_bat.config(text="🔋 --", fg=C["dim"])

        # Velocity & prediction status
        if self.connected:
            vel = math.sqrt(self._vel_x**2 + self._vel_y**2)
            self.lbl_vel.config(text=f"Vitesse: {vel:.2f} m/s")
            age = time.time() - self.last_pkt
            if age < 0.5:
                self.lbl_predict.config(text="🟢 Live UWB", fg=C["ok"])
            elif age < 3.0:
                self.lbl_predict.config(text=f"⏳ Dernier: {age:.1f}s", fg=C["warn"])
            else:
                self.lbl_predict.config(text=f"⚠ Signal perdu ({age:.0f}s)", fg=C["bad"])
        else:
            self.lbl_vel.config(text="Vitesse: —")
            self.lbl_predict.config(text="")

        # MA2 button blink (vert clignotant quand connecté)
        if self.ma2_connected and self.ma2_socket:
            blink = int(time.time() * 2) % 2 == 0
            self.btn_ma2_top.config(bg="#33cc33" if blink else "#227722")
        elif self.ma2_connected:
            self.btn_ma2_top.config(bg="#cc8800")

        # Manual button blink (bleu clignotant quand actif)
        if self.test_mode.get():
            blink = int(time.time() * 2) % 2 == 0
            self.btn_manual.config(bg="#3388ff" if blink else "#2255aa",
                                   text="✋ Manual ●" if blink else "✋ Manual")

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

    # =========================================================================
    # BATTERY HISTORY POPUP
    # =========================================================================
    def _show_bat_history(self):
        if len(self.bat_history) < 2:
            return

        top = tk.Toplevel(self.root)
        top.title("🔋 Historique tension GPIO32")
        top.geometry("700x400")
        top.configure(bg=C["bg"])

        tk.Label(top, text="Tension GPIO32 (2 dernières heures)",
                 font=self.ft_title, bg=C["bg"], fg=C["accent"]).pack(pady=8)

        canvas = tk.Canvas(top, bg=C["canvas_bg"], highlightthickness=0)
        canvas.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        def _draw(event=None):
            canvas.delete("all")
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            if w < 50 or h < 50:
                return

            margin_l, margin_r, margin_t, margin_b = 50, 20, 20, 35
            gw = w - margin_l - margin_r
            gh = h - margin_t - margin_b

            data = list(self.bat_history)
            now = time.time()
            t_min = now - 7200  # 2 heures
            # Filter to last 2h
            data = [(t, v) for t, v in data if t >= t_min]
            if len(data) < 2:
                canvas.create_text(w//2, h//2, text="Pas assez de données",
                                   fill=C["dim"], font=self.ft_label)
                return

            t_start = data[0][0]
            t_end = data[-1][0]
            t_range = max(t_end - t_start, 1.0)

            voltages = [v for _, v in data]
            v_min = min(voltages) - 0.05
            v_max = max(voltages) + 0.05
            v_range = max(v_max - v_min, 0.1)

            # Grid lines
            for i in range(6):
                y = margin_t + int(gh * i / 5)
                v = v_max - (v_range * i / 5)
                canvas.create_line(margin_l, y, w - margin_r, y,
                                   fill="#333", dash=(2, 4))
                canvas.create_text(margin_l - 5, y, text=f"{v:.2f}V",
                                   anchor="e", fill=C["dim"], font=self.ft_small)

            # Time labels
            for i in range(5):
                x = margin_l + int(gw * i / 4)
                t = t_start + (t_range * i / 4)
                minutes_ago = (now - t) / 60
                if minutes_ago < 1:
                    label = "now"
                else:
                    label = f"-{int(minutes_ago)}m"
                canvas.create_text(x, h - margin_b + 15, text=label,
                                   fill=C["dim"], font=self.ft_small)

            # Plot line
            points = []
            for t, v in data:
                x = margin_l + int(gw * (t - t_start) / t_range)
                y = margin_t + int(gh * (1.0 - (v - v_min) / v_range))
                points.append((x, y))

            if len(points) >= 2:
                flat = [coord for p in points for coord in p]
                canvas.create_line(*flat, fill="#44aaff", width=2, smooth=True)

            # Current value
            last_v = data[-1][1]
            canvas.create_text(w - margin_r - 5, margin_t + 5,
                               text=f"{last_v:.2f}V",
                               anchor="ne", fill="#44aaff", font=self.ft_value)

        canvas.bind("<Configure>", _draw)
        top.after(100, _draw)


if __name__ == "__main__":
    print("SudShow Locator — Dashboard V2")
    app = Dashboard()
    app.run()
