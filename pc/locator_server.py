#!/usr/bin/env python3
# =============================================================================
# SudShow Locator — PC Server
# =============================================================================
# Reçoit les positions (x, y) de l'ESP32 via UDP,
# calcule les angles Pan/Tilt pour chaque lyre,
# et envoie les commandes via Telnet à GrandMA2 onPC.
# =============================================================================

import socket
import json
import math
import time
import sys
import threading
import telnetlib
import os
from dataclasses import dataclass, field
from typing import List, Optional

# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")


@dataclass
class Fixture:
    """Représente une lyre (moving head) dans l'espace."""
    id: int
    name: str
    x: float
    y: float
    height: float
    gma_fixture_id: int
    pan_range_deg: float = 540.0
    tilt_range_deg: float = 270.0
    pan_offset_deg: float = 0.0
    tilt_offset_deg: float = 0.0
    pan_invert: bool = False
    tilt_invert: bool = False
    enabled: bool = True
    # État interne
    last_pan: float = 0.0
    last_tilt: float = 0.0


@dataclass
class Config:
    """Configuration globale du système."""
    stage_width: float = 10.0
    stage_depth: float = 5.0
    udp_listen_port: int = 9000
    gma2_host: str = "127.0.0.1"
    gma2_port: int = 30000
    gma2_user: str = "administrator"
    gma2_password: str = "admin"
    update_rate_hz: int = 20
    smoothing_factor: float = 0.3
    dead_zone_deg: float = 0.5
    target_height: float = 1.7  # Hauteur du performer (mètres)
    fixtures: List[Fixture] = field(default_factory=list)


