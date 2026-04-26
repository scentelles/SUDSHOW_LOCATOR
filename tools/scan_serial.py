import serial, time

PORT = "COM7"

# Test 1: Read raw bytes at different bauds
for baud in [115200, 9600, 230400]:
    s = serial.Serial(PORT, baud, timeout=0.3)
    time.sleep(0.2)
    s.setDTR(False)  # toggle reset via DTR if connected
    time.sleep(0.1)
    s.setDTR(True)
    time.sleep(0.5)
    raw = s.read(256)
    s.close()
    if raw:
        print(f"Baud {baud}: {len(raw)} bytes => {raw[:60]}")
    else:
        print(f"Baud {baud}: rien")

# Test 2: Interactive - wait for user to press RESET
print("\n--- Appuie sur RESET sur la carte maintenant ! ---")
s = serial.Serial(PORT, 115200, timeout=0.2)
s.read(s.in_waiting)
start = time.time()
got_data = False
while time.time() - start < 15:
    raw = s.read(128)
    if raw:
        got_data = True
        try:
            txt = raw.decode("utf-8", errors="replace")
            print(f"  [{time.time()-start:.1f}s] TXT: {txt.strip()}")
        except:
            print(f"  [{time.time()-start:.1f}s] RAW: {raw.hex()}")

if not got_data:
    print("  => Aucune donnee recue en 15 secondes")
s.close()
print("Done.")
