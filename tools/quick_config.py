#!/usr/bin/env python3
"""
Configure un module BU-01 en un rôle donné.
Usage:
  python quick_config.py COM7 anchor 2    # Configure en Anchor ID=2
  python quick_config.py COM7 tag          # Configure en Tag
"""
import serial, time, sys

if len(sys.argv) < 3:
    print("Usage: python quick_config.py <PORT> <anchor|tag> [anchor_id]")
    print("  Ex:  python quick_config.py COM7 anchor 2")
    print("  Ex:  python quick_config.py COM7 tag")
    sys.exit(1)

PORT = sys.argv[1]
ROLE = sys.argv[2].lower()
AID = int(sys.argv[3]) if len(sys.argv) > 3 else 0

ser = serial.Serial(PORT, 115200, timeout=2)
time.sleep(1)

def cmd(c, wait=0.5):
    ser.reset_input_buffer()
    ser.write(f"{c}\r\n".encode())
    time.sleep(wait)
    r = ""
    while ser.in_waiting:
        r += ser.read(ser.in_waiting).decode("utf-8", errors="replace")
        time.sleep(0.05)
    return r.strip()

# Check
r = cmd("AT")
if "OK" not in r:
    print(f"✗ Module ne répond pas sur {PORT}")
    ser.close()
    sys.exit(1)

ver = cmd("AT+version?").split("\n")[0].strip()
print(f"✓ Module détecté: {ver}")

# Configure
if ROLE == "anchor":
    print(f"\nConfiguration → Anchor ID={AID}")
    r = cmd(f"AT+anchor_tag=1,{AID}")
    print(f"  AT+anchor_tag=1,{AID} → {r}")
else:
    print(f"\nConfiguration → Tag")
    r = cmd("AT+anchor_tag=0")
    print(f"  AT+anchor_tag=0 → {r}")

# Verify
r = cmd("AT+anchor_tag?")
lines = [l.strip() for l in r.split("\n") if l.strip() and l.strip() != "OK"]
print(f"  Vérif: {' | '.join(lines)}")

# Reset to confirm persistence
print("\nReset pour confirmer...")
ser.reset_input_buffer()
ser.write(b"AT+RST\r\n")
time.sleep(3)
r = ""
while ser.in_waiting:
    r += ser.read(ser.in_waiting).decode("utf-8", errors="replace")
    time.sleep(0.05)

for line in r.split("\n"):
    line = line.strip()
    if line.startswith("device:"):
        label = line
        print(f"\n  ✅ Confirmé: {line}")
        break
else:
    # Show all boot lines
    for line in r.split("\n"):
        line = line.strip()
        if line:
            print(f"  Boot: {line}")

ser.close()

expected = f"anchor ID:{AID}" if ROLE == "anchor" else "TAG"
mark = f"A{AID}" if ROLE == "anchor" else "TAG"
print(f"\n  📝 Marquez ce module: \"{mark}\"")
print(f"     Vous pouvez le débrancher.\n")