def load_config(path: str) -> Config:
    """Charge la configuration depuis un fichier JSON."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cfg = Config()
    cfg.stage_width = data.get("stage", {}).get("width", 10.0)
    cfg.stage_depth = data.get("stage", {}).get("depth", 5.0)

    net = data.get("network", {})
    cfg.udp_listen_port = net.get("udp_listen_port", 9000)
    cfg.gma2_host = net.get("gma2_host", "127.0.0.1")
    cfg.gma2_port = net.get("gma2_port", 30000)
    cfg.gma2_user = net.get("gma2_user", "administrator")
    cfg.gma2_password = net.get("gma2_password", "admin")

    trk = data.get("tracking", {})
    cfg.update_rate_hz = trk.get("update_rate_hz", 20)
    cfg.smoothing_factor = trk.get("smoothing_factor", 0.3)
    cfg.dead_zone_deg = trk.get("dead_zone_deg", 0.5)
    cfg.target_height = trk.get("target_height", 1.7)

    for fx_data in data.get("fixtures", []):
        fx = Fixture(
            id=fx_data["id"],
            name=fx_data["name"],
            x=fx_data["x"],
            y=fx_data["y"],
            height=fx_data["height"],
            gma_fixture_id=fx_data["gma_fixture_id"],
            pan_range_deg=fx_data.get("pan_range_deg", 540),
            tilt_range_deg=fx_data.get("tilt_range_deg", 270),
            pan_offset_deg=fx_data.get("pan_offset_deg", 0),
            tilt_offset_deg=fx_data.get("tilt_offset_deg", 0),
            pan_invert=fx_data.get("pan_invert", False),
            tilt_invert=fx_data.get("tilt_invert", False),
            enabled=fx_data.get("enabled", True),
        )
        cfg.fixtures.append(fx)

    return cfg


# =============================================================================
# CALCUL PAN / TILT
# =============================================================================

def calculate_pan_tilt(fixture: Fixture, target_x: float, target_y: float,
                       target_height: float) -> tuple:
    """
    Calcule les angles Pan et Tilt en degrés pour pointer une lyre
    vers une cible au sol.

    Repère de la scène :
      x → largeur (gauche/droite)
      y → profondeur (avant/arrière)
      z → hauteur (haut/bas)

    La lyre est à (fixture.x, fixture.y, fixture.height).
    La cible est à (target_x, target_y, target_height).

    Pan  = rotation horizontale (0° = face, positif = sens horaire)
    Tilt = inclinaison verticale (0° = horizontal, 90° = droit en bas)
    """
    dx = target_x - fixture.x
    dy = target_y - fixture.y
    dz = fixture.height - target_height  # Positif car fixture plus haute

    # Distance horizontale
    dist_h = math.sqrt(dx * dx + dy * dy)

    # Pan : angle horizontal (en degrés)
    # atan2(dx, dy) donne l'angle par rapport à l'axe Y (profondeur)
    pan_rad = math.atan2(dx, dy)
    pan_deg = math.degrees(pan_rad) + fixture.pan_offset_deg

    if fixture.pan_invert:
        pan_deg = -pan_deg

    # Tilt : angle vertical (en degrés)
    # 0° = horizontal, 90° = droit en bas
    if dist_h < 0.01:
        tilt_deg = 90.0  # Directement en dessous
    else:
        tilt_rad = math.atan2(dz, dist_h)
        tilt_deg = math.degrees(tilt_rad) + fixture.tilt_offset_deg

    if fixture.tilt_invert:
        tilt_deg = -tilt_deg

    return pan_deg, tilt_deg


# =============================================================================
# CONNECTION GRANDMA2 TELNET
# =============================================================================

class GrandMA2Connection:
    """Gère la connexion Telnet vers GrandMA2 onPC."""

    def __init__(self, host: str, port: int, user: str, password: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.tn: Optional[telnetlib.Telnet] = None
        self.connected = False
        self._lock = threading.Lock()
        self._last_commands: dict = {}  # Cache pour éviter les envois inutiles

    def connect(self) -> bool:
        """Établit la connexion Telnet avec GrandMA2."""
        try:
            print(f"[GMA2] Connexion à {self.host}:{self.port}...")
            self.tn = telnetlib.Telnet(self.host, self.port, timeout=5)

            # Attendre le prompt de login
            time.sleep(0.5)
            response = self.tn.read_very_eager().decode("utf-8", errors="ignore")
            print(f"[GMA2] Réponse initiale: {response.strip()}")

            # Envoyer le login
            login_cmd = f'Login "{self.user}" "{self.password}"\r\n'
            self.tn.write(login_cmd.encode("utf-8"))
            time.sleep(0.5)

            response = self.tn.read_very_eager().decode("utf-8", errors="ignore")
            print(f"[GMA2] Réponse login: {response.strip()}")

            self.connected = True
            print(f"[GMA2] ✓ Connecté à GrandMA2 onPC")
            return True

        except Exception as e:
            print(f"[GMA2] ✗ Erreur connexion: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Ferme la connexion Telnet."""
        if self.tn:
            try:
                self.tn.write(b"Logout\r\n")
                self.tn.close()
            except Exception:
                pass
        self.connected = False
        print("[GMA2] Déconnecté")

    def send_command(self, cmd: str):
        """Envoie une commande à GrandMA2."""
        if not self.connected or not self.tn:
            return

        with self._lock:
            try:
                self.tn.write(f"{cmd}\r\n".encode("utf-8"))
            except Exception as e:
                print(f"[GMA2] ✗ Erreur envoi: {e}")
                self.connected = False

    def set_fixture_pan_tilt(self, fixture_id: int, pan_deg: float, tilt_deg: float,
                              dead_zone: float = 0.5):
        """
        Envoie les valeurs Pan/Tilt à GrandMA2 pour une fixture.

        Les valeurs sont en degrés naturels (GrandMA2 interprète selon le profil
        de la fixture).
        """
        # Arrondir pour éviter le bruit
        pan_deg = round(pan_deg, 1)
        tilt_deg = round(tilt_deg, 1)

        # Vérifier la dead zone (ne pas envoyer si changement trop petit)
        key = f"fx_{fixture_id}"
        if key in self._last_commands:
            last_pan, last_tilt = self._last_commands[key]
            if (abs(pan_deg - last_pan) < dead_zone and
                    abs(tilt_deg - last_tilt) < dead_zone):
                return  # Pas de changement significatif

        self._last_commands[key] = (pan_deg, tilt_deg)

        # Envoyer les commandes GrandMA2
        # On sélectionne la fixture et on lui attribue Pan et Tilt
        self.send_command(f'Fixture {fixture_id} Attribute "Pan" At {pan_deg}')
        self.send_command(f'Fixture {fixture_id} Attribute "Tilt" At {tilt_deg}')

    def reconnect(self) -> bool:
        """Tente de se reconnecter."""
        self.disconnect()
        time.sleep(1)
        return self.connect()


