#!/usr/bin/env python3
"""BU-01 AT command explorer — read data stream + try AT commands."""

import serial
import time
import sys

PORT = "COM7"
BAUD = 115200

def main():
    s = serial.Serial(PORT, BAUD, timeout=1)
    time.sleep(0.3)
    s.read(s.in_waiting)  # flush

    # 1) Read incoming data for 5 seconds
    print("=" * 50)
    print(f"Reading BU-01 data stream on {PORT} for 5s...")
    print("=" * 50)
    start = time.time()
    line_count = 0
    while time.time() - start < 5:
        line = s.readline()
        if line:
            ts = time.time() - start
            text = line.decode("utf-8", errors="ignore").strip()
            if text:
                print(f"  [{ts:5.2f}s] {text}")
                line_count += 1
    print(f"\n=> {line_count} lines in 5s = {line_count/5:.1f} lines/s\n")

    # 2) Try AT commands to discover capabilities
    at_commands = [
        "AT",
        "AT+help",
        "AT+version",
        "AT+switchdis=1",
        "AT+cap",
        "AT+interval",
        "AT+rate",
        "AT+setting",
        "AT+range_interval",
        "AT+at_cfg",
    ]

    print("=" * 50)
    print("Trying AT commands...")
    print("=" * 50)
    for cmd in at_commands:
        s.read(s.in_waiting)  # flush
        s.write((cmd + "\r\n").encode())
        time.sleep(0.5)
        resp = s.read(s.in_waiting).decode("utf-8", errors="ignore").strip()
        print(f"  {cmd:30s} => {resp if resp else '(no response)'}")

    # 3) Read again for 5s to see if anything changed
    print("\n" + "=" * 50)
    print("Reading data stream for 5 more seconds...")
    print("=" * 50)
    s.read(s.in_waiting)
    start = time.time()
    line_count = 0
    while time.time() - start < 5:
        line = s.readline()
        if line:
            ts = time.time() - start
            text = line.decode("utf-8", errors="ignore").strip()
            if text:
                print(f"  [{ts:5.2f}s] {text}")
                line_count += 1
    print(f"\n=> {line_count} lines in 5s = {line_count/5:.1f} lines/s")

    s.close()
    print("\nDone.")

if __name__ == "__main__":
    main()
