#!/usr/bin/env python3
"""BU-01 — Set interval to minimum and measure rate."""

import serial
import time

PORT = "COM7"
BAUD = 115200

def send_at(s, cmd, wait=0.3):
    s.read(s.in_waiting)
    s.write((cmd + "\r\n").encode())
    time.sleep(wait)
    resp = s.read(s.in_waiting).decode("utf-8", errors="ignore").strip()
    print(f"  {cmd:35s} => {resp if resp else '(no response)'}")
    return resp

def measure_rate(s, duration=10):
    """Measure the actual ranging rate."""
    s.read(s.in_waiting)
    start = time.time()
    cycle_timestamps = []
    while time.time() - start < duration:
        line = s.readline()
        if line:
            text = line.decode("utf-8", errors="ignore").strip()
            if text.startswith("an0:"):
                cycle_timestamps.append(time.time() - start)
            if text.startswith("an"):
                ts = time.time() - start
                print(f"    [{ts:5.2f}s] {text}")

    n = len(cycle_timestamps)
    hz = n / duration if duration > 0 else 0
    avg_ms = 0
    if n > 1:
        intervals = [cycle_timestamps[i+1] - cycle_timestamps[i] for i in range(n-1)]
        avg_ms = sum(intervals) / len(intervals) * 1000
    print(f"\n  => {n} complete cycles in {duration}s = {hz:.2f} Hz (avg interval: {avg_ms:.0f} ms)")
    return hz

def main():
    s = serial.Serial(PORT, BAUD, timeout=1)
    time.sleep(0.5)
    s.read(s.in_waiting)

    print("=" * 60)
    print("BU-01 — Speed Optimization")
    print("=" * 60)

    # Reset and configure
    send_at(s, "AT")
    send_at(s, "AT+anchor_tag=0")  # Tag mode

    # Test different interval values: 5, 10, 15, 20 (default?)
    for interval_val in [5, 10, 15, 20, 50]:
        print(f"\n{'='*60}")
        print(f"Testing AT+interval={interval_val}")
        print(f"{'='*60}")
        resp = send_at(s, f"AT+interval={interval_val}")
        send_at(s, "AT+switchdis=1")
        time.sleep(0.5)
        rate = measure_rate(s, 10)
        print(f"  >>> interval={interval_val} => {rate:.2f} Hz")

    # Also try with anchors directly
    # Try reducing the number of anchor queries
    print(f"\n{'='*60}")
    print("Final test with interval=5")
    print(f"{'='*60}")
    send_at(s, "AT+interval=5")
    send_at(s, "AT+switchdis=1")
    time.sleep(0.5)
    measure_rate(s, 10)

    s.close()
    print("\nDone.")

if __name__ == "__main__":
    main()
