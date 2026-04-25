#!/usr/bin/env python3
"""
SudShow Locator — Test de Ranging
Connecte le Tag via USB-TTL et affiche les distances mesurées vers les Anchors.
Les Anchors doivent être alimentés et à portée.
"""
import serial
import time
import sys
import re

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

print()
print("╔══════════════════════════════════════════════════════╗")
print("║   SudShow Locator — Test de Ranging                  ║")
print("╚══════════════════════════════════════════════════════╝")
print()
print(f"Port: {PORT} @ {BAUD} baud")
print()
print("Prérequis:")
print("  🔵 Les 3 Anchors sont alimentés et à portée")
print("  🔴 Le Tag est branché sur le dongle USB-TTL")
print()

try:
    ser = serial.Serial(PORT, BAUD, timeout=2)
    time.sleep(1)

    # Vérifier la connexion
    resp = send_cmd(ser, "AT")
    if "OK" not in resp:
        print("✗ Le module ne répond pas.")
        ser.close()
        sys.exit(1)
    
    print("✓ Module connecté")

    # Vérifier que c'est bien un Tag
    resp = send_cmd(ser, "AT+anchor_tag?")
    print(f"  Config actuelle: {resp.replace(chr(10), ' | ')}")

    # S'assurer qu'il est en mode Tag
    print("\nConfiguration en Tag...")
    resp = send_cmd(ser, "AT+anchor_tag=0")
    print(f"  AT+anchor_tag=0 → {resp}")

    # Démarrer le ranging
    print("\nDémarrage du ranging...")
    resp = send_cmd(ser, "AT+switchdis=1", wait=1)
    print(f"  AT+switchdis=1 → {resp}")

    # Écouter les données de distance
    print()
    print("=" * 55)
    print("  ÉCOUTE DES DISTANCES (Ctrl+C pour arrêter)")
    print("=" * 55)
    print()

    # Patterns de distance possibles
    patterns = [
        re.compile(r'an(\d+):(\d+\.?\d*)'),           # an0:1.234
        re.compile(r'AN(\d+):(\d+\.?\d*)'),           # AN0:1.234
        re.compile(r'DIST.*?(\d+)=(\d+\.?\d*)'),      # DIST:0=1.234
        re.compile(r'dis(\d+):(\d+\.?\d*)'),          # dis0:1.234
        re.compile(r'range(\d+):(\d+\.?\d*)'),        # range0:1.234
        re.compile(r'(\d+)\s*:\s*(\d+\.?\d*)\s*m'),   # 0: 1.234 m
    ]

    distances = {}
    start_time = time.time()
    line_buffer = ""
    data_received = False
    raw_lines = []

    while True:
        if ser.in_waiting:
            data = ser.read(ser.in_waiting).decode('utf-8', errors='replace')
            line_buffer += data

            while '\n' in line_buffer:
                line, line_buffer = line_buffer.split('\n', 1)
                line = line.strip()
                if not line:
                    continue

                raw_lines.append(line)
                
                # Afficher la ligne brute
                elapsed = time.time() - start_time
                print(f"  [{elapsed:6.1f}s] RAW: {line}")

                # Chercher des patterns de distance
                found = False
                for pattern in patterns:
                    matches = pattern.findall(line)
                    for match in matches:
                        anchor_id = int(match[0])
                        distance = float(match[1])
                        distances[anchor_id] = distance
                        data_received = True
                        found = True
                
                if found:
                    # Afficher le résumé des distances
                    dist_str = "  → "
                    for aid in sorted(distances.keys()):
                        dist_str += f"A{aid}={distances[aid]:.3f}m  "
                    print(dist_str)
                    print()

        # Afficher un statut périodique
        elapsed = time.time() - start_time
        if int(elapsed) % 10 == 0 and int(elapsed) > 0 and elapsed - int(elapsed) < 0.15:
            if not data_received:
                print(f"  [{elapsed:.0f}s] ⏳ En attente de données...")
                print(f"       Lignes brutes reçues: {len(raw_lines)}")
                if raw_lines:
                    print(f"       Dernière: {raw_lines[-1]}")
                print(f"       Vérifiez que les Anchors sont alimentés et à portée")

        # Timeout après 60s sans données
        if elapsed > 60 and not data_received:
            print("\n⚠ Aucune donnée de distance reçue après 60s.")
            print("  Vérifications :")
            print("  1. Les 3 Anchors sont bien alimentés ?")
            print("  2. Les Anchors sont configurés (AT+anchor_tag=1) ?")
            print("  3. Les modules sont à portée (< 30m) ?")
            if raw_lines:
                print(f"\n  Données brutes reçues ({len(raw_lines)} lignes) :")
                for rl in raw_lines[-10:]:
                    print(f"    {rl}")
            break

        time.sleep(0.05)

except serial.SerialException as e:
    print(f"✗ Erreur série: {e}")
except KeyboardInterrupt:
    print(f"\n\nArrêt du test.")
    if distances:
        print(f"\nDernières distances mesurées :")
        for aid in sorted(distances.keys()):
            print(f"  Anchor {aid} : {distances[aid]:.3f} m")
    else:
        print("Aucune distance mesurée.")
    
    # Arrêter le ranging
    try:
        resp = send_cmd(ser, "AT+switchdis=0")
        print(f"\nRanging arrêté: {resp}")
    except:
        pass
finally:
    try:
        ser.close()
        print("Port fermé.")
    except:
        pass
