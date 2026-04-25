#!/usr/bin/env python3
"""Test config persistence on BU-01 module."""
import serial, time, sys

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"
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

# 1. Check module
print("=== MODULE ACTUEL ===")
print(f"AT: {cmd('AT')}")
ver = cmd("AT+version?")
print(f"Version: {ver}")
role = cmd("AT+anchor_tag?")
print(f"Role: {role}")

# 2. Configure as Anchor ID=1
print("\n=== CONFIG ANCHOR ID=1 ===")
r = cmd("AT+anchor_tag=1,1")
print(f"AT+anchor_tag=1,1 -> {r}")

# Check before reset
print("\n=== VERIF AVANT RESET ===")
r = cmd("AT+anchor_tag?")
print(f"anchor_tag? : {r}")

# Test save commands
print("\n=== TEST SAVE COMMANDS ===")
for s in ["AT+save", "AT+SAVE", "AT+store", "AT+write", "AT+flash"]:
    r = cmd(s, 0.3)
    tag = "OK" if "OK" in r else "FAIL" if not r else "???"
    print(f"  {s:20s} [{tag}] {repr(r)[:60]}")

# Reset
print("\n=== RESET ===")
ser.reset_input_buffer()
ser.write(b"AT+RST\r\n")
time.sleep(3)
r = ""
while ser.in_waiting:
    r += ser.read(ser.in_waiting).decode("utf-8", errors="replace")
    time.sleep(0.05)
for line in r.split("\n"):
    line = line.strip()
    if line:
        print(f"  {line}")

# After reset
print("\n=== APRES RESET ===")
r = cmd("AT+anchor_tag?")
print(f"anchor_tag? : {repr(r)}")

ser.close()
print("\nDone")
