from flask import Flask, request, jsonify
import math
import numpy as np
from datetime import datetime

app = Flask(__name__)

# --- 🎯 MASTER ANCHOR CONFIGURATION (From your Logs) ---
# Coordinates in Meters: (X, Y)
# --- 🎯 MASTER ANCHOR CONFIGURATION (Updated) ---
ANCHOR_LOCATIONS = {
    "Braket_Anchor_B": (0.0, 0.0),    
    "Bracket_Anchor_C": (2.0, 0.0),   
    "DIRECT-SQLAPTOP-C0KS24P7m": (2.0, 2.0)  # Naya strong anchor
}

# --- 🧪 CALIBRATION PARAMETERS ---
MEASURED_POWER = -48  # RSSI at 1 meter (Optimized for your data)
N = 3.2               # Indoor path-loss exponent

# Kalman Filter Storage for smoothing
kf_states = {} 

def kalman_filter(ssid, rssi):
    if ssid not in kf_states:
        kf_states[ssid] = [rssi, 1.0]
    estimate, error = kf_states[ssid]
    # Parameters for smooth tracking
    process_noise = 0.1
    measurement_noise = 0.5
    gain = (error + process_noise) / (error + process_noise + measurement_noise)
    new_estimate = estimate + gain * (rssi - estimate)
    kf_states[ssid] = [new_estimate, (1 - gain) * (error + process_noise)]
    return new_estimate

def rssi_to_meters(rssi):
    if rssi == 0: return 0.0
    return math.pow(10, (MEASURED_POWER - rssi) / (10 * N))

def trilaterate_lls(anchors):
    """Linear Least Squares for Pin-Point Accuracy"""
    if len(anchors) < 3: return None
    try:
        A = []
        B = []
        # Use first anchor as relative origin
        x1, y1, d1 = anchors[0]
        for i in range(1, len(anchors)):
            xi, yi, di = anchors[i]
            A.append([2 * (xi - x1), 2 * (yi - y1)])
            B.append(xi**2 + yi**2 - di**2 - x1**2 - y1**2 + d1**2)
        
        # Solving the linear system: A * [x, y] = B
        res = np.linalg.lstsq(np.array(A), np.array(B), rcond=None)[0]
        return round(res[0], 2), round(res[1], 2)
    except Exception as e:
        print(f"Math Error: {e}")
        return None

@app.route('/rssi', methods=['POST'])
def rssi_receiver():
    data = request.json
    readings = data.get("readings", [])
    valid_anchors = []

    print(f"\n📡 [LIVE TRACKING] {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'Anchor SSID':<20} | {'Dist (m)':<10} | {'RSSI':<5}")
    print("-" * 45)

    for r in readings:
        ssid, rssi = r.get("ssid"), r.get("rssi")
        if ssid in ANCHOR_LOCATIONS:
            # Filtering and Smoothing
            smooth_rssi = kalman_filter(ssid, rssi)
            dist = rssi_to_meters(smooth_rssi)
            x, y = ANCHOR_LOCATIONS[ssid]
            valid_anchors.append((x, y, dist))
            print(f"{ssid:<20} | {dist:<10.2f} | {rssi:<5}")

    # Calculate X, Y position
    if len(valid_anchors) >= 3:
        pos = trilaterate_lls(valid_anchors)
        if pos:
            print(f"📍 CURRENT LOCATION: X={pos[0]}m, Y={pos[1]}m")
    else:
        print(f"⚠️ Need more Anchors. Found: {len(valid_anchors)}/3")

    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    # Using your laptop IP
    app.run(host='0.0.0.0', port=5000, debug=False)