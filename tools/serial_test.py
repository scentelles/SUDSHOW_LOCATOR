#!/usr/bin/env python3
"""Test de communication série avec le module BU-01."""
import serial
import time
import sys

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"
BAUD = 115200

print(f"=== Test série BU-01 sur {PORT} @ {BAUD} baud ===")
print()

try:
    ser = serial.Serial(PORT, BAUD, timeout=2)
    print(f"✓ Port {PORT} ouvert")
    time.sleep(0.5)
    
    # 1. Lire ce qui est déjà dans le buffer (données spontanées)
    print("\n--- Lecture passive (2s) ---")
    start = time.time()
    while time.time() - start < 2:
        if ser.in_waiting:
            data = ser.read(ser.in_waiting)
            try:
                text = data.decode('utf-8', errors='replace')
                print(f"  Reçu: {repr(text)}")
            except:
                print(f"  Reçu (hex): {data.hex()}")
        time.sleep(0.1)
    
    # 2. Envoyer AT et attendre réponse
    print("\n--- Envoi: AT ---")
    ser.write(b"AT\r\n")
    time.sleep(0.5)
    if ser.in_waiting:
        resp = ser.read(ser.in_waiting).decode('utf-8', errors='replace')
        print(f"  Réponse: {repr(resp)}")
    else:
        print("  Pas de réponse")
    
    # 3. Tester AT+version?
    print("\n--- Envoi: AT+version? ---")
    ser.write(b"AT+version?\r\n")
    time.sleep(0.5)
    if ser.in_waiting:
        resp = ser.read(ser.in_waiting).decode('utf-8', errors='replace')
        print(f"  Réponse: {repr(resp)}")
    else:
        print("  Pas de réponse")
    
    # 4. Tester le rôle actuel
    print("\n--- Envoi: AT+anchor_tag? ---")
    ser.write(b"AT+anchor_tag?\r\n")
    time.sleep(0.5)
    if ser.in_waiting:
        resp = ser.read(ser.in_waiting).decode('utf-8', errors='replace')
        print(f"  Réponse: {repr(resp)}")
    else:
        print("  Pas de réponse")

    # 5. Écoute prolongée (5s) pour voir si le module envoie des données
    print("\n--- Écoute prolongée (5s) ---")
    start = time.time()
    received_any = False
    while time.time() - start < 5:
        if ser.in_waiting:
            data = ser.read(ser.in_waiting)
            text = data.decode('utf-8', errors='replace')
            print(f"  [{time.time()-start:.1f}s] {repr(text)}")
            received_any = True
        time.sleep(0.1)
    
    if not received_any:
        print("  Aucune donnée reçue")
        print("\n⚠ Le module ne répond pas. Vérifications :")
        print("  1. TX du dongle → U1RX du BU-01 (et inversement)")
        print("  2. GND connecté")  
        print("  3. Le module est bien alimenté (LED allumée ?)")
        print("  4. Essayez d'autres bauds: 9600, 38400, 57600")
    
    ser.close()
    print(f"\n✓ Port {PORT} fermé")

except serial.SerialException as e:
    print(f"✗ Erreur: {e}")
except KeyboardInterrupt:
    print("\nInterrompu")
