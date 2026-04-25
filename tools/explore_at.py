#!/usr/bin/env python3
"""Exploration complète des commandes AT du module BU-01."""
import serial
import time
import sys

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"
BAUD = 115200

def send_cmd(ser, cmd, wait=0.5):
    """Envoie une commande et retourne la réponse."""
    ser.reset_input_buffer()
    ser.write(f"{cmd}\r\n".encode())
    time.sleep(wait)
    resp = ""
    while ser.in_waiting:
        resp += ser.read(ser.in_waiting).decode('utf-8', errors='replace')
        time.sleep(0.05)
    return resp.strip()

print(f"=== Exploration AT du BU-01 sur {PORT} ===\n")

try:
    ser = serial.Serial(PORT, BAUD, timeout=2)
    time.sleep(0.5)

    # Liste de commandes AT connues pour les modules BU-01 / Ai-Thinker UWB
    commands = [
        ("AT", "Test de communication"),
        ("AT+version?", "Version du firmware"),
        ("AT+anchor_tag?", "Rôle actuel (anchor/tag)"),
        ("AT+anchor_tag=0", "→ Configurer en Tag"),
        ("AT+anchor_tag=1", "→ Configurer en Anchor"),
        ("AT+id?", "ID du module"),
        ("AT+id=0", "→ Set ID à 0"),
        ("AT+cap?", "Capacités / paramètres"),
        ("AT+switchdis=1", "Démarrer le ranging"),
        ("AT+switchdis=0", "Arrêter le ranging"),
        ("AT+switchdis?", "État du ranging"),
        ("AT+interval?", "Intervalle de mesure"),
        ("AT+interval=1", "→ Intervalle 1"),
        ("AT+RST", "Reset du module"),
        ("AT+rate?", "Taux de transmission"),
        ("AT+channel?", "Canal UWB"),
        ("AT+power?", "Puissance d'émission"),
        ("AT+help", "Aide / liste des commandes"),
        ("AT+?", "Aide alternative"),
        ("AT+tem_hum", "Température & humidité"),
        ("AT+xyz", "Accéléromètre 3 axes"),
        ("AT+range?", "Portée / mode ranging"),
        ("AT+mode?", "Mode de fonctionnement"),
        ("AT+addr?", "Adresse du module"),
        ("AT+panid?", "PAN ID"),
        ("AT+dst_addr?", "Adresse destination"),
        ("AT+baud?", "Vitesse série"),
    ]

    # D'abord, on ne fait que lire — pas de config
    read_only_cmds = [c for c in commands if '=' not in c[0] and c[0] != "AT+RST"]
    
    print("=" * 60)
    print("  COMMANDES DE LECTURE (exploration)")
    print("=" * 60)
    
    supported = []
    unsupported = []
    
    for cmd, desc in read_only_cmds:
        resp = send_cmd(ser, cmd)
        # Vérifier si la commande est supportée
        if resp and "ERROR" not in resp.upper() and len(resp) > 0:
            print(f"\n✓ {cmd:25s} [{desc}]")
            for line in resp.split('\n'):
                line = line.strip()
                if line:
                    print(f"  → {line}")
            supported.append((cmd, desc, resp))
        else:
            unsupported.append((cmd, desc))
    
    print("\n" + "=" * 60)
    print("  RÉSUMÉ")
    print("=" * 60)
    print(f"\n✓ Commandes supportées: {len(supported)}")
    for cmd, desc, resp in supported:
        clean = resp.replace('\r\n', ' | ').replace('\r', '').strip()
        print(f"  {cmd:25s} → {clean[:60]}")
    
    print(f"\n✗ Commandes non supportées: {len(unsupported)}")
    for cmd, desc in unsupported:
        print(f"  {cmd:25s} [{desc}]")

    ser.close()
    print(f"\n✓ Port fermé")

except serial.SerialException as e:
    print(f"✗ Erreur: {e}")
except KeyboardInterrupt:
    print("\nInterrompu")
