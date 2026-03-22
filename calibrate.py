"""
scripts/calibrate.py — Per-environment path loss exponent calibration.

Place the Target phone at known distances from ONE anchor phone.
Record RSSI at each distance. This script fits the optimal n value.

Usage:
    python scripts/calibrate.py

Outputs:
    Suggested PATH_LOSS_EXPONENT value for server/utils/config.py
"""

import math
import numpy as np

print("=" * 55)
print("  Braket 1.5 — Path Loss Exponent Calibration")
print("=" * 55)
print()
print("Place the target phone at known distances from ONE anchor.")
print("Enter at least 5 (distance, RSSI) measurements.")
print("Type 'done' when finished.")
print()

TX_POWER = int(input("Tx power (from BLE ad packet, usually -59): ") or "-59")

measurements = []
while True:
    entry = input("Enter 'distance_m RSSI_dBm' (e.g. '1.0 -52') or 'done': ").strip()
    if entry.lower() == "done":
        break
    try:
        parts = entry.split()
        d, rssi = float(parts[0]), float(parts[1])
        measurements.append((d, rssi))
        print(f"  Added: {d}m → {rssi} dBm")
    except (ValueError, IndexError):
        print("  Invalid format. Try: 1.5 -65")

if len(measurements) < 3:
    print("Need at least 3 measurements.")
    exit(1)

# Fit n: RSSI = TX_POWER - 10*n*log10(d)
# → n = (TX_POWER - RSSI) / (10 * log10(d))
ns = []
for d, rssi in measurements:
    if d > 0:
        n_val = (TX_POWER - rssi) / (10 * math.log10(d))
        ns.append(n_val)

n_median = float(np.median(ns))
n_mean = float(np.mean(ns))
n_std = float(np.std(ns))

print()
print("─" * 45)
print(f"  Measurements : {len(measurements)}")
print(f"  n (median)   : {n_median:.3f}  ← use this")
print(f"  n (mean)     : {n_mean:.3f}")
print(f"  n (std)      : {n_std:.3f}")
print()
print(f"  Expected range: 2.0 (open space) — 4.0 (dense office)")

if n_std > 0.5:
    print("  ⚠ High variance — try measuring in a straight line away from walls.")

print()
print("Update server/utils/config.py:")
print(f"  PATH_LOSS_EXPONENT = {n_median:.2f}")
print()
print(f"  Also set DEFAULT_TX_POWER_DBM = {TX_POWER}")
