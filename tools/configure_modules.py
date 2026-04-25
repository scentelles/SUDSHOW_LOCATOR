#!/usr/bin/env python3
"""
SudShow Locator — Configuration des modules BU-01 (v2)
Configure les 4 modules un par un : 3 Anchors + 1 Tag
Le rôle est confirmé par le message de boot après reset.
"""
import serial
import time
import sys

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"
BAUD = 115200

def send_cmd(ser, cmd, wait=0.5):
    ser.reset_input_buffer()
    ser.write(f"{cmd}\r\n".encode())
    time.sleep(wait)
    resp = ""
    while ser.in_waiting:
        resp += ser.read(ser.in_waiting).decode('utf-8', errors='replace')
        time.sleep(0.05)
    return resp.strip()

def check_connection(ser):
    resp = send_cmd(ser, "AT")
    return "OK" in resp

def configure_and_verify(ser, role, anchor_id=0):
    """
    Configure le module et vérifie via reset.
    role: 'anchor' ou 'tag'
    anchor_id: 0, 1, 2 (pour les anchors)
    Retourne (success, device_info)
    """
    # Configurer
    if role == 'anchor':
        resp = send_cmd(ser, f"AT+anchor_tag=1,{anchor_id}")
        print(f"    AT+anchor_tag=1,{anchor_id} → {resp}")
    else:
        resp = send_cmd(ser, "AT+anchor_tag=0")
        print(f"    AT+anchor_tag=0 → {resp}")

    # Reset pour vérifier
    print("    Reset du module...")
    ser.reset_input_buffer()
    ser.write(b"AT+RST\r\n")
    time.sleep(2.5)
    
    boot_msg = ""
    while ser.in_waiting:
        boot_msg += ser.read(ser.in_waiting).decode('utf-8', errors='replace')
        time.sleep(0.05)
    
    print(f"    Message de boot:")
    for line in boot_msg.split('\n'):
        line = line.strip()
        if line:
            print(f"      {line}")
    
    # Vérifier le rôle dans le message de boot
    boot_lower = boot_msg.lower()
    if role == 'anchor' and 'anchor' in boot_lower:
        return True, boot_msg
    elif role == 'tag' and 'tag' in boot_lower:
        return True, boot_msg
    elif 'device:' in boot_lower:
        # Le device est identifié mais pas le rôle attendu
        return False, boot_msg
    else:
        # Pas de message device — vérifier via AT
        resp = send_cmd(ser, "AT+anchor_tag?")
        print(f"    anchor_tag? → {resp.replace(chr(10), ' | ')}")
        return True, boot_msg  # On fait confiance au OK

# =============================================================================

print()
print("╔══════════════════════════════════════════════════════╗")
print("║   SudShow Locator — Configuration BU-01 (v2)        ║")
print("╚══════════════════════════════════════════════════════╝")
print()

modules = [
    {"name": "Anchor 0", "role": "anchor", "id": 0, "emoji": "🔵"},
    {"name": "Anchor 1", "role": "anchor", "id": 1, "emoji": "🔵"},
    {"name": "Anchor 2", "role": "anchor", "id": 2, "emoji": "🔵"},
    {"name": "Tag",      "role": "tag",    "id": 0, "emoji": "🔴"},
]

results = []

for i, mod in enumerate(modules):
    print(f"{'─'*55}")
    print(f"  {mod['emoji']} Module {i+1}/4 : {mod['name']}")
    print(f"{'─'*55}")
    
    if i > 0:
        print(f"\n  ⏳ Débranchez le module précédent.")
        print(f"     Branchez le module pour '{mod['name']}' sur le dongle USB-TTL.")
    
    input(f"\n  [Entrée] quand le module est branché sur {PORT} → ")
    
    try:
        ser = serial.Serial(PORT, BAUD, timeout=2)
        time.sleep(1)
        
        if not check_connection(ser):
            print("  ✗ Pas de réponse. Vérifiez le branchement.")
            input("  [Entrée] pour réessayer → ")
            time.sleep(1)
            if not check_connection(ser):
                print("  ✗ Toujours rien. On passe au suivant.")
                results.append((mod, False, "Pas de réponse"))
                ser.close()
                continue
        
        # Info module
        ver = send_cmd(ser, "AT+version?").split('\n')[0].strip()
        print(f"\n  ✓ Détecté : {ver}")
        
        # Configurer
        print(f"\n  Configuration en {mod['name']}...")
        success, info = configure_and_verify(ser, mod['role'], mod['id'])
        
        if success:
            print(f"\n  ✅ {mod['name']} configuré avec succès !")
            results.append((mod, True, info))
        else:
            print(f"\n  ⚠ Configuration incertaine. Vérifiez manuellement.")
            results.append((mod, False, info))
        
        # Optionnel : afficher capteurs
        temp = send_cmd(ser, "AT+tem_hum")
        for line in temp.split('\n'):
            line = line.strip()
            if line.startswith("T:"):
                print(f"  Temp: {float(line[2:]):.1f}°C")
        
        ser.close()
        
        # Marquer physiquement le module
        label = f"A{mod['id']}" if mod['role'] == 'anchor' else "TAG"
        print(f"\n  📝 MARQUEZ ce module : \"{label}\"")
        print(f"     Vous pouvez le débrancher.\n")
        
    except serial.SerialException as e:
        print(f"  ✗ Erreur: {e}")
        results.append((mod, False, str(e)))

# =============================================================================
# RÉSUMÉ
# =============================================================================
print(f"\n{'═'*55}")
print(f"  RÉSUMÉ")
print(f"{'═'*55}\n")

all_ok = True
for mod, success, info in results:
    status = "✅" if success else "❌"
    label = f"Anchor ID={mod['id']}" if mod['role'] == 'anchor' else "Tag"
    print(f"  {status} {mod['emoji']} {mod['name']:12s} → {label}")
    if not success:
        all_ok = False

if all_ok and len(results) == 4:
    print(f"\n  🎉 Tous les modules sont configurés !")
    print(f"\n  PROCHAINE ÉTAPE :")
    print(f"  1. Alimentez les 3 Anchors (marqués A0, A1, A2)")
    print(f"  2. Rebranchez le TAG sur le dongle USB-TTL")
    print(f"  3. Lancez :")
    print(f"     python tools/test_ranging.py {PORT}")
elif len(results) < 4:
    print(f"\n  ⚠ Seulement {len(results)}/4 modules configurés")
print()
