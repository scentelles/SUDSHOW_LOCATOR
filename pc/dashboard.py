#!/usr/bin/env python3
"""
SudShow Locator — Dashboard V2
Plan 2D interactif avec anchors/lyres draggables, faisceaux, et log ESP32.
"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import simpledialog, filedialog, messagebox
import socket
import json
import math
import re
import threading
import time
import os
import copy
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
    "tag2":        "#00e5ff",
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
    # 8 Couleurs standards (Nom, Hex, (R, G, B) 0-100)
    COLOR_SWATCHES = [
        ("Blanc",   "#FFFFFF", (100, 100, 100)),
        ("Rouge",   "#FF3333", (100, 0, 0)),
        ("Vert",    "#33FF33", (0, 100, 0)),
        ("Bleu",    "#3366FF", (0, 0, 100)),
        ("Jaune",   "#FFFF33", (100, 100, 0)),
        ("Cyan",    "#33FFFF", (0, 100, 100)),
        ("Magenta", "#FF33FF", (100, 0, 100)),
        ("Orange",  "#FF8800", (100, 45, 0)),
    ]

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("SudShow Locator — Dashboard")
        self.root.configure(bg=C["bg"])
        self.root.geometry("1400x900")
        self.root.minsize(1000, 700)

        # --- Config ---
        self.current_config_file = CONFIG_FILE
        self.cfg = self._load_config(self.current_config_file)
        self.stage_w = self.cfg.get("stage", {}).get("width", 10.0)
        self.stage_d = self.cfg.get("stage", {}).get("depth", 5.0)
        self.stage_h = self.cfg.get("stage", {}).get("height", 3.0)
        self.target_z = self.cfg.get("tracking", {}).get("target_height", 1.7)
        fp2_cfg = self.cfg.get("focus_point_2", {})
        self.fp2_x = fp2_cfg.get("x", self.stage_w * 0.5)
        self.fp2_y = fp2_cfg.get("y", self.stage_d * 0.5)
        self.fp2_z = fp2_cfg.get("z", 1.7)

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
        fp1_cfg = self.cfg.get("focus_point_1", {})
        self.tag_x = fp1_cfg.get("x", round(self.stage_w * 0.5, 2))
        self.tag_y = fp1_cfg.get("y", round(self.stage_d * 0.5, 2))
        self.tag_q = 0.0
        self.distances = [0.0, 0.0, 0.0]
        self.pkt_count = 0
        self.pkt_rate = 0.0
        self.connected = False
        self.last_pkt = 0.0
        self.last_uwb_pkt = 0.0
        self._rate_n = 0
        self._rate_t = time.time()
        self.trail = collections.deque(maxlen=120)
        self.display_x = self.tag_x
        self.display_y = self.tag_y
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
        self.ft_grp_btn = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        
        self.test_mode = tk.BooleanVar(value=False)    # Manual F1
        self.test_mode_2 = tk.BooleanVar(value=False)  # Manual F2
        self.focus1_active = True
        self.focus2_active = False
        self.group_toggles = {i: True for i in range(1, 6)}
        fp2_grps = self.cfg.get("focus_point_2", {}).get("groups", {})
        self.group_toggles_2 = {i: bool(fp2_grps.get(str(i), False)) for i in range(1, 6)}
        for i in range(1, 6):
            if self.group_toggles_2[i]:
                self.group_toggles[i] = False

        # Telnet MA2 state
        self.ma2_socket = None
        self.ma2_connected = False
        self.ma2_targets = {}  # {gma_id: (pan, tilt, grp, manual_cmd)}
        self.ma2_clear_pending = False
        self.ma2_resend_manual_cmd = False
        self.ma2_cmd_queue = []
        self.ma2_lock = threading.Lock()

        # Presets par Focus Point (8 presets pour Focus 1, 8 presets pour Focus 2)
        self.focus_presets = self.cfg.get("focus_presets", {})
        for fp in ("1", "2"):
            if fp not in self.focus_presets:
                def_x = round(self.stage_w * 0.5, 2)
                def_y = round(self.stage_d * 0.5, 2)
                def_z = round(self.target_z if fp == "1" else self.fp2_z, 2)
                self.focus_presets[fp] = [
                    {"label": f"P{i+1}", "x": def_x, "y": def_y, "z": def_z, "empty": True}
                    for i in range(8)
                ]
            else:
                while len(self.focus_presets[fp]) < 8:
                    i = len(self.focus_presets[fp])
                    def_x = round(self.stage_w * 0.5, 2)
                    def_y = round(self.stage_d * 0.5, 2)
                    def_z = round(self.target_z if fp == "1" else self.fp2_z, 2)
                    self.focus_presets[fp].append(
                        {"label": f"P{i+1}", "x": def_x, "y": def_y, "z": def_z, "empty": True}
                    )
        self.focus_current_color = self.cfg.get("focus_colors", {"1": "#FFFFFF", "2": "#FFFFFF"})
        self.preset_save_mode = False

        # Battery monitoring
        self.bat_voltage = 0.0
        # Historique: (timestamp, voltage) — 1 sample/2s = 3600 samples pour 2h
        self.bat_history = collections.deque(maxlen=3600)

        self._build_ui()
        self._start_udp()
        self._start_telnet()
        self._start_heartbeat()
        self._start_remote_listener()
        self._tick()

    def _load_config(self, filepath=None):
        target = filepath or CONFIG_FILE
        try:
            with open(target, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _dump_config_data(self, target_path=None):
        """Génère la structure JSON complète à partir des paramètres en cours."""
        target = target_path or self.current_config_file
        existing = {}
        if os.path.exists(target):
            try:
                with open(target, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}

        data = existing if isinstance(existing, dict) else {}
        if "_comment" not in data:
            data["_comment"] = "SudShow Locator — Configuration PC"
        if "_units" not in data:
            data["_units"] = "Toutes les distances en mètres, angles en degrés"

        # Synchroniser les dimensions de scène depuis les entries si présentes
        try:
            if hasattr(self, 'entry_w') and self.entry_w.get():
                self.stage_w = float(self.entry_w.get())
            if hasattr(self, 'entry_d') and self.entry_d.get():
                self.stage_d = float(self.entry_d.get())
            if hasattr(self, 'entry_h') and self.entry_h.get():
                self.stage_h = float(self.entry_h.get())
        except ValueError:
            pass

        data["stage"] = {
            "width": round(self.stage_w, 2),
            "depth": round(self.stage_d, 2),
            "height": round(self.stage_h, 2)
        }

        # Calibration & Z des anchors
        cal = self.cfg.get("calibration", {}) if isinstance(self.cfg.get("calibration"), dict) else {}
        try:
            if hasattr(self, 'cal_entries') and len(self.cal_entries) >= 3:
                for i in range(3):
                    cal[f"a{i}"] = float(self.cal_entries[i][0].get())
                    self.anchors[i][2] = float(self.cal_entries[i][1].get())
            if hasattr(self, 'ent_alpha') and self.ent_alpha.get():
                cal["alpha"] = float(self.ent_alpha.get())
            if hasattr(self, 'ent_tag_z') and self.ent_tag_z.get():
                cal["tag_z"] = float(self.ent_tag_z.get())
        except ValueError:
            pass
        data["calibration"] = cal

        data["anchors"] = {
            f"a{i}": {"x": round(a[0], 2), "y": round(a[1], 2), "z": round(a[2], 2)}
            for i, a in enumerate(self.anchors)
        }

        # Synchroniser les positions et paramètres des fixtures
        for i, fx in enumerate(self.fixtures):
            fx["x"] = round(fx["x"], 2)
            fx["y"] = round(fx["y"], 2)
            if "visible" not in fx:
                fx["visible"] = True
            if "color_subfixtures" not in fx:
                fx["color_subfixtures"] = ""
            try:
                if hasattr(self, 'fx_ma2_entries') and i < len(self.fx_ma2_entries):
                    fx["gma_id"] = int(self.fx_ma2_entries[i].get())
            except:
                pass
            try:
                if hasattr(self, 'fx_grp_entries') and i < len(self.fx_grp_entries):
                    fx["group"] = max(1, min(5, int(self.fx_grp_entries[i].get())))
            except:
                pass
        data["fixtures"] = self.fixtures

        if hasattr(self, 'var_hide_anchors'):
            data["hide_anchors"] = self.var_hide_anchors.get()

        data["tracking"] = self.cfg.get("tracking", {}) if isinstance(self.cfg.get("tracking"), dict) else {}
        data["tracking"]["target_height"] = round(self.target_z, 2)

        data["focus_point_1"] = {
            "x": round(self.display_x, 2),
            "y": round(self.display_y, 2),
        }

        data["focus_point_2"] = {
            "x": round(self.fp2_x, 2),
            "y": round(self.fp2_y, 2),
            "z": round(self.fp2_z, 2),
            "groups": {str(i): self.group_toggles_2.get(i, False) for i in range(1, 6)}
        }

        # MA2
        ma2 = self.cfg.get("ma2", {}) if isinstance(self.cfg.get("ma2"), dict) else {}
        try:
            if hasattr(self, 'ent_ma2_ip') and self.ent_ma2_ip.get():
                ma2["ip"] = self.ent_ma2_ip.get().strip()
            if hasattr(self, 'ent_ma2_port') and self.ent_ma2_port.get():
                ma2["port"] = int(self.ent_ma2_port.get().strip())
            if hasattr(self, 'ent_ma2_user'):
                ma2["user"] = self.ent_ma2_user.get().strip()
            if hasattr(self, 'ent_ma2_pass'):
                ma2["pass"] = self.ent_ma2_pass.get().strip()
        except ValueError:
            pass
        data["ma2"] = ma2

        data["focus_presets"] = self.focus_presets
        data["focus_colors"] = self.focus_current_color

        return data

    def _apply_config_data(self, data, source_name="config.json"):
        """Applique l'ensemble d'une configuration chargée à la volée et rafraîchit l'interface."""
        if not isinstance(data, dict):
            return

        # Scène
        stage_cfg = data.get("stage", {})
        if stage_cfg:
            self.stage_w = float(stage_cfg.get("width", self.stage_w))
            self.stage_d = float(stage_cfg.get("depth", self.stage_d))
            self.stage_h = float(stage_cfg.get("height", self.stage_h))
            if hasattr(self, 'entry_w'):
                self.entry_w.delete(0, tk.END)
                self.entry_w.insert(0, str(self.stage_w))
            if hasattr(self, 'entry_d'):
                self.entry_d.delete(0, tk.END)
                self.entry_d.insert(0, str(self.stage_d))
            if hasattr(self, 'entry_h'):
                self.entry_h.delete(0, tk.END)
                self.entry_h.insert(0, str(self.stage_h))

        # Anchors
        acfg = data.get("anchors", {})
        if acfg:
            self.anchors = [
                [float(acfg.get("a0", {}).get("x", 0.0)),
                 float(acfg.get("a0", {}).get("y", 0.0)),
                 float(acfg.get("a0", {}).get("z", 2.0))],
                [float(acfg.get("a1", {}).get("x", self.stage_w)),
                 float(acfg.get("a1", {}).get("y", 0.0)),
                 float(acfg.get("a1", {}).get("z", 2.0))],
                [float(acfg.get("a2", {}).get("x", self.stage_w * 0.5)),
                 float(acfg.get("a2", {}).get("y", self.stage_d)),
                 float(acfg.get("a2", {}).get("z", 2.0))],
            ]

        # Calibration
        cal = data.get("calibration", {})
        if hasattr(self, 'cal_entries') and len(self.cal_entries) >= 3:
            for i in range(3):
                ent_off, ent_z = self.cal_entries[i]
                ent_off.delete(0, tk.END)
                ent_off.insert(0, str(cal.get(f"a{i}", 0.8)))
                ent_z.delete(0, tk.END)
                ent_z.insert(0, str(self.anchors[i][2]))
        if hasattr(self, 'ent_alpha'):
            self.ent_alpha.delete(0, tk.END)
            self.ent_alpha.insert(0, str(cal.get("alpha", 0.85)))
        if hasattr(self, 'ent_tag_z'):
            self.ent_tag_z.delete(0, tk.END)
            self.ent_tag_z.insert(0, str(cal.get("tag_z", 1.0)))

        # Masquage des Anchors
        if hasattr(self, 'var_hide_anchors'):
            self.var_hide_anchors.set(bool(data.get("hide_anchors", False)))

        # Fixtures
        cfg_fixtures = data.get("fixtures", [])
        if cfg_fixtures:
            self.fixtures = copy.deepcopy(cfg_fixtures)
            defaults_list = self._default_fixtures()
            def_fx = defaults_list[0]
            for fx in self.fixtures:
                for k, v in def_fx.items():
                    if k not in fx:
                        fx[k] = v
        else:
            self.fixtures = self._default_fixtures()

        if hasattr(self, 'frm_fixtures'):
            self._build_fixtures_list()

        # Tracking / Cible Z
        self.target_z = float(data.get("tracking", {}).get("target_height", self.target_z))

        # Focus Point 1
        fp1_cfg = data.get("focus_point_1", {})
        self.tag_x = float(fp1_cfg.get("x", round(self.stage_w * 0.5, 2)))
        self.tag_y = float(fp1_cfg.get("y", round(self.stage_d * 0.5, 2)))
        self.display_x = self.tag_x
        self.display_y = self.tag_y

        # Focus Point 2
        fp2_cfg = data.get("focus_point_2", {})
        self.fp2_x = float(fp2_cfg.get("x", round(self.stage_w * 0.5, 2)))
        self.fp2_y = float(fp2_cfg.get("y", round(self.stage_d * 0.5, 2)))
        self.fp2_z = float(fp2_cfg.get("z", 1.7))

        fp2_grps = fp2_cfg.get("groups", {})
        if fp2_grps:
            self.group_toggles_2 = {i: bool(fp2_grps.get(str(i), False)) for i in range(1, 6)}
            self.group_toggles = {i: True for i in range(1, 6)}
            for i in range(1, 6):
                if self.group_toggles_2[i]:
                    self.group_toggles[i] = False
                if hasattr(self, 'btn_groups') and hasattr(self, 'btn_groups_2'):
                    self._update_group_btn_color(i, 1)
                    self._update_group_btn_color(i, 2)

        # Indicateur Z Top
        if hasattr(self, 'lbl_z_top'):
            cur_z = self.target_z if self.focus1_active else self.fp2_z
            self.lbl_z_top.config(text=f"Z: {cur_z:.2f}m")

        # GrandMA2
        ma2_cfg = data.get("ma2", {})
        if hasattr(self, 'ent_ma2_ip'):
            self.ent_ma2_ip.delete(0, tk.END)
            self.ent_ma2_ip.insert(0, ma2_cfg.get("ip", "127.0.0.1"))
        if hasattr(self, 'ent_ma2_port'):
            self.ent_ma2_port.delete(0, tk.END)
            self.ent_ma2_port.insert(0, str(ma2_cfg.get("port", 30000)))
        if hasattr(self, 'ent_ma2_user'):
            self.ent_ma2_user.delete(0, tk.END)
            self.ent_ma2_user.insert(0, ma2_cfg.get("user", "administrator"))
        if hasattr(self, 'ent_ma2_pass'):
            self.ent_ma2_pass.delete(0, tk.END)
            self.ent_ma2_pass.insert(0, ma2_cfg.get("pass", "admin"))

        # Presets Focus 1 et 2
        raw_presets = data.get("focus_presets", {})
        self.focus_presets = copy.deepcopy(raw_presets) if raw_presets else {}
        for fp in ("1", "2"):
            if fp not in self.focus_presets:
                def_x = round(self.stage_w * 0.5, 2)
                def_y = round(self.stage_d * 0.5, 2)
                def_z = round(self.target_z if fp == "1" else self.fp2_z, 2)
                self.focus_presets[fp] = [
                    {"label": f"P{i+1}", "x": def_x, "y": def_y, "z": def_z, "empty": True}
                    for i in range(8)
                ]
            else:
                while len(self.focus_presets[fp]) < 8:
                    i = len(self.focus_presets[fp])
                    def_x = round(self.stage_w * 0.5, 2)
                    def_y = round(self.stage_d * 0.5, 2)
                    def_z = round(self.target_z if fp == "1" else self.fp2_z, 2)
                    self.focus_presets[fp].append(
                        {"label": f"P{i+1}", "x": def_x, "y": def_y, "z": def_z, "empty": True}
                    )

        if hasattr(self, 'focus_preset_buttons'):
            for fp in (1, 2):
                s_fp = str(fp)
                if fp in self.focus_preset_buttons:
                    for i, btn in enumerate(self.focus_preset_buttons[fp]):
                        p_info = self.focus_presets[s_fp][i]
                        lbl = p_info.get("label", f"P{i+1}")
                        is_empty = p_info.get("empty", True)
                        accent_col = C["tag"] if fp == 1 else C["tag2"]
                        saved_bg = "#241618" if fp == 1 else "#0f2630"
                        btn.config(
                            text=lbl,
                            bg=C["border"] if is_empty else saved_bg,
                            fg=C["dim"] if is_empty else accent_col,
                            font=("Segoe UI", 10, "bold")
                        )

        # Couleurs Focus 1 et 2
        raw_colors = data.get("focus_colors", {"1": "#FFFFFF", "2": "#FFFFFF"})
        self.focus_current_color = copy.deepcopy(raw_colors)
        if hasattr(self, 'color_swatch_boxes'):
            for fp in (1, 2):
                cur_hex = self.focus_current_color.get(str(fp), "#FFFFFF").upper()
                if fp in self.color_swatch_boxes:
                    for s_box, (_, s_hex, _) in zip(self.color_swatch_boxes[fp], self.COLOR_SWATCHES):
                        if s_hex.upper() == cur_hex:
                            hl = "#00d4ff" if s_hex.upper() in ["#FFFFFF", "#FFFF33", "#33FFFF"] else "#FFFFFF"
                            s_box.config(bg=hl)
                        else:
                            s_box.config(bg=C["canvas_bg"])

        # Reset drag & trail
        self._dragging = False
        self._drag_idx = -1
        self.trail.clear()

        self.cfg = data
        self._draw()

    def _save_config(self, filepath=None):
        """Sauvegarde la config courante dans un fichier JSON (par défaut le fichier actif)."""
        target = filepath or self.current_config_file
        try:
            data = self._dump_config_data(target)
            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            self.current_config_file = target
            self.cfg = data
            filename = os.path.basename(target)
            now_str = time.strftime("%H:%M:%S")
            msg = f"{filename} (sauvegardé à {now_str})"
            self._log(f"[CFG] ✓ Configuration sauvegardée dans {filename}")
            if hasattr(self, 'lbl_cfg_status'):
                self.lbl_cfg_status.config(text=msg, fg=C["ok"])
            return True
        except Exception as e:
            err = f"✗ Erreur sauvegarde: {e}"
            self._log(f"[CFG] {err}")
            if hasattr(self, 'lbl_cfg_status'):
                self.lbl_cfg_status.config(text=err, fg=C["bad"])
            messagebox.showerror("Erreur sauvegarde", f"Impossible d'enregistrer la configuration :\n{e}")
            return False

    def _reload_config(self, filepath=None, confirm=True):
        """Recharge la config depuis un fichier JSON (par défaut le fichier actif)."""
        target = filepath or self.current_config_file
        filename = os.path.basename(target)
        if confirm:
            ok = messagebox.askyesno(
                "Recharger la configuration",
                f"Voulez-vous recharger la configuration depuis '{filename}' ?\n\nToutes les modifications non enregistrées seront remplacées."
            )
            if not ok:
                return False

        if not os.path.exists(target):
            err = f"✗ Fichier introuvable: {filename}"
            self._log(f"[CFG] {err}")
            if hasattr(self, 'lbl_cfg_status'):
                self.lbl_cfg_status.config(text=err, fg=C["bad"])
            messagebox.showerror("Fichier introuvable", f"Le fichier de configuration n'existe pas :\n{target}")
            return False

        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.current_config_file = target
            self._apply_config_data(data, source_name=filename)
            now_str = time.strftime("%H:%M:%S")
            msg = f"{filename} (rechargé à {now_str})"
            self._log(f"[CFG] ✓ Configuration rechargée depuis {filename}")
            if hasattr(self, 'lbl_cfg_status'):
                self.lbl_cfg_status.config(text=msg, fg=C["accent"])
            return True
        except Exception as e:
            err = f"✗ Erreur rechargement: {e}"
            self._log(f"[CFG] {err}")
            if hasattr(self, 'lbl_cfg_status'):
                self.lbl_cfg_status.config(text=err, fg=C["bad"])
            messagebox.showerror("Erreur rechargement", f"Impossible de charger la configuration :\n{e}")
            return False

    def _export_config_dialog(self):
        """Ouvre un dialogue pour exporter la configuration courante sous un autre nom/chemin."""
        cur_name = os.path.basename(self.current_config_file)
        filepath = filedialog.asksaveasfilename(
            parent=self.root,
            title="Exporter la configuration sous...",
            initialdir=os.path.dirname(self.current_config_file),
            initialfile=cur_name,
            defaultextension=".json",
            filetypes=[("Fichiers JSON", "*.json"), ("Tous les fichiers", "*.*")]
        )
        if filepath:
            if self._save_config(filepath):
                messagebox.showinfo("Export réussi", f"Configuration exportée avec succès dans :\n{filepath}")

    def _import_config_dialog(self):
        """Ouvre un dialogue pour importer une configuration existante."""
        filepath = filedialog.askopenfilename(
            parent=self.root,
            title="Importer une configuration...",
            initialdir=os.path.dirname(self.current_config_file),
            filetypes=[("Fichiers JSON", "*.json"), ("Tous les fichiers", "*.*")]
        )
        if filepath:
            if self._reload_config(filepath, confirm=False):
                messagebox.showinfo("Import réussi", f"Configuration importée et appliquée depuis :\n{filepath}")

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
                "visible": True,
                "color_subfixtures": "",
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
                "manual_cmd": "",
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

        # Boutons Manual mode dans la top bar (un pour F1, un pour F2)
        self.btn_manual = tk.Button(top, text="✋ Manual F1", font=self.ft_large_btn,
                                    bg="#555555", fg="#ccc", bd=0, padx=12, pady=4,
                                    activebackground="#777777", activeforeground="#fff",
                                    cursor="hand2",
                                    command=lambda: self._toggle_manual(1))
        self.btn_manual.pack(side="left", padx=(8, 0))

        self.btn_manual_2 = tk.Button(top, text="✋ Manual F2", font=self.ft_large_btn,
                                      bg="#555555", fg="#ccc", bd=0, padx=12, pady=4,
                                      activebackground="#777777", activeforeground="#fff",
                                      cursor="hand2",
                                      command=lambda: self._toggle_manual(2))
        self.btn_manual_2.pack(side="left", padx=(6, 0))

        # Boutons Focus 1 et Focus 2 (actifs simultanément ou séparément)
        self.btn_focus_1 = tk.Button(top, text="🎯 Focus 1", font=self.ft_large_btn,
                                     bd=0, padx=12, pady=4, cursor="hand2",
                                     command=lambda: self._toggle_focus(1))
        self.btn_focus_1.pack(side="left", padx=(8, 0))

        self.btn_focus_2 = tk.Button(top, text="🎯 Focus 2", font=self.ft_large_btn,
                                     bd=0, padx=12, pady=4, cursor="hand2",
                                     command=lambda: self._toggle_focus(2))
        self.btn_focus_2.pack(side="left", padx=(4, 0))

        self._update_focus_buttons()

        # Bouton Vue X/Z dans la top bar (à côté des boutons Focus)
        self.btn_toggle_front = tk.Button(top, text="📐 Vue X/Z", font=self.ft_large_btn,
                                          bg=C["border"], fg=C["accent"], bd=0, padx=16, pady=4,
                                          activebackground=C["accent"], activeforeground="#000",
                                          cursor="hand2",
                                          command=self._toggle_front_panel)
        self.btn_toggle_front.pack(side="left", padx=(8, 0))

        # Contrôle rapide Z (toujours visible dans la top bar)
        self.z_ctrl_frame = tk.Frame(top, bg=C["panel"])
        self.z_ctrl_frame.pack(side="left", padx=(8, 0))
        self.btn_z_down = tk.Button(self.z_ctrl_frame, text="▼ Z-", font=self.ft_large_btn,
                                    bg=C["border"], fg=C["text"], bd=0, padx=10, pady=4,
                                    activebackground=C["accent"], activeforeground="#000",
                                    cursor="hand2",
                                    command=lambda: self._adjust_target_z(-0.25))
        self.btn_z_down.pack(side="left", padx=(0, 4))
        self.lbl_z_top = tk.Label(self.z_ctrl_frame, text=f"Z: {self.target_z:.2f}m",
                                  font=self.ft_value, bg=C["panel"], fg=C["accent"], width=9)
        self.lbl_z_top.pack(side="left", padx=2)
        self.btn_z_up = tk.Button(self.z_ctrl_frame, text="▲ Z+", font=self.ft_large_btn,
                                  bg=C["border"], fg=C["text"], bd=0, padx=10, pady=4,
                                  activebackground=C["accent"], activeforeground="#000",
                                  cursor="hand2",
                                  command=lambda: self._adjust_target_z(0.25))
        self.btn_z_up.pack(side="left", padx=(4, 0))

        # Boutons de toggle (Presets, Panneau & Logs) empilés à droite
        toggle_frame = tk.Frame(top, bg=C["panel"])
        toggle_frame.pack(side="right", padx=8)

        col_left = tk.Frame(toggle_frame, bg=C["panel"])
        col_left.pack(side="left", padx=(0, 4))
        self.btn_toggle_presets = tk.Button(col_left, text="[<] Presets", font=("Segoe UI", 8, "bold"),
                                            bg=C["border"], fg=C["accent"], bd=0, width=12,
                                            activebackground=C["accent"], activeforeground="#000",
                                            cursor="hand2", command=self._toggle_left_panel)
        self.btn_toggle_presets.pack(side="top", pady=(0, 2))

        self.btn_toggle_log = tk.Button(col_left, text="[+] Logs ESP32", font=("Segoe UI", 8, "bold"),
                                          bg=C["border"], fg=C["text"], bd=0, width=12,
                                          activebackground=C["accent"], activeforeground="#000",
                                          cursor="hand2",
                                          command=self._toggle_log_panel)
        self.btn_toggle_log.pack(side="top")

        col_right = tk.Frame(toggle_frame, bg=C["panel"])
        col_right.pack(side="left")
        self.btn_toggle_panel = tk.Button(col_right, text="[>] Panneau", font=("Segoe UI", 8, "bold"),
                                          bg=C["border"], fg=C["text"], bd=0, width=12,
                                          activebackground=C["accent"], activeforeground="#000",
                                          cursor="hand2",
                                          command=self._toggle_right_panel)
        self.btn_toggle_panel.pack(side="top", pady=(0, 2))

        self.btn_quick_save = tk.Button(col_right, text="💾 Sauver Cfg", font=("Segoe UI", 8, "bold"),
                                        bg=C["border"], fg=C["ok"], bd=0, width=12,
                                        activebackground=C["ok"], activeforeground="#000",
                                        cursor="hand2",
                                        command=self._save_config)
        self.btn_quick_save.pack(side="top")



        # Frame pour les boutons de groupes (2 lignes : FP1 et FP2)
        grp_container = tk.Frame(top, bg=C["panel"])
        grp_container.pack(side="right", padx=(16, 8))

        grp_rows = tk.Frame(grp_container, bg=C["panel"])
        grp_rows.pack(side="left")

        # Ligne 1 : Focus Point 1 (G1-G5)
        grp_frame1 = tk.Frame(grp_rows, bg=C["panel"])
        grp_frame1.pack(side="top", pady=(0, 2))
        tk.Label(grp_frame1, text="F1:", font=self.ft_grp_btn, bg=C["panel"], fg=C["tag"], width=3, anchor="e").pack(side="left", padx=(0, 4))
        self.btn_groups = {}
        for i in range(1, 6):
            btn = tk.Button(grp_frame1, text=f"G{i}", font=self.ft_grp_btn,
                            bd=0, padx=10, pady=1, cursor="hand2",
                            command=lambda grp=i: self._toggle_group(grp, 1))
            btn.pack(side="left", padx=(0, 4) if i < 5 else 0)
            self.btn_groups[i] = btn
            self._update_group_btn_color(i, 1)

        # Ligne 2 : Focus Point 2 (G1-G5)
        grp_frame2 = tk.Frame(grp_rows, bg=C["panel"])
        grp_frame2.pack(side="top")
        tk.Label(grp_frame2, text="F2:", font=self.ft_grp_btn, bg=C["panel"], fg=C["tag2"], width=3, anchor="e").pack(side="left", padx=(0, 4))
        self.btn_groups_2 = {}
        for i in range(1, 6):
            btn = tk.Button(grp_frame2, text=f"G{i}", font=self.ft_grp_btn,
                            bd=0, padx=10, pady=1, cursor="hand2",
                            command=lambda grp=i: self._toggle_group(grp, 2))
            btn.pack(side="left", padx=(0, 4) if i < 5 else 0)
            self.btn_groups_2[i] = btn
            self._update_group_btn_color(i, 2)

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

        # --- Main: left preset panel + center canvas + right panel ---
        self.main_panes = tk.PanedWindow(self.root, orient="horizontal",
                               bg=C["bg"], bd=0, sashwidth=4)
        self.main_panes.pack(fill="both", expand=True, padx=4, pady=4)

        # Left panel (Presets & Couleurs)
        self.left_panel = tk.Frame(self.main_panes, bg=C["panel"], width=340)
        self.main_panes.add(self.left_panel, stretch="never")
        self._build_left_panel()

        # Canvas frame (center)
        self.canvas_frame = tk.Frame(self.main_panes, bg=C["bg"])
        self.main_panes.add(self.canvas_frame, stretch="always")

        # Right panel
        self.right_panel = tk.Frame(self.main_panes, bg=C["panel"], width=280)
        self.main_panes.add(self.right_panel, stretch="never")

        # --- Canvases ---
        self.left_panes = tk.PanedWindow(self.canvas_frame, orient="vertical", bg=C["border"], bd=0, sashwidth=4)
        self.left_panes.pack(fill="both", expand=True)

        top_border = tk.Frame(self.left_panes, bg=C["border"], padx=2, pady=2)
        self.left_panes.add(top_border, stretch="always")
        self.canvas_top = tk.Canvas(top_border, bg=C["canvas_bg"], highlightthickness=0, cursor="crosshair")
        self.canvas_top.pack(fill="both", expand=True)
        self.canvas_top.bind("<Configure>", lambda e: self._draw())
        self.canvas_top.bind("<ButtonPress-1>", lambda e: self._on_press(e, "top"))
        self.canvas_top.bind("<B1-Motion>", lambda e: self._on_drag(e, "top"))
        self.canvas_top.bind("<ButtonRelease-1>", self._on_release)

        self.front_border = tk.Frame(self.left_panes, bg=C["border"], padx=2, pady=2)
        self.left_panes.add(self.front_border, stretch="always")
        self.canvas_front = tk.Canvas(self.front_border, bg=C["canvas_bg"], highlightthickness=0, cursor="crosshair")
        self.canvas_front.pack(fill="both", expand=True)
        self.canvas_front.bind("<Configure>", lambda e: self._draw())
        self.canvas_front.bind("<ButtonPress-1>", lambda e: self._on_press(e, "front"))
        self.canvas_front.bind("<B1-Motion>", lambda e: self._on_drag(e, "front"))
        self.canvas_front.bind("<ButtonRelease-1>", self._on_release)

        # --- Log frame (bottom of left, initially hidden) ---
        self.log_frame = tk.Frame(self.left_panes, bg=C["log_bg"], height=120)
        self.log_frame.pack_propagate(False)

        tk.Label(self.log_frame, text=" 📡 Messages ESP32", font=self.ft_label,
                 bg=C["log_bg"], fg=C["accent"], anchor="w").pack(fill="x")

        self.log_text = tk.Text(self.log_frame, bg=C["log_bg"], fg=C["log_text"],
                                 font=self.ft_log, wrap="none", bd=0,
                                 highlightthickness=0, state="disabled",
                                 height=6)
        self.log_text.pack(fill="both", expand=True, padx=4, pady=2)

        # Raccourcis clavier pour sauvegarder / recharger / importer
        self.root.bind("<Control-s>", lambda e: self._save_config())
        self.root.bind("<Control-S>", lambda e: self._save_config())
        self.root.bind("<Control-o>", lambda e: self._import_config_dialog())
        self.root.bind("<Control-O>", lambda e: self._import_config_dialog())
        self.root.bind("<Control-r>", lambda e: self._reload_config())
        self.root.bind("<Control-R>", lambda e: self._reload_config())

        # --- Right panel content ---
        self._build_panel(self.right_panel)

    def _build_panel(self, parent):
        parent.columnconfigure(0, weight=1)

        # CONFIGURATION
        self._section(parent, "📁 CONFIGURATION")
        cfg_frame = tk.Frame(parent, bg=C["panel"])
        cfg_frame.pack(fill="x", padx=8, pady=2)

        f_cfg_r1 = tk.Frame(cfg_frame, bg=C["panel"])
        f_cfg_r1.pack(fill="x", pady=2)
        btn_save = tk.Button(f_cfg_r1, text="💾 Sauvegarder", font=self.ft_label,
                             bg=C["border"], fg=C["ok"], bd=0, padx=6, pady=3,
                             activebackground=C["ok"], activeforeground="#000",
                             cursor="hand2", command=self._save_config)
        btn_save.pack(side="left", fill="x", expand=True, padx=(0, 2))

        btn_reload = tk.Button(f_cfg_r1, text="🔄 Recharger", font=self.ft_label,
                               bg=C["border"], fg=C["accent"], bd=0, padx=6, pady=3,
                               activebackground=C["accent"], activeforeground="#000",
                               cursor="hand2", command=self._reload_config)
        btn_reload.pack(side="left", fill="x", expand=True, padx=(2, 0))

        f_cfg_r2 = tk.Frame(cfg_frame, bg=C["panel"])
        f_cfg_r2.pack(fill="x", pady=(2, 4))
        btn_export = tk.Button(f_cfg_r2, text="📤 Exporter...", font=self.ft_small,
                               bg=C["border"], fg=C["text"], bd=0, padx=4, pady=2,
                               activebackground=C["dim"], activeforeground="#fff",
                               cursor="hand2", command=self._export_config_dialog)
        btn_export.pack(side="left", fill="x", expand=True, padx=(0, 2))

        btn_import = tk.Button(f_cfg_r2, text="📥 Importer...", font=self.ft_small,
                               bg=C["border"], fg=C["text"], bd=0, padx=4, pady=2,
                               activebackground=C["dim"], activeforeground="#fff",
                               cursor="hand2", command=self._import_config_dialog)
        btn_import.pack(side="left", fill="x", expand=True, padx=(2, 0))

        cfg_name = os.path.basename(self.current_config_file)
        self.lbl_cfg_status = tk.Label(cfg_frame, text=f"{cfg_name} (prêt)",
                                       font=("Segoe UI", 8), bg=C["panel"], fg=C["dim"])
        self.lbl_cfg_status.pack(anchor="w", pady=(0, 2))

        # DIMENSIONS SCÈNE (m)
        self._section(parent, "📐 DIMENSIONS SCÈNE (m)")
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

        # Row 2: Appliquer dimensions
        btn_apply = tk.Button(sz_frame, text="Appliquer dimensions", font=self.ft_small,
                               bg=C["border"], fg=C["text"], bd=0, padx=8, pady=2,
                               activebackground=C["accent"], activeforeground="#000",
                               cursor="hand2", command=self._apply_stage_size)
        btn_apply.pack(fill="x", pady=4)

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

        # Masquer Anchors
        self.var_hide_anchors = tk.BooleanVar(value=self.cfg.get("hide_anchors", False))
        cb_hide_anchors = tk.Checkbutton(parent, text="Masquer les Anchors", variable=self.var_hide_anchors,
                                         font=self.ft_small, bg=C["panel"], fg=C["text"],
                                         selectcolor=C["bg"], activebackground=C["panel"], activeforeground=C["text"],
                                         command=self._draw)
        cb_hide_anchors.pack(anchor="w", padx=8, pady=(4, 0))

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
        top.geometry("340x590")
        top.transient(self.root)
        top.grab_set()

        def _row(parent, label, key, default):
            f = tk.Frame(parent, bg=C["bg"])
            f.pack(fill="x", padx=10, pady=4)
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

        v_vis = _check(top, "Visible sur le plan", "visible", True)
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
        e_col_sub = _row(top, "Sous-fix. Couleur", "color_subfixtures", "")
        tk.Label(top, text="  ↳ ex: .2 Thru .4  (ou vide si lyre standard)",
                 font=("Segoe UI", 7), bg=C["bg"], fg=C["dim"], anchor="w").pack(fill="x", padx=12, pady=(0, 2))

        # Zone de texte : commande MA2 supplémentaire à l'activation du mode Manual
        f_cmd = tk.Frame(top, bg=C["bg"])
        f_cmd.pack(fill="x", padx=10, pady=(8, 2))
        f_cmd_hdr = tk.Frame(f_cmd, bg=C["bg"])
        f_cmd_hdr.pack(fill="x")
        tk.Label(f_cmd_hdr, text="Commande MA2 (mode Manual) :", font=self.ft_label,
                 bg=C["bg"], fg=C["accent"], anchor="w").pack(side="left")
        txt_cmd = tk.Text(f_cmd, height=3, font=self.ft_small, bg=C["canvas_bg"],
                          fg=C["text"], insertbackground=C["text"], bd=1, wrap="word")
        btn_help = tk.Button(f_cmd_hdr, text="?", font=("Segoe UI", 9, "bold"),
                             bg=C["border"], fg=C["accent"], bd=0, padx=6, pady=0,
                             activebackground=C["accent"], activeforeground="#000",
                             cursor="hand2",
                             command=lambda: self._show_manual_cmd_help(top, txt_cmd))
        btn_help.pack(side="right")
        tk.Label(f_cmd, text="Ex: At 100 ; At Preset 4.1  (cliquez sur ? pour l'aide)",
                 font=("Segoe UI", 8), bg=C["bg"], fg=C["dim"], anchor="w").pack(fill="x")
        txt_cmd.insert("1.0", str(fx.get("manual_cmd", "")))
        txt_cmd.pack(fill="x", pady=(2, 0))
        
        def _save():
            try:
                fx["visible"] = v_vis.get()
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
                fx["color_subfixtures"] = e_col_sub.get().strip()
                fx["manual_cmd"] = txt_cmd.get("1.0", "end-1c").strip()
                with self.ma2_lock:
                    self.ma2_resend_manual_cmd = True
                self._save_config()
                self._build_fixtures_list()
                self._draw()
                top.destroy()
            except ValueError:
                pass
                
        tk.Button(top, text="Sauvegarder", font=self.ft_small, bg=C["border"], fg=C["accent"], bd=0, padx=12, pady=4, command=_save).pack(pady=12)

    def _show_manual_cmd_help(self, parent_win, txt_target=None):
        hlp = tk.Toplevel(parent_win)
        hlp.title("❓ Aide — Commandes MA2 (Mode Manual)")
        hlp.configure(bg=C["bg"])
        hlp.geometry("620x650")
        hlp.transient(parent_win)
        hlp.grab_set()

        # Canvas défilant pour accueillir tous les exemples et explications
        cv = tk.Canvas(hlp, bg=C["bg"], highlightthickness=0)
        sb = tk.Scrollbar(hlp, orient="vertical", command=cv.yview)
        sf = tk.Frame(cv, bg=C["bg"])

        sf.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv_win = cv.create_window((0, 0), window=sf, anchor="nw")
        cv.bind("<Configure>", lambda e: cv.itemconfig(cv_win, width=e.width))
        cv.configure(yscrollcommand=sb.set)

        def _on_mousewheel(event):
            try:
                if cv.winfo_exists():
                    cv.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except:
                pass
        cv.bind_all("<MouseWheel>", _on_mousewheel)

        def _close_help():
            try:
                cv.unbind_all("<MouseWheel>")
            except:
                pass
            hlp.destroy()
        hlp.protocol("WM_DELETE_WINDOW", _close_help)

        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        tk.Label(sf, text="Guide & Exemples — Commandes MA2 (Mode Manual)",
                 font=self.ft_section, bg=C["bg"], fg=C["accent"]).pack(anchor="w", padx=14, pady=(12, 6))

        # Encadré explicatif pour {id} et {sub}
        info_frame = tk.Frame(sf, bg=C["panel"], padx=10, pady=8, highlightbackground=C["border"], highlightthickness=1)
        info_frame.pack(fill="x", padx=14, pady=(0, 10))

        tk.Label(info_frame, text="💡 Utilisation des variables dynamiques {id} et {sub} :",
                 font=("Segoe UI", 9, "bold"), bg=C["panel"], fg=C["fixture"]).pack(anchor="w")

        info_text = (
            "• {id}  : Remplacé par l'ID GrandMA2 de la lyre (ex: 301)\n"
            "• {sub} : Remplacé par les sous-fixtures définies dans 'Sous-fix. Couleur'\n"
            "          (ex: 301.2 Thru 301.4, ou 301 si non défini)\n\n"
            "Deux syntaxes sont possibles :\n"
            "1. Syntaxe explicite avec {id} ou {sub} (recommandée) :\n"
            "   Exemple : Fixture {id} At 100 ; Fixture {sub} At Preset 4.1\n"
            "2. Raccourci automatique :\n"
            "   Si vous commencez directement par 'At ...', 'Attribute ...' ou 'Stomp ...',\n"
            "   le dashboard ajoute automatiquement 'Fixture {id}' devant chaque commande.\n"
            "   Exemple : 'At 100 ; At Preset 4.1' devient 'Fixture 301 At 100 ; Fixture 301 At Preset 4.1'\n"
            "• Séparez plusieurs instructions par ';' ou par un saut de ligne."
        )
        tk.Label(info_frame, text=info_text, font=self.ft_small, bg=C["panel"],
                 fg=C["text"], justify="left", anchor="w").pack(fill="x", pady=(4, 0))

        examples = [
            ("1. Avec Preset Couleur « Blanc » (syntaxe explicite avec {id})",
             "Dimmer à 100% sur la lyre principale + 1er preset de la piscine Color (4.1) :",
             'Fixture {id} At 100 ; Fixture {id} At Preset 4.1'),

            ("2. Lyre multi-instances / sous-fixtures (Aura, Wash LEDs)",
             "Dimmer sur le corps ({id}) et couleur sur les sous-fixtures ({sub}) :",
             'Fixture {id} At 100 ; Fixture {sub} At 100 ; Fixture {sub} At Preset 4.1'),

            ("3. Blanc universel sans preset (valeur par défaut console)",
             "Dimmer à 100% + réinitialise la fonction Color à sa valeur par défaut (Open/Blanc) :",
             'Fixture {id} At 100 ; Fixture {id} PresetType "Color" At Default'),

            ("4. Lyre à roue de couleurs (Color1)",
             "Dimmer à 100% + positionne la roue de couleur 1 à 0 (Open/Blanc) :",
             'Fixture {id} At 100 ; Fixture {id} Attribute "Color1" At 0'),

            ("5. Lyre LED RGB / RGBW directe (canaux ColorRGB)",
             "Dimmer à 100% + rouge, vert, bleu et blanc à 100% :",
             'Fixture {id} At 100 ; Fixture {id} Attribute "ColorRGB1" At 100 ; Fixture {id} Attribute "ColorRGB2" At 100 ; Fixture {id} Attribute "ColorRGB3" At 100 ; Fixture {id} Attribute "ColorRGB5" At 100'),

            ("6. Bloquer les effets en cours (Stomp) + Allumer",
             "Stompe les effets de Dimmer & Couleur d'autres séquences puis allume en blanc :",
             'Fixture {id} Stomp PresetType "Dimmer" ; Fixture {id} Stomp PresetType "Color" ; Fixture {id} At 100 ; Fixture {id} PresetType "Color" At Default'),

            ("7. Raccourci automatique (sans taper 'Fixture {id}')",
             "Écriture courte équivalente à l'exemple 1 (le dashboard injecte automatiquement 'Fixture {id}') :",
             'At 100 ; At Preset 4.1'),
        ]

        for title, desc, cmd_str in examples:
            box = tk.Frame(sf, bg=C["panel"], padx=8, pady=6, highlightbackground=C["border"], highlightthickness=1)
            box.pack(fill="x", padx=14, pady=3)
            tk.Label(box, text=title, font=("Segoe UI", 9, "bold"), bg=C["panel"], fg=C["fixture"], anchor="w").pack(fill="x")
            tk.Label(box, text=desc, font=("Segoe UI", 8), bg=C["panel"], fg=C["dim"], anchor="w").pack(fill="x")

            cmd_row = tk.Frame(box, bg=C["panel"])
            cmd_row.pack(fill="x", pady=(3, 0))
            ent_ex = tk.Entry(cmd_row, font=self.ft_small, bg=C["canvas_bg"], fg=C["log_text"],
                              readonlybackground=C["canvas_bg"], bd=1)
            ent_ex.insert(0, cmd_str.replace("\n", " ; "))
            ent_ex.config(state="readonly")
            ent_ex.pack(side="left", fill="x", expand=True, padx=(0, 6))

            if txt_target is not None:
                def _use_cmd(c=cmd_str):
                    txt_target.delete("1.0", "end")
                    txt_target.insert("1.0", c)
                    _close_help()
                tk.Button(cmd_row, text="Utiliser", font=("Segoe UI", 8, "bold"),
                          bg=C["border"], fg=C["accent"], bd=0, padx=8, pady=1,
                          activebackground=C["accent"], activeforeground="#000",
                          cursor="hand2", command=_use_cmd).pack(side="right")

        tk.Button(sf, text="Fermer", font=self.ft_small, bg=C["border"], fg=C["text"],
                  bd=0, padx=16, pady=4, command=_close_help).pack(pady=14)

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
            
            is_vis = fx.get("visible", True)
            name_fg = C["fixture"] if is_vis else C["dim"]
            name_txt = f"{fx['name']}:" if is_vis else f"{fx['name']} (off):"
            tk.Label(f, text=name_txt, font=self.ft_small,
                     bg=C["panel"], fg=name_fg).pack(side="left")
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

    def _build_left_panel(self):
        # Header
        top_f = tk.Frame(self.left_panel, bg=C["panel"], padx=8, pady=6)
        top_f.pack(fill="x")

        tk.Label(top_f, text="🎯 PRESETS & COULEURS", font=self.ft_section,
                 bg=C["panel"], fg=C["accent"]).pack(anchor="w")

        btn_row = tk.Frame(top_f, bg=C["panel"])
        btn_row.pack(fill="x", pady=(6, 2))

        self.btn_save_preset = tk.Button(btn_row, text="💾 Save to Preset",
                                         font=("Segoe UI", 10, "bold"),
                                         bg=C["border"], fg=C["text"], bd=0, padx=8, pady=5,
                                         activebackground=C["accent"], activeforeground="#000",
                                         cursor="hand2", command=self._toggle_save_preset_mode)
        self.btn_save_preset.pack(fill="x")

        self.lbl_save_hint = tk.Label(top_f, text="Cliquez sur un preset F1 ou F2 pour charger sa position",
                                      font=("Segoe UI", 8), bg=C["panel"], fg=C["dim"], anchor="w")
        self.lbl_save_hint.pack(fill="x")

        tk.Frame(self.left_panel, bg=C["border"], height=1).pack(fill="x", padx=8, pady=(4, 6))

        # Zone scrollable
        cv = tk.Canvas(self.left_panel, bg=C["panel"], highlightthickness=0, width=320)
        sb = tk.Scrollbar(self.left_panel, orient="vertical", command=cv.yview)
        sf = tk.Frame(cv, bg=C["panel"])

        sf.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv_win = cv.create_window((0, 0), window=sf, anchor="nw")
        cv.bind("<Configure>", lambda e: cv.itemconfig(cv_win, width=e.width))
        cv.configure(yscrollcommand=sb.set)

        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def _on_wheel(event):
            cv.yview_scroll(int(-1 * (event.delta / 120)), "units")
        cv.bind("<Enter>", lambda e: cv.bind_all("<MouseWheel>", _on_wheel))
        cv.bind("<Leave>", lambda e: cv.unbind_all("<MouseWheel>"))

        self.focus_preset_buttons = {1: [], 2: []}
        self.color_swatch_btns = {1: [], 2: []}
        self.color_swatch_boxes = {1: [], 2: []}

        # 8 Couleurs standards (Nom, Hex, (R, G, B) 0-100)
        self.COLOR_SWATCHES = [
            ("Blanc",   "#FFFFFF", (100, 100, 100)),
            ("Rouge",   "#FF3333", (100, 0, 0)),
            ("Vert",    "#33FF33", (0, 100, 0)),
            ("Bleu",    "#3366FF", (0, 0, 100)),
            ("Jaune",   "#FFFF33", (100, 100, 0)),
            ("Cyan",    "#33FFFF", (0, 100, 100)),
            ("Magenta", "#FF33FF", (100, 0, 100)),
            ("Orange",  "#FF8800", (100, 45, 0)),
        ]

        # --- SECTION FOCUS 1 ---
        card_f1 = tk.Frame(sf, bg=C["canvas_bg"], highlightbackground=C["border"],
                           highlightthickness=1, padx=6, pady=6)
        card_f1.pack(fill="x", padx=8, pady=4)

        hdr_f1 = tk.Frame(card_f1, bg=C["canvas_bg"])
        hdr_f1.pack(fill="x", pady=(0, 4))
        tk.Label(hdr_f1, text="🎯 PRESETS FOCUS 1", font=("Segoe UI", 10, "bold"),
                 bg=C["canvas_bg"], fg=C["tag"]).pack(side="left")

        grid_f1 = tk.Frame(card_f1, bg=C["canvas_bg"])
        grid_f1.pack(fill="x", pady=2)
        for c in range(4): grid_f1.grid_columnconfigure(c, weight=1, uniform="f1_p")
        for r in range(2): grid_f1.grid_rowconfigure(r, weight=1, uniform="f1_p")

        presets_1 = self.focus_presets.get("1", [])
        for row in range(2):
            for col in range(4):
                idx = row * 4 + col
                p_info = presets_1[idx] if idx < len(presets_1) else {"label": f"P{idx+1}", "empty": True}
                lbl = p_info.get("label", f"P{idx+1}")
                is_empty = p_info.get("empty", True)

                btn = tk.Button(grid_f1, text=lbl, font=("Segoe UI", 10, "bold"),
                                bg=C["border"] if is_empty else "#241618",
                                fg=C["dim"] if is_empty else C["tag"],
                                activebackground=C["tag"], activeforeground="#fff",
                                bd=0, relief="flat", highlightthickness=0,
                                height=2, pady=10, cursor="hand2",
                                command=lambda i=idx: self._on_preset_click(1, i))
                btn.bind("<Button-3>", lambda e, i=idx: self._save_focus_preset_dialog(1, i))
                btn.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)
                self.focus_preset_buttons[1].append(btn)

        col_hdr_f1 = tk.Frame(card_f1, bg=C["canvas_bg"])
        col_hdr_f1.pack(fill="x", pady=(10, 4))
        tk.Label(col_hdr_f1, text="🎨 COULEURS FOCUS 1", font=("Segoe UI", 10, "bold"),
                 bg=C["canvas_bg"], fg=C["tag"]).pack(side="left")

        grid_col1 = tk.Frame(card_f1, bg=C["canvas_bg"])
        grid_col1.pack(fill="x", pady=2)
        for c in range(4): grid_col1.grid_columnconfigure(c, weight=1, uniform="f1_c")
        for r in range(2): grid_col1.grid_rowconfigure(r, weight=1, uniform="f1_c")

        cur_col1 = self.focus_current_color.get("1", "#FFFFFF").upper()
        for row in range(2):
            for col in range(4):
                idx = row * 4 + col
                c_name, c_hex, c_rgb = self.COLOR_SWATCHES[idx]
                is_selected = (c_hex.upper() == cur_col1)
                hl = ("#00d4ff" if c_hex.upper() in ["#FFFFFF", "#FFFF33", "#33FFFF"] else "#FFFFFF") if is_selected else C["canvas_bg"]

                box = tk.Frame(grid_col1, bg=hl, padx=3, pady=3, cursor="hand2")
                box.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)
                box.bind("<Button-1>", lambda e, name=c_name, hx=c_hex, rgb=c_rgb: self._apply_focus_color(1, name, hx, rgb))

                swatch = tk.Button(box, text="", bg=c_hex, activebackground=c_hex,
                                   bd=0, relief="flat", highlightthickness=0,
                                   height=2, pady=10, cursor="hand2",
                                   command=lambda name=c_name, hx=c_hex, rgb=c_rgb: self._apply_focus_color(1, name, hx, rgb))
                swatch.pack(fill="both", expand=True)

                self.color_swatch_boxes[1].append(box)
                self.color_swatch_btns[1].append(swatch)

        # --- SECTION FOCUS 2 ---
        card_f2 = tk.Frame(sf, bg=C["canvas_bg"], highlightbackground=C["border"],
                           highlightthickness=1, padx=6, pady=6)
        card_f2.pack(fill="x", padx=8, pady=4)

        hdr_f2 = tk.Frame(card_f2, bg=C["canvas_bg"])
        hdr_f2.pack(fill="x", pady=(0, 4))
        tk.Label(hdr_f2, text="🎯 PRESETS FOCUS 2", font=("Segoe UI", 10, "bold"),
                 bg=C["canvas_bg"], fg=C["tag2"]).pack(side="left")

        grid_f2 = tk.Frame(card_f2, bg=C["canvas_bg"])
        grid_f2.pack(fill="x", pady=2)
        for c in range(4): grid_f2.grid_columnconfigure(c, weight=1, uniform="f2_p")
        for r in range(2): grid_f2.grid_rowconfigure(r, weight=1, uniform="f2_p")

        presets_2 = self.focus_presets.get("2", [])
        for row in range(2):
            for col in range(4):
                idx = row * 4 + col
                p_info = presets_2[idx] if idx < len(presets_2) else {"label": f"P{idx+1}", "empty": True}
                lbl = p_info.get("label", f"P{idx+1}")
                is_empty = p_info.get("empty", True)

                btn = tk.Button(grid_f2, text=lbl, font=("Segoe UI", 10, "bold"),
                                bg=C["border"] if is_empty else "#0f2630",
                                fg=C["dim"] if is_empty else C["tag2"],
                                activebackground=C["tag2"], activeforeground="#000",
                                bd=0, relief="flat", highlightthickness=0,
                                height=2, pady=10, cursor="hand2",
                                command=lambda i=idx: self._on_preset_click(2, i))
                btn.bind("<Button-3>", lambda e, i=idx: self._save_focus_preset_dialog(2, i))
                btn.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)
                self.focus_preset_buttons[2].append(btn)

        col_hdr_f2 = tk.Frame(card_f2, bg=C["canvas_bg"])
        col_hdr_f2.pack(fill="x", pady=(10, 4))
        tk.Label(col_hdr_f2, text="🎨 COULEURS FOCUS 2", font=("Segoe UI", 10, "bold"),
                 bg=C["canvas_bg"], fg=C["tag2"]).pack(side="left")

        grid_col2 = tk.Frame(card_f2, bg=C["canvas_bg"])
        grid_col2.pack(fill="x", pady=2)
        for c in range(4): grid_col2.grid_columnconfigure(c, weight=1, uniform="f2_c")
        for r in range(2): grid_col2.grid_rowconfigure(r, weight=1, uniform="f2_c")

        cur_col2 = self.focus_current_color.get("2", "#FFFFFF").upper()
        for row in range(2):
            for col in range(4):
                idx = row * 4 + col
                c_name, c_hex, c_rgb = self.COLOR_SWATCHES[idx]
                is_selected = (c_hex.upper() == cur_col2)
                hl = ("#00d4ff" if c_hex.upper() in ["#FFFFFF", "#FFFF33", "#33FFFF"] else "#FFFFFF") if is_selected else C["canvas_bg"]

                box = tk.Frame(grid_col2, bg=hl, padx=3, pady=3, cursor="hand2")
                box.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)
                box.bind("<Button-1>", lambda e, name=c_name, hx=c_hex, rgb=c_rgb: self._apply_focus_color(2, name, hx, rgb))

                swatch = tk.Button(box, text="", bg=c_hex, activebackground=c_hex,
                                   bd=0, relief="flat", highlightthickness=0,
                                   height=2, pady=10, cursor="hand2",
                                   command=lambda name=c_name, hx=c_hex, rgb=c_rgb: self._apply_focus_color(2, name, hx, rgb))
                swatch.pack(fill="both", expand=True)

                self.color_swatch_boxes[2].append(box)
                self.color_swatch_btns[2].append(swatch)

    def _toggle_left_panel(self):
        if str(self.left_panel) in [str(p) for p in self.main_panes.panes()]:
            self.main_panes.forget(self.left_panel)
            self.btn_toggle_presets.config(text="[>] Presets", fg=C["text"])
        else:
            self.main_panes.add(self.left_panel, before=self.canvas_frame, stretch="never")
            self.btn_toggle_presets.config(text="[<] Presets", fg=C["accent"])
        self._draw()

    def _toggle_save_preset_mode(self, force_off=False):
        if force_off:
            self.preset_save_mode = False
        else:
            self.preset_save_mode = not self.preset_save_mode

        if self.preset_save_mode:
            self.btn_save_preset.config(text="⚠️ CHOIX DU PRESET...", bg="#cc8800", fg="#000")
            self.lbl_save_hint.config(text="Cliquez sur un bouton P1-P8 pour y enregistrer la position", fg="#ffcc00")
            self._log("[PRESET] Mode enregistrement actif : cliquez sur le preset F1 ou F2 à écraser")
        else:
            self.btn_save_preset.config(text="💾 Save to Preset", bg=C["border"], fg=C["text"])
            self.lbl_save_hint.config(text="Cliquez sur un preset F1 ou F2 pour charger sa position", fg=C["dim"])

    def _on_preset_click(self, fp, idx):
        if self.preset_save_mode:
            self._save_focus_preset_dialog(fp, idx)
            self._toggle_save_preset_mode(force_off=True)
        else:
            self._recall_focus_preset(fp, idx)

    def _save_focus_preset_dialog(self, fp, idx):
        s_fp = str(fp)
        p_info = self.focus_presets[s_fp][idx]
        old_lbl = p_info.get("label", f"P{idx+1}")

        label = simpledialog.askstring(
            "Sauvegarder Preset",
            f"Nom court pour le preset {idx+1} (Focus {fp}) :",
            initialvalue=old_lbl if not p_info.get("empty", True) else f"P{idx+1}",
            parent=self.root
        )
        if label is None:
            return

        label = label.strip()[:10]
        if not label:
            label = f"P{idx+1}"

        if fp == 1:
            cur_x = self.display_x
            cur_y = self.display_y
            cur_z = self.target_z
        else:
            cur_x = self.fp2_x
            cur_y = self.fp2_y
            cur_z = self.fp2_z

        self.focus_presets[s_fp][idx] = {
            "label": label,
            "x": round(cur_x, 2),
            "y": round(cur_y, 2),
            "z": round(cur_z, 2),
            "empty": False
        }

        btn = self.focus_preset_buttons[fp][idx]
        btn.config(text=label,
                   bg="#241618" if fp == 1 else "#0f2630",
                   fg=C["tag"] if fp == 1 else C["tag2"],
                   font=("Segoe UI", 10, "bold"))

        self._save_config()
        self._highlight_active_preset(fp, idx)
        self._log(f"[PRESET] Focus {fp} P{idx+1} '{label}' sauvegardé à ({cur_x:.2f}m, {cur_y:.2f}m, Z={cur_z:.2f}m)")

    def _recall_focus_preset(self, fp, idx):
        s_fp = str(fp)
        p_info = self.focus_presets[s_fp][idx]
        if p_info.get("empty", True):
            self._log(f"[PRESET] Focus {fp} P{idx+1} est vide — utilisez 'Save to Preset' pour enregistrer")
            return

        tx = p_info["x"]
        ty = p_info["y"]
        tz = p_info["z"]

        if fp == 1:
            self.tag_x = self.display_x = tx
            self.tag_y = self.display_y = ty
            self.target_z = tz
            if hasattr(self, 'lbl_z_top') and self.focus1_active:
                self.lbl_z_top.config(text=f"Z: {self.target_z:.2f}m")
        else:
            self.fp2_x = tx
            self.fp2_y = ty
            self.fp2_z = tz
            if hasattr(self, 'lbl_z_top') and self.focus2_active:
                self.lbl_z_top.config(text=f"Z: {self.fp2_z:.2f}m")

        self._highlight_active_preset(fp, idx)
        self._draw()
        self._log(f"[PRESET] Focus {fp} -> '{p_info['label']}' ({tx:.2f}m, {ty:.2f}m, Z={tz:.2f}m)")

    def _highlight_active_preset(self, fp, active_idx):
        if fp not in self.focus_preset_buttons:
            return
        s_fp = str(fp)
        presets = self.focus_presets[s_fp]
        accent_col = C["tag"] if fp == 1 else C["tag2"]
        saved_bg = "#241618" if fp == 1 else "#0f2630"
        active_bg = "#772222" if fp == 1 else "#005577"
        for i, btn in enumerate(self.focus_preset_buttons[fp]):
            is_empty = presets[i].get("empty", True)
            if i == active_idx:
                btn.config(bg=active_bg, fg="#ffffff", font=("Segoe UI", 10, "bold"))
            else:
                btn.config(bg=C["border"] if is_empty else saved_bg,
                           fg=C["dim"] if is_empty else accent_col,
                           font=("Segoe UI", 10, "bold"))

    def _get_fixture_color_target(self, fx, gma_id):
        """
        Détermine la cible MA2 pour la couleur d'une lyre (support des sous-fixtures).
        - Si vide : retourne str(gma_id) (ex: '301')
        - Syntaxe relative avec points (ex: '.2 Thru .4', '.2 + .3') :
          remplace les '.X' par '{gma_id}.X' -> '301.2 Thru 301.4'
        - Syntaxe relative sans points (ex: '2 Thru 4') :
          transforme en '{gma_id}.2 Thru {gma_id}.4'
        - Syntaxe absolue (ex: '301.2 Thru 301.4' ou '501') :
          conservée telle quelle
        """
        sub = str(fx.get("color_subfixtures", "")).strip()
        if not sub:
            return str(gma_id)

        # Si le pattern contient des points non précédés d'un chiffre (ex: ".2 Thru .4", ".2 + .3", ".2")
        if re.search(r'(?<!\d)\.(\d+)', sub):
            return re.sub(r'(?<!\d)\.(\d+)', rf'{gma_id}.\1', sub)

        # Si le pattern est "X Thru Y" sans point (ex: "2 Thru 4")
        m_thru = re.match(r'^(\d+)\s+thru\s+(\d+)$', sub, re.IGNORECASE)
        if m_thru:
            return f"{gma_id}.{m_thru.group(1)} Thru {gma_id}.{m_thru.group(2)}"

        # Si c'est déjà un identifiant absolu ou une cible personnalisée
        return sub

    def _is_focus_active(self, fp):
        """Retourne True si le Focus concerné est actif pour le contrôle des projecteurs."""
        if fp == 1:
            return bool(self.test_mode.get() or self.connected)
        else:
            return bool(self.test_mode_2.get())

    def _get_swatch_by_hex(self, hex_code):
        """Retourne (name, hex_code, (r, g, b)) correspondant à un code hexadécimal."""
        hex_u = str(hex_code).upper()
        for name, s_hex, rgb in self.COLOR_SWATCHES:
            if s_hex.upper() == hex_u:
                return name, s_hex, rgb
        return "Blanc", "#FFFFFF", (100, 100, 100)

    def _get_focus_color_targets(self, fp):
        """Récupère les cibles GrandMA2 (lyres ou sous-fixtures) pour le Focus fp."""
        color_targets = []
        for j, fx in enumerate(self.fixtures):
            if not fx.get("visible", True):
                continue
            try:
                if hasattr(self, 'fx_grp_entries') and j < len(self.fx_grp_entries):
                    fx["group"] = max(1, min(5, int(self.fx_grp_entries[j].get())))
            except:
                pass
            grp = fx.get("group", 1)
            in_fp = self.group_toggles.get(grp, False) if fp == 1 else self.group_toggles_2.get(grp, False)
            if in_fp:
                try:
                    gid = int(self.fx_ma2_entries[j].get())
                except:
                    gid = fx.get("gma_id", j + 1)
                target = self._get_fixture_color_target(fx, gid)
                if target and target not in color_targets:
                    color_targets.append(target)
        return color_targets

    def _send_focus_color_to_ma2(self, fp):
        """
        Envoie la couleur configurée du Focus fp vers GrandMA2 avec priorité absolue :
        Freeze On + Stomp PresetType Color sur chaque cible pour stopper les effets MA2,
        puis assignation des attributs RGBW.
        """
        if not self._is_focus_active(fp):
            return

        color_targets = self._get_focus_color_targets(fp)
        if not color_targets:
            return

        s_fp = str(fp)
        hex_code = self.focus_current_color.get(s_fp, "#FFFFFF")
        name, _, rgb = self._get_swatch_by_hex(hex_code)
        g_str = " + ".join(color_targets)
        r, g_val, b = rgb

        cmd_lines = ["Freeze On"]
        for t in color_targets:
            # Stomp de tout effet de couleur actif sur cette fixture/sous-fixture pour que le dashboard prenne la priorité absolue
            cmd_lines.append(f'Fixture {t} Stomp PresetType "Color"')
            if name == "Blanc":
                cmd_lines.extend([
                    f'Fixture {t} Attribute "ColorRGB1" At 100',
                    f'Fixture {t} Attribute "ColorRGB2" At 100',
                    f'Fixture {t} Attribute "ColorRGB3" At 100',
                    f'Fixture {t} Attribute "ColorRGB5" At 100',
                    f'Fixture {t} PresetType "Color" At Default',
                ])
            else:
                cmd_lines.extend([
                    f'Fixture {t} Attribute "ColorRGB1" At {r}',
                    f'Fixture {t} Attribute "ColorRGB2" At {g_val}',
                    f'Fixture {t} Attribute "ColorRGB3" At {b}',
                    f'Fixture {t} Attribute "ColorRGB5" At 0',
                ])
        cmd = "\r\n".join(cmd_lines) + "\r\n"
        self._send_ma2_direct(cmd)
        self._log(f"[MA2] ✓ Focus {fp} ({g_str}) Couleur -> {name} (Priorité/Stomp OK)")

    def _apply_focus_color(self, fp, name, hex_code, rgb):
        s_fp = str(fp)
        self.focus_current_color[s_fp] = hex_code

        # Mise à jour du cadre de sélection (zéro décalage de géométrie)
        if fp in self.color_swatch_boxes:
            for s_box, (_, s_hex, _) in zip(self.color_swatch_boxes[fp], self.COLOR_SWATCHES):
                if s_hex.upper() == hex_code.upper():
                    hl = "#00d4ff" if s_hex.upper() in ["#FFFFFF", "#FFFF33", "#33FFFF"] else "#FFFFFF"
                    s_box.config(bg=hl)
                else:
                    s_box.config(bg=C["canvas_bg"])

        self._save_config()

        # Si le Focus n'est pas actif (Manual éteint et pas de suivi live), on ne touche pas à la console
        if not self._is_focus_active(fp):
            self._log(f"[UI] Focus {fp} Couleur {name} mémorisée (en attente d'activation Manual F{fp})")
            return

        self._send_focus_color_to_ma2(fp)

    def _send_ma2_direct(self, cmd):
        with self.ma2_lock:
            self.ma2_cmd_queue.append(cmd)

    def _toggle_right_panel(self):
        if str(self.right_panel) in [str(p) for p in self.main_panes.panes()]:
            self.main_panes.forget(self.right_panel)
            self.btn_toggle_panel.config(text="[<] Panneau")
        else:
            self.main_panes.add(self.right_panel, stretch="never")
            self.btn_toggle_panel.config(text="[>] Panneau")

    def _toggle_front_panel(self):
        if str(self.front_border) in [str(p) for p in self.left_panes.panes()]:
            self.left_panes.forget(self.front_border)
            self.btn_toggle_front.config(bg="#555555", fg="#ccc")
        else:
            if str(self.log_frame) in [str(p) for p in self.left_panes.panes()]:
                self.left_panes.add(self.front_border, before=self.log_frame, stretch="always")
            else:
                self.left_panes.add(self.front_border, stretch="always")
            self.btn_toggle_front.config(bg=C["border"], fg=C["accent"])
        self._draw()

    @property
    def active_focus(self):
        if self.focus2_active and not self.focus1_active:
            return 2
        return 1

    def _adjust_target_z(self, delta):
        if self.focus1_active and self.focus2_active:
            val = round(max(-1.0, min(self.stage_h + 2.0, self.target_z + delta)), 2)
            self.target_z = val
            self.fp2_z = val
            if hasattr(self, 'lbl_z_top'):
                self.lbl_z_top.config(text=f"Z: {val:.2f}m", fg=C["accent"])
            if hasattr(self, 'lbl_z'):
                self.lbl_z.config(text=f"{self.target_z:.3f} m")
        elif self.focus2_active:
            self.fp2_z = round(max(-1.0, min(self.stage_h + 2.0, self.fp2_z + delta)), 2)
            if hasattr(self, 'lbl_z_top'):
                self.lbl_z_top.config(text=f"Z: {self.fp2_z:.2f}m", fg=C["tag2"])
        elif self.focus1_active:
            self.target_z = round(max(-1.0, min(self.stage_h + 2.0, self.target_z + delta)), 2)
            if hasattr(self, 'lbl_z_top'):
                self.lbl_z_top.config(text=f"Z: {self.target_z:.2f}m", fg=C["accent"])
            if hasattr(self, 'lbl_z'):
                self.lbl_z.config(text=f"{self.target_z:.3f} m")
        self._save_config()
        self._draw()

    def _toggle_log_panel(self):
        if str(self.log_frame) in [str(p) for p in self.left_panes.panes()]:
            self.left_panes.forget(self.log_frame)
            self.btn_toggle_log.config(text="[+] Logs ESP32")
        else:
            self.left_panes.add(self.log_frame, stretch="never")
            self.btn_toggle_log.config(text="[-] Logs ESP32")

    def _toggle_focus(self, fp):
        if fp == 1:
            self.focus1_active = not self.focus1_active
            if not self.focus1_active and not self.focus2_active:
                self.focus2_active = True
        else:
            self.focus2_active = not self.focus2_active
            if not self.focus1_active and not self.focus2_active:
                self.focus1_active = True

        self._update_focus_buttons()
        self._draw()

    def _update_focus_buttons(self):
        if self.focus1_active:
            self.btn_focus_1.config(bg=C["tag"], fg="#fff", activebackground="#ff6666", activeforeground="#fff")
        else:
            self.btn_focus_1.config(bg=C["border"], fg=C["dim"], activebackground="#3a3a4e", activeforeground="#aaa")

        if self.focus2_active:
            self.btn_focus_2.config(bg=C["tag2"], fg="#000", activebackground="#66ffff", activeforeground="#000")
        else:
            self.btn_focus_2.config(bg=C["border"], fg=C["dim"], activebackground="#3a3a4e", activeforeground="#aaa")

        if hasattr(self, 'lbl_z_top'):
            if self.focus1_active and self.focus2_active:
                self.lbl_z_top.config(text=f"Z: {self.target_z:.2f}m", fg=C["accent"])
            elif self.focus2_active:
                self.lbl_z_top.config(text=f"Z: {self.fp2_z:.2f}m", fg=C["tag2"])
            elif self.focus1_active:
                self.lbl_z_top.config(text=f"Z: {self.target_z:.2f}m", fg=C["accent"])

    def _toggle_active_focus(self):
        if self.focus1_active and not self.focus2_active:
            self._toggle_focus(2)
        else:
            self._toggle_focus(1)

    def _toggle_group(self, grp, fp=1):
        if fp == 1:
            self.group_toggles[grp] = not self.group_toggles[grp]
            if self.group_toggles[grp] and self.group_toggles_2.get(grp, False):
                self.group_toggles_2[grp] = False
                self._update_group_btn_color(grp, 2)
            self._update_group_btn_color(grp, 1)
        else:
            self.group_toggles_2[grp] = not self.group_toggles_2[grp]
            if self.group_toggles_2[grp] and self.group_toggles.get(grp, False):
                self.group_toggles[grp] = False
                self._update_group_btn_color(grp, 1)
            self._update_group_btn_color(grp, 2)
        self._save_config()
        self._draw()
        if self._is_focus_active(fp) and (self.group_toggles[grp] if fp == 1 else self.group_toggles_2[grp]):
            self._send_focus_color_to_ma2(fp)

    def _update_group_btn_color(self, grp, fp=1):
        if fp == 1:
            btn = self.btn_groups[grp]
            active = self.group_toggles[grp]
        else:
            btn = self.btn_groups_2[grp]
            active = self.group_toggles_2[grp]
        if active:
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
        
        ml, mt, mr, mb = self._margins()
        dw = cw - ml - mr
        dh_top = max(1, ch_top - mt - mb)
        
        scx = dw / max(self.stage_w, 0.5)
        scy_top = dh_top / max(self.stage_d, 0.5)
        
        front_visible = hasattr(self, 'front_border') and str(self.front_border) in [str(p) for p in self.left_panes.panes()]
        if front_visible:
            ch_front = self.canvas_front.winfo_height()
            dh_front = max(1, ch_front - mt - mb)
            scy_front = dh_front / max(self.stage_h, 0.5)
            scale = min(scx, scy_top, scy_front)
        else:
            scale = min(scx, scy_top)
            
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

        def get_fp2_pos():
            return (self.fp2_x, self.fp2_y) if view == "top" else (self.fp2_x, self.fp2_z)

        fp1_has_groups = any(self.group_toggles.values())
        show_fp1 = fp1_has_groups or self.focus1_active or self.connected
        fp2_has_groups = any(self.group_toggles_2.values())
        show_fp2 = fp2_has_groups or self.focus2_active

        # Beams (dessinés en 2 passes : focus inactif en arrière-plan atténué, puis focus actif au premier plan)
        for pass_active in (False, True):
            for fx in self.fixtures:
                if not fx.get("visible", True):
                    continue
                grp = fx.get("group", 1)
                in_fp1 = self.group_toggles.get(grp, False)
                in_fp2 = self.group_toggles_2.get(grp, False)
                if in_fp2 and show_fp2:
                    fp_num = 2
                    tx, ty_z = get_fp2_pos()
                elif in_fp1 and show_fp1:
                    fp_num = 1
                    tx, ty_z = get_tag_pos()
                else:
                    continue

                is_active_fp = (fp_num == 1 and self.focus1_active) or (fp_num == 2 and self.focus2_active)
                if is_active_fp != pass_active:
                    continue

                if is_active_fp:
                    beam_fill_col = "#0a1e28" if fp_num == 2 else C["beam_fill"]
                    beam_out_col = "#18667a" if fp_num == 2 else C["beam"]
                    beam_line_col = C["tag2"] if fp_num == 2 else C["fixture"]
                    dash_pat = (6, 4)
                else:
                    # Effet transparence (atténué sur le fond sombre)
                    beam_fill_col = "#0d1422" if fp_num == 2 else "#121118"
                    beam_out_col = "#143042" if fp_num == 2 else "#2e281c"
                    beam_line_col = "#185a6a" if fp_num == 2 else "#5a4d22"
                    dash_pat = (3, 6)

                txp, typ, _ = s2p(tx, ty_z)
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
                    fill=beam_fill_col, outline=beam_out_col, width=1
                )
                cv.create_line(fxp, fyp, txp, typ, fill=beam_line_col, width=1, dash=dash_pat)

        # Distance lines from anchors
        hide_a = getattr(self, 'var_hide_anchors', None) and self.var_hide_anchors.get()
        if self.connected and view == "top" and not hide_a:
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
            if not fx.get("visible", True):
                continue
            fxx, fxy_z = get_fx_pos(fx)
            fxp, fyp, _ = s2p(fxx, fxy_z)
            r = 14
            grp = fx.get("group", 1)
            is_active = self.group_toggles.get(grp, False) or self.group_toggles_2.get(grp, False)
            grp_col = self._get_group_color(grp) if is_active else C["dim"]
            bg_col = C["fixture_bg"] if is_active else C["panel"]
            text_col = C["fixture"] if is_active else C["dim"]
            
            cv.create_rectangle(fxp - r, fyp - r, fxp + r, fyp + r, fill=bg_col, outline=grp_col, width=2)
            cv.create_text(fxp, fyp, text=f"L{i+1}", fill=text_col, font=("Consolas", 8, "bold"))
            cv.create_text(fxp, fyp - 20, text=fx["name"], fill=text_col, font=("Segoe UI", 7))
            cv.create_text(fxp, fyp + 20, text=f"({fxx:.1f},{fxy_z:.1f})", fill=C["dim"], font=("Consolas", 7))

        # Anchors
        if not hide_a:
            for i, a in enumerate(self.anchors):
                ax, ay_z = (a[0], a[1]) if view == "top" else (a[0], a[2])
                apx, apy, _ = s2p(ax, ay_z)
                r1 = 18
                cv.create_oval(apx - r1, apy - r1, apx + r1, apy + r1, outline=C["anchor_bg"], width=2)
                r2 = 9
                cv.create_oval(apx - r2, apy - r2, apx + r2, apy + r2, fill=C["anchor"], outline="")
                cv.create_text(apx, apy - 24, text=f"A{i}", fill=C["anchor"], font=("Segoe UI", 10, "bold"))
                cv.create_text(apx, apy + 24, text=f"({ax:.1f},{ay_z:.1f})", fill=C["dim"], font=("Consolas", 7))

        # Focus Points (F1 & F2) : dessiner d'abord l'inactif (en transparence), puis l'actif au premier plan
        tx1, ty1_z = get_tag_pos()
        tx2, ty2_z = get_fp2_pos()
        are_superposed = (show_fp1 and show_fp2 and math.hypot(tx1 - tx2, ty1_z - ty2_z) < 0.20)

        def draw_focus_point(fp_num, tx, ty_z, is_active):
            txp, typ, _ = s2p(tx, ty_z)
            if fp_num == 1:
                lbl_x = txp - 13 if are_superposed else txp
                if is_active:
                    for gr in [28, 20, 14]:
                        intensity = int(30 * (28 - gr) / 14)
                        gcol = f"#{50 + intensity:02x}{10:02x}{10:02x}"
                        cv.create_oval(txp - gr, typ - gr, txp + gr, typ + gr, outline=gcol, width=1)
                    r = 9
                    cv.create_oval(txp - r, typ - r, txp + r, typ + r, fill=C["tag"], outline="#ff8888", width=2)
                    cv.create_line(txp - 14, typ, txp + 14, typ, fill=C["tag"], width=1)
                    cv.create_line(txp, typ - 14, txp, typ + 14, fill=C["tag"], width=1)
                    cv.create_text(lbl_x, typ - 18, text="F1", fill=C["tag"], font=("Segoe UI", 8, "bold"))
                    cv.create_text(txp, typ + 22, text=f"({tx:.2f}, {ty_z:.2f})", fill=C["text"], font=("Consolas", 9, "bold"))
                else:
                    cv.create_oval(txp - 16, typ - 16, txp + 16, typ + 16, outline="#26121e", width=1)
                    r = 7
                    cv.create_oval(txp - r, typ - r, txp + r, typ + r, fill="#5c202a", outline="#7a333d", width=1)
                    cv.create_line(txp - 11, typ, txp + 11, typ, fill="#5c202a", width=1)
                    cv.create_line(txp, typ - 11, txp, typ + 11, fill="#5c202a", width=1)
                    cv.create_text(lbl_x, typ - 16, text="F1", fill="#7a3842", font=("Segoe UI", 8))
                    cv.create_text(txp, typ + 19, text=f"({tx:.2f}, {ty_z:.2f})", fill="#605060", font=("Consolas", 8))
            else:
                lbl_x = txp + 13 if are_superposed else txp
                if is_active:
                    for gr in [28, 20, 14]:
                        intensity = int(30 * (28 - gr) / 14)
                        gcol = f"#{10:02x}{40 + intensity:02x}{50 + intensity:02x}"
                        cv.create_oval(txp - gr, typ - gr, txp + gr, typ + gr, outline=gcol, width=1)
                    r = 9
                    cv.create_oval(txp - r, typ - r, txp + r, typ + r, fill=C["tag2"], outline="#88ffff", width=2)
                    cv.create_line(txp - 14, typ, txp + 14, typ, fill=C["tag2"], width=1)
                    cv.create_line(txp, typ - 14, txp, typ + 14, fill=C["tag2"], width=1)
                    cv.create_text(lbl_x, typ - 18, text="F2", fill=C["tag2"], font=("Segoe UI", 8, "bold"))
                    cv.create_text(txp, typ + 22, text=f"({tx:.2f}, {ty_z:.2f})", fill=C["tag2"], font=("Consolas", 9, "bold"))
                else:
                    cv.create_oval(txp - 16, typ - 16, txp + 16, typ + 16, outline="#0e2434", width=1)
                    r = 7
                    cv.create_oval(txp - r, typ - r, txp + r, typ + r, fill="#105266", outline="#247388", width=1)
                    cv.create_line(txp - 11, typ, txp + 11, typ, fill="#105266", width=1)
                    cv.create_line(txp, typ - 11, txp, typ + 11, fill="#105266", width=1)
                    cv.create_text(lbl_x, typ - 16, text="F2", fill="#287388", font=("Segoe UI", 8))
                    cv.create_text(txp, typ + 19, text=f"({tx:.2f}, {ty_z:.2f})", fill="#406878", font=("Consolas", 8))

        for pass_active in (False, True):
            if show_fp2 and (self.focus2_active == pass_active):
                tx2, ty2_z = get_fp2_pos()
                draw_focus_point(2, tx2, ty2_z, pass_active)
            if show_fp1 and (self.focus1_active == pass_active):
                tx1, ty1_z = get_tag_pos()
                draw_focus_point(1, tx1, ty1_z, pass_active)

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
            if not fx.get("visible", True):
                continue
            fxx, fxy_z = (fx["x"], fx["y"]) if view == "top" else (fx["x"], fx["height"])
            px, py, _ = self._s2p(fxx, fxy_z, cv, view)
            d = math.hypot(event.x - px, event.y - py)
            if d < 20 and d < best_dist:
                best_dist = d
                best_type = "fixture"
                best_idx = i

        tx1, ty1_z = (self.display_x, self.display_y) if view == "top" else (self.display_x, self.target_z)
        tx2, ty2_z = (self.fp2_x, self.fp2_y) if view == "top" else (self.fp2_x, self.fp2_z)

        px1, py1, _ = self._s2p(tx1, ty1_z, cv, view)
        d_f1 = math.hypot(event.x - px1, event.y - py1)

        px2, py2, _ = self._s2p(tx2, ty2_z, cv, view)
        d_f2 = math.hypot(event.x - px2, event.y - py2)

        if self.focus1_active and self.focus2_active:
            min_d = min(d_f1, d_f2)
            if min_d < 25 and min_d < best_dist:
                best_dist = min_d
                best_type = "both_tags"
                best_idx = -1
            active_tag_type = "both_tags"
        elif self.focus2_active:
            if d_f2 < 25 and d_f2 < best_dist:
                best_dist = d_f2
                best_type = "tag2"
                best_idx = -1
            active_tag_type = "tag2"
        elif self.focus1_active:
            if d_f1 < 25 and d_f1 < best_dist:
                best_dist = d_f1
                best_type = "tag"
                best_idx = -1
            active_tag_type = "tag"
        else:
            active_tag_type = None

        if best_type:
            self._drag_type = best_type
            self._drag_idx = best_idx
            self._dragging = True
            self._drag_view = view
            cv.config(cursor="fleur")
        elif active_tag_type:
            self._drag_type = active_tag_type
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
        elif self._drag_type == "both_tags":
            uwb_live = (time.time() - self.last_uwb_pkt < 3.0) and not self.test_mode.get()
            if not uwb_live:
                self.tag_x = sx
                self.display_x = sx
            self.fp2_x = sx
            if self.test_mode.get():
                self.connected = True
                self.last_pkt = time.time()
                self.tag_q = 1.0

            if view == "top":
                if not uwb_live:
                    self.tag_y = sy
                    self.display_y = sy
                self.fp2_y = sy
            elif view == "front":
                self.target_z = sy
                self.fp2_z = sy
                if hasattr(self, 'lbl_z_top'):
                    self.lbl_z_top.config(text=f"Z: {self.target_z:.2f}m", fg=C["accent"])
                if hasattr(self, 'lbl_z'):
                    self.lbl_z.config(text=f"{self.target_z:.3f} m")
        elif self._drag_type == "tag":
            uwb_live = (time.time() - self.last_uwb_pkt < 3.0) and not self.test_mode.get()
            if not uwb_live:
                self.tag_x = sx
                self.display_x = sx
            if self.test_mode.get():
                self.connected = True
                self.last_pkt = time.time()
                self.tag_q = 1.0

            if view == "top" and not uwb_live:
                self.tag_y = sy
                self.display_y = sy
            elif view == "front":
                self.target_z = sy
                if hasattr(self, 'lbl_z_top') and self.focus1_active:
                    self.lbl_z_top.config(text=f"Z: {self.target_z:.2f}m", fg=C["accent"])
                if hasattr(self, 'lbl_z'):
                    self.lbl_z.config(text=f"{self.target_z:.3f} m")
        elif self._drag_type == "tag2":
            self.fp2_x = sx
            if view == "top":
                self.fp2_y = sy
            elif view == "front":
                self.fp2_z = sy
                if hasattr(self, 'lbl_z_top') and self.focus2_active:
                    self.lbl_z_top.config(text=f"Z: {self.fp2_z:.2f}m", fg=C["tag2"])

        self._draw()

    def _on_release(self, event):
        if self._dragging:
            self._dragging = False
            self.canvas_top.config(cursor="crosshair")
            self.canvas_front.config(cursor="crosshair")
            if self._drag_type in ["anchor", "fixture", "tag", "tag2", "both_tags"]:
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
                self.fp2_x = self.fp2_x * new_w / old_w
                self.fp2_y = self.fp2_y * new_d / old_d
                self.fp2_z = self.fp2_z * new_h / old_h
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

    def _format_fixture_manual_cmd(self, gma_id, raw_cmd, color_target=None):
        if not raw_cmd or not raw_cmd.strip():
            return ""
        sub_str = str(color_target) if color_target else str(gma_id)
        lines = [l.strip() for l in raw_cmd.replace("\r", "").split("\n") if l.strip()]
        raw_joined = " ; ".join(lines).replace("{id}", str(gma_id)).replace("{sub}", sub_str)
        parts = [p.strip() for p in raw_joined.split(";") if p.strip()]
        formatted_parts = []
        for p in parts:
            low = p.lower()
            if (low.startswith("attribute ") or low.startswith("at ") or
                low.startswith("stomp ") or low.startswith("presettype ")):
                formatted_parts.append(f"Fixture {gma_id} {p}")
            elif re.match(r'^(\d+(\.\d+)?(\s+thru\s+\d+(\.\d+)?)?)\s+(at|attribute|presettype|stomp)', low):
                # Si l'utilisateur a écrit "{id} At 100" ou "{sub} At 100" sans le mot "Fixture" devant
                formatted_parts.append(f"Fixture {p}")
            else:
                formatted_parts.append(p)
        return " ; ".join(formatted_parts)

    def _toggle_manual(self, fp=1):
        if fp == 1:
            current = self.test_mode.get()
            self.test_mode.set(not current)
            if not current:
                self.btn_manual.config(fg="#fff")
                self._log("[UI] Mode Manual F1 activé")
                self.connected = True
                self.last_pkt = time.time()
                self.tag_q = 1.0
                self._send_focus_color_to_ma2(1)
            else:
                self.btn_manual.config(bg="#555555", fg="#ccc", text="✋ Manual F1")
                self._log("[UI] Mode Manual F1 désactivé")
                if time.time() - self.last_uwb_pkt > 3.0:
                    self.connected = False
                with self.ma2_lock:
                    # Retirer immédiatement uniquement les lyres de F1
                    if not self.connected:
                        self.ma2_targets = {
                            gid: val for gid, val in self.ma2_targets.items()
                            if self.group_toggles_2.get(val[2] if len(val) >= 3 else 1, False)
                        }
                    if not self.test_mode_2.get() and not self.connected:
                        self.ma2_targets.clear()
                        self.ma2_clear_pending = True
        else:
            current = self.test_mode_2.get()
            self.test_mode_2.set(not current)
            if not current:
                self.btn_manual_2.config(fg="#fff")
                self._log("[UI] Mode Manual F2 activé")
                self._send_focus_color_to_ma2(2)
            else:
                self.btn_manual_2.config(bg="#555555", fg="#ccc", text="✋ Manual F2")
                self._log("[UI] Mode Manual F2 désactivé")
                with self.ma2_lock:
                    # Retirer immédiatement uniquement les lyres de F2
                    self.ma2_targets = {
                        gid: val for gid, val in self.ma2_targets.items()
                        if not self.group_toggles_2.get(val[2] if len(val) >= 3 else 1, False)
                    }
                    if not self.test_mode.get() and not self.connected:
                        self.ma2_targets.clear()
                        self.ma2_clear_pending = True
            
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
                stomped_gids = set()
                manual_sent_gids = set()
                known_col_targets = {}
                last_stomp_t = 0.0
                while self.ma2_connected:
                    time.sleep(0.066)
                    
                    # 1. Toujours vider le buffer de réception pour éviter que la MA2 ne freeze
                    # même si on n'a rien à envoyer (si MA2 envoie des logs ou un broadcast)
                    try:
                        s.setblocking(False)
                        while True:
                            data = s.recv(4096)
                            if not data:
                                raise ConnectionResetError("Connexion fermée par le serveur")
                    except BlockingIOError:
                        pass  # Plus rien à lire, c'est normal
                    except Exception as e:
                        self._log(f"[MA2] ✗ Erreur lecture: {e}")
                        break
                    finally:
                        s.setblocking(True)
                    
                    with self.ma2_lock:
                        clear_req = self.ma2_clear_pending
                        self.ma2_clear_pending = False
                        resend_manual = self.ma2_resend_manual_cmd
                        self.ma2_resend_manual_cmd = False
                        targets = list(self.ma2_targets.items())
                        direct_cmds = list(self.ma2_cmd_queue)
                        self.ma2_cmd_queue.clear()

                    # Commandes directes (couleurs, etc.)
                    if direct_cmds:
                        for d_cmd in direct_cmds:
                            try:
                                s.sendall(d_cmd.encode("utf-8"))
                            except Exception as e:
                                self._log(f"[MA2] ✗ Erreur envoi commande directe: {e}")
                                break

                    if resend_manual:
                        manual_sent_gids.clear()

                    if clear_req:
                        try:
                            s.sendall(b"ClearAll\r\nFreeze Off\r\n")
                            last_cmd = ""
                            stomped_gids.clear()
                            manual_sent_gids.clear()
                            known_col_targets.clear()
                            self._log("[MA2] ✓ ClearAll + Freeze Off envoyé (reprise effets/valeurs console)")
                        except Exception as e:
                            self._log(f"[MA2] ✗ Erreur envoi ClearAll: {e}")
                            break
                        continue

                    current_gids = {gid for gid, _ in targets}
                    removed_gids = stomped_gids - current_gids
                    if removed_gids:
                        try:
                            rem_lines = []
                            for g in sorted(removed_gids):
                                rem_lines.append(f'Off Fixture {g}')
                                col_t = known_col_targets.get(g)
                                if col_t and col_t != str(g):
                                    rem_lines.append(f'Off Fixture {col_t}')
                            rel_cmd = "\r\n".join(rem_lines) + "\r\n"
                            s.sendall(rel_cmd.encode("utf-8"))
                            stomped_gids -= removed_gids
                            manual_sent_gids -= removed_gids
                            for g in removed_gids:
                                known_col_targets.pop(g, None)
                            last_cmd = ""
                            self._log(f"[MA2] ✓ Relâchement Fixture {', '.join(str(g) for g in sorted(removed_gids))} (retour console pour ces lyres)")
                        except Exception as e:
                            self._log(f"[MA2] ✗ Erreur relâchement lyres: {e}")
                            break
                        
                    if not targets:
                        continue

                    # Stomp des effets Pan/Tilt et Couleur en cours sur les lyres contrôlées + Freeze On
                    now_t = time.time()
                    new_stomp = current_gids - stomped_gids
                    if new_stomp or (now_t - last_stomp_t > 1.5):
                        try:
                            stomp_groups = {}
                            stomp_col_targets = []
                            for gid, val in targets:
                                grp = val[2] if len(val) >= 3 else 1
                                stomp_groups.setdefault(grp, []).append(gid)
                                col_t = val[4] if len(val) >= 5 else None
                                if col_t:
                                    known_col_targets[gid] = col_t
                                    if col_t not in stomp_col_targets:
                                        stomp_col_targets.append(col_t)
                                else:
                                    known_col_targets[gid] = str(gid)

                            stomp_lines = ["Freeze On"]
                            for grp, gids in sorted(stomp_groups.items()):
                                g_str = " + ".join(str(g) for g in gids)
                                stomp_lines.append(
                                    f'Fixture {g_str} Stomp PresetType "Position" ; '
                                    f'Fixture {g_str} Stomp Attribute "Pan" ; '
                                    f'Fixture {g_str} Stomp Attribute "Tilt"'
                                )
                            # Couper tout effet de couleur actif sur les lyres / sous-fixtures
                            for ct in stomp_col_targets:
                                stomp_lines.append(f'Fixture {ct} Stomp PresetType "Color"')

                            s.sendall(("\r\n".join(stomp_lines) + "\r\n").encode("utf-8"))
                            stomped_gids.update(current_gids)
                            last_stomp_t = now_t

                            # Si de nouvelles lyres viennent d'être prises en charge, appliquer la couleur de leur focus
                            if new_stomp:
                                if self._is_focus_active(1):
                                    self._send_focus_color_to_ma2(1)
                                if self._is_focus_active(2):
                                    self._send_focus_color_to_ma2(2)
                        except Exception as e:
                            self._log(f"[MA2] ✗ Erreur envoi Stomp: {e}")
                            break

                    # Commandes supplémentaires par lyre à l'activation du mode Manual (F1 ou F2)
                    if self.test_mode.get() or self.test_mode_2.get():
                        new_manual = current_gids - manual_sent_gids
                        if new_manual:
                            custom_lines = []
                            for gid, val in targets:
                                if gid in new_manual and len(val) >= 4:
                                    raw_mcmd = val[3]
                                    col_tgt = val[4] if len(val) >= 5 else None
                                    f_cmd = self._format_fixture_manual_cmd(gid, raw_mcmd, col_tgt)
                                    if f_cmd:
                                        custom_lines.append(f_cmd)
                            if custom_lines:
                                try:
                                    s.sendall(("\r\n".join(custom_lines) + "\r\n").encode("utf-8"))
                                    self._log(f"[MA2] ✓ Cmd Manual envoyée ({len(custom_lines)} lyre(s))")
                                except Exception as e:
                                    self._log(f"[MA2] ✗ Erreur envoi Cmd Manual: {e}")
                                    break
                            manual_sent_gids.update(new_manual)
                        
                    # Build MA2 command (une ligne par groupe pour ne pas dépasser la limite Telnet MA2)
                    # Correct syntax to avoid "Error: Fixture X": Fixture X Attribute "Pan" At Y ; Fixture X Attribute "Tilt" At Z
                    groups_cmd = {}
                    for gid, val in targets:
                        pan = val[0]
                        tilt = val[1]
                        grp = val[2] if len(val) >= 3 else 1
                        groups_cmd.setdefault(grp, []).append(
                            f'Fixture {gid} Attribute "Pan" At {pan:.1f} ; Fixture {gid} Attribute "Tilt" At {tilt:.1f}'
                        )
                        
                    lines = [" ; ".join(parts) for grp, parts in sorted(groups_cmd.items())]
                    cmd = "\r\n".join(lines) + "\r\n"
                    
                    if cmd == last_cmd:
                        continue
                    last_cmd = cmd
                    
                    try:
                        s.sendall(cmd.encode("utf-8"))
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

    def _start_remote_listener(self):
        t = threading.Thread(target=self._listen_remote_commands, daemon=True)
        t.start()

    def _listen_remote_commands(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        port = 5005
        try:
            sock.bind(("0.0.0.0", port))
        except OSError as e:
            self._log(f"[NET] ⚠ Erreur accès port {port}: {e}")
            port = 9005
            try:
                sock.bind(("0.0.0.0", port))
            except Exception as e2:
                self._log(f"[NET] ✗ Impossible d'écouter la télécommande: {e2}")
                return
                
        self._log(f"[NET] Écoute UDP télécommande sur port {port}")
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                msg = data.decode("utf-8").strip()
                if msg == "SHOW_WINDOW":
                    self.root.after(0, self._toggle_window_state)
                elif msg == "HIDE_WINDOW":
                    self.root.after(0, self._hide_window)
            except Exception:
                pass

    def _toggle_window_state(self):
        try:
            # Si la fenêtre est normale (pas réduite) ET qu'elle a le focus actif
            if self.root.state() == 'normal' and self.root.focus_displayof():
                self._hide_window()
            else:
                self._bring_to_front()
        except Exception:
            pass

    def _bring_to_front(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.attributes("-topmost", False)
            self.root.focus_force()
            self._log("[UI] Fenêtre ramenée au premier plan via UDP")
        except Exception:
            pass

    def _hide_window(self):
        try:
            self.root.iconify()
            self._log("[UI] Fenêtre réduite via UDP")
        except Exception:
            pass

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
                self.last_uwb_pkt = now
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
        # Direct display: tag_x/y is set by the UDP thread (trilaterated) or manual edit
        self.display_x = self.tag_x
        self.display_y = self.tag_y

        # Draw
        self._draw()

        # Flush log
        self._flush_log()

        # Panel updates
        if hasattr(self, 'lbl_z_top'):
            if self.focus2_active and not self.focus1_active:
                cur_z = self.fp2_z
                col_z = C["tag2"]
            else:
                cur_z = self.target_z
                col_z = C["accent"]
            self.lbl_z_top.config(text=f"Z: {cur_z:.2f}m", fg=col_z)

        self.lbl_x.config(text=f"{self.display_x:.3f} m")
        self.lbl_y.config(text=f"{self.display_y:.3f} m")
        self.lbl_z.config(text=f"{self.target_z:.3f} m")

        if self.connected:
            for i, l in enumerate(self.dlbls):
                if i < len(self.distances):
                    l.config(text=f"{self.distances[i]:.3f} m")
            self._draw_qbar(self.tag_q)
            self.lbl_q.config(text=f"{self.tag_q * 100:.0f}%")
            self.lbl_status.config(text="✅ Connecté", fg=C["ok"])
        else:
            self.lbl_status.config(text="⏳ En attente données UWB...", fg=C["dim"])

        # Pan/Tilt (Focus Point 1 et Focus Point 2) : toujours calculé pour l'aperçu UI,
        # mais envoyé à GrandMA2 uniquement pour les focus points actifs (Manual F1 / UWB live ou Manual F2)
        fp1_live = self.test_mode.get() or self.connected
        fp2_live = self.test_mode_2.get()

        # Dès qu'un focus passe à l'état actif (connexion UWB ou clic Manual), appliquer sa couleur
        if fp1_live and not getattr(self, '_prev_fp1_live', False):
            self._send_focus_color_to_ma2(1)
        self._prev_fp1_live = fp1_live

        if fp2_live and not getattr(self, '_prev_fp2_live', False):
            self._send_focus_color_to_ma2(2)
        self._prev_fp2_live = fp2_live
        new_targets = {}
        for j, fx in enumerate(self.fixtures):
            try:
                if hasattr(self, 'fx_grp_entries') and j < len(self.fx_grp_entries):
                    fx["group"] = max(1, min(5, int(self.fx_grp_entries[j].get())))
            except:
                pass

            grp = fx.get("group", 1)
            in_fp1 = self.group_toggles.get(grp, False)
            in_fp2 = self.group_toggles_2.get(grp, False)

            if in_fp2:
                tx, ty, th = self.fp2_x, self.fp2_y, self.fp2_z
                active_for_ma2 = fp2_live
                is_manual_fp = self.test_mode_2.get()
            elif in_fp1:
                tx, ty, th = self.display_x, self.display_y, self.target_z
                active_for_ma2 = fp1_live
                is_manual_fp = self.test_mode.get()
            else:
                tx, ty, th = self.display_x, self.display_y, self.target_z
                active_for_ma2 = False
                is_manual_fp = False

            dx = tx - fx["x"]
            dy = ty - fx["y"]
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
                if not fx.get("visible", True):
                    self.fx_labels[j].config(text="(masquée)", fg=C["dim"])
                else:
                    self.fx_labels[j].config(
                        text=f"P={ma_pan:.1f}° T={ma_tilt:.1f}°", fg=status_col)
                    
            # Store for MA2 Telnet thread (only when this fixture is visible and its focus point is active)
            if active_for_ma2 and fx.get("visible", True):
                try:
                    gma_id = int(self.fx_ma2_entries[j].get())
                except:
                    gma_id = fx.get("gma_id", j + 1)
                col_tgt = self._get_fixture_color_target(fx, gma_id)
                new_targets[gma_id] = (ma_pan, ma_tilt, grp, fx.get("manual_cmd", "") if is_manual_fp else "", col_tgt)
            
        with self.ma2_lock:
            self.ma2_targets = new_targets

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

        # Manual buttons blink (sans changer le texte pour garder une largeur fixe)
        blink = int(time.time() * 2) % 2 == 0
        if self.test_mode.get():
            self.btn_manual.config(bg="#ff4444" if blink else "#aa2222")
        if self.test_mode_2.get():
            self.btn_manual_2.config(bg="#00ccdd" if blink else "#007788", fg="#fff")

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