# =============================================================================
# SERVEUR PRINCIPAL
# =============================================================================

class LocatorServer:
    """Serveur principal : réception UDP + calcul + envoi GMA2."""

    def __init__(self, config: Config):
        self.config = config
        self.running = False

        # Lissage
        self.smoothed_x: Optional[float] = None
        self.smoothed_y: Optional[float] = None

        # Stats
        self.packet_count = 0
        self.last_stats_time = time.time()
        self.last_position = (0.0, 0.0)

    def run(self):
        """Lance le serveur."""
        self.running = True

        # --- Connexion GrandMA2 ---
        gma = GrandMA2Connection(
            self.config.gma2_host,
            self.config.gma2_port,
            self.config.gma2_user,
            self.config.gma2_password,
        )

        gma_connected = gma.connect()
        if not gma_connected:
            print("[MAIN] ⚠ GrandMA2 non disponible — mode affichage uniquement")

        # --- Socket UDP ---
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.config.udp_listen_port))
        sock.settimeout(1.0)

        print(f"[MAIN] ✓ Écoute UDP sur le port {self.config.udp_listen_port}")
        print(f"[MAIN]   Fixtures configurées: {len(self.config.fixtures)}")
        for fx in self.config.fixtures:
            status = "✓" if fx.enabled else "✗"
            print(f"[MAIN]   {status} {fx.name} (GMA #{fx.gma_fixture_id}) "
                  f"à ({fx.x}, {fx.y}, H={fx.height}m)")
        print("─" * 50)
        print("[MAIN] En attente de données de l'ESP32...")
        print()

        try:
            while self.running:
                try:
                    data, addr = sock.recvfrom(1024)
                except socket.timeout:
                    # Tenter de reconnecter GMA2 si nécessaire
                    if not gma.connected and gma_connected:
                        gma.reconnect()
                    continue

                # Parser le JSON
                try:
                    msg = json.loads(data.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                raw_x = msg.get("x", 0.0)
                raw_y = msg.get("y", 0.0)
                quality = msg.get("q", 0.0)
                distances = msg.get("d", [])
                seq = msg.get("n", 0)

                self.packet_count += 1

                # --- Lissage côté PC ---
                alpha = self.config.smoothing_factor
                if self.smoothed_x is None:
                    self.smoothed_x = raw_x
                    self.smoothed_y = raw_y
                else:
                    self.smoothed_x = alpha * raw_x + (1 - alpha) * self.smoothed_x
                    self.smoothed_y = alpha * raw_y + (1 - alpha) * self.smoothed_y

                tx = self.smoothed_x
                ty = self.smoothed_y
                self.last_position = (tx, ty)

                # --- Calcul Pan/Tilt pour chaque fixture ---
                for fx in self.config.fixtures:
                    if not fx.enabled:
                        continue

                    pan, tilt = calculate_pan_tilt(
                        fx, tx, ty, self.config.target_height
                    )

                    # Envoyer à GrandMA2
                    if gma.connected:
                        gma.set_fixture_pan_tilt(
                            fx.gma_fixture_id, pan, tilt,
                            self.config.dead_zone_deg
                        )

                    fx.last_pan = pan
                    fx.last_tilt = tilt

                # --- Stats périodiques ---
                now = time.time()
                if now - self.last_stats_time >= 3.0:
                    self.last_stats_time = now
                    rate = self.packet_count / 3.0
                    self.packet_count = 0

                    dist_str = ""
                    if distances:
                        dist_str = f"  Dist: [{', '.join(f'{d:.2f}m' for d in distances)}]"

                    print(f"[STATS] Pos: ({tx:.3f}, {ty:.3f})m  "
                          f"Q: {quality:.0%}  "
                          f"Rate: {rate:.1f} pkt/s  "
                          f"GMA2: {'✓' if gma.connected else '✗'}"
                          f"{dist_str}")

                    for fx in self.config.fixtures:
                        if fx.enabled:
                            print(f"  └─ {fx.name}: Pan={fx.last_pan:.1f}°  "
                                  f"Tilt={fx.last_tilt:.1f}°")

        except KeyboardInterrupt:
            print("\n[MAIN] Arrêt demandé...")
        finally:
            gma.disconnect()
            sock.close()
            print("[MAIN] Serveur arrêté.")


# =============================================================================
# MODE SIMULATION (pour tester sans hardware)
# =============================================================================

def run_simulation(config: Config):
    """
    Simule un performer qui se déplace sur la scène.
    Envoie des paquets UDP comme le ferait l'ESP32.
    """
    print("╔══════════════════════════════════════════╗")
    print("║   SudShow Locator — Mode Simulation      ║")
    print("╚══════════════════════════════════════════╝")
    print()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = ("127.0.0.1", config.udp_listen_port)

    print(f"[SIM] Envoi vers {target}")
    print(f"[SIM] Scène: {config.stage_width}m × {config.stage_depth}m")
    print(f"[SIM] Le performer fait des allers-retours sur la scène.")
    print()

    t = 0.0
    seq = 0
    dt = 1.0 / config.update_rate_hz

    try:
        while True:
            # Mouvement sinusoïdal sur X, léger mouvement sur Y
            x = config.stage_width / 2 + (config.stage_width / 3) * math.sin(t * 0.5)
            y = config.stage_depth / 2 + (config.stage_depth / 4) * math.sin(t * 0.3)

            # Simuler les distances (avec un peu de bruit)
            import random
            anchors = [(0, 0), (config.stage_width, 0),
                       (config.stage_width / 2, config.stage_depth)]
            distances = []
            for ax, ay in anchors:
                d = math.sqrt((x - ax) ** 2 + (y - ay) ** 2)
                d += random.gauss(0, 0.02)  # Bruit ±2cm
                distances.append(round(d, 3))

            packet = {
                "x": round(x, 3),
                "y": round(y, 3),
                "t": int(time.time() * 1000),
                "q": 0.95,
                "n": seq,
                "d": distances
            }

            sock.sendto(json.dumps(packet).encode("utf-8"), target)

            if seq % (config.update_rate_hz * 2) == 0:
                print(f"[SIM] Position: ({x:.2f}, {y:.2f})m  "
                      f"Dist: [{', '.join(f'{d:.2f}' for d in distances)}]")

            seq += 1
            t += dt
            time.sleep(dt)

    except KeyboardInterrupt:
        print("\n[SIM] Simulation arrêtée.")
    finally:
        sock.close()


# =============================================================================
# POINT D'ENTRÉE
# =============================================================================

def main():
    print()
    print("╔══════════════════════════════════════════╗")
    print("║   SudShow Locator — PC Server            ║")
    print("╚══════════════════════════════════════════╝")
    print()

    # Charger la config
    try:
        config = load_config(CONFIG_FILE)
        print(f"[MAIN] ✓ Configuration chargée: {CONFIG_FILE}")
    except FileNotFoundError:
        print(f"[MAIN] ✗ Fichier de configuration non trouvé: {CONFIG_FILE}")
        print(f"[MAIN]   Utilisation des valeurs par défaut.")
        config = Config()
    except json.JSONDecodeError as e:
        print(f"[MAIN] ✗ Erreur JSON dans la configuration: {e}")
        sys.exit(1)

    # Mode d'exécution
    if len(sys.argv) > 1 and sys.argv[1] == "--simulate":
        run_simulation(config)
    elif len(sys.argv) > 1 and sys.argv[1] == "--sim-both":
        # Lance le serveur ET le simulateur en parallèle
        server = LocatorServer(config)
        sim_thread = threading.Thread(target=run_simulation, args=(config,), daemon=True)
        sim_thread.start()
        server.run()
    else:
        server = LocatorServer(config)
        server.run()


if __name__ == "__main__":
    main()
