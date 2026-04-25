#!/usr/bin/env python3
"""Quick UDP listener to test ESP32 packets."""
import socket, json, time

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("0.0.0.0", 9000))
sock.settimeout(2)

print("=== Ecoute UDP port 9000 ===")
print("En attente de paquets de l'ESP32...")
print()

start = time.time()
count = 0
while time.time() - start < 30:
    try:
        data, addr = sock.recvfrom(1024)
        msg = json.loads(data.decode("utf-8"))
        count += 1
        x = msg.get("x", 0)
        y = msg.get("y", 0)
        q = msg.get("q", 0)
        d = msg.get("d", [])
        dist_str = ", ".join(f"{v:.2f}m" for v in d) if d else "N/A"
        print(f"  [{count:3d}] From {addr[0]} | x={x:.3f}  y={y:.3f}  q={q:.0%}  d=[{dist_str}]")
    except socket.timeout:
        elapsed = int(time.time() - start)
        print(f"  [{elapsed}s] En attente...")
    except json.JSONDecodeError:
        print(f"  JSON invalide: {data}")
    except Exception as e:
        print(f"  Erreur: {e}")

print(f"\nTotal: {count} paquets recus en 30s")
sock.close()
