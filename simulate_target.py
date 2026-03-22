"""
scripts/simulate_target.py — Dummy target phone simulator.

Sends realistic WebSocket packets to the server so Squad B can develop and
test the math without waiting for Squad A's Android app.

Simulates a person walking a figure-8 path in a 5m × 4m room with 4 anchors.
RSSI is computed from true path-loss + Gaussian noise.

Usage:
    python scripts/simulate_target.py [--host 192.168.1.100] [--port 8765]
"""

import asyncio
import base64
import hashlib
import hmac
import json
import math
import random
import time
import argparse

SECRET = "braket-1.5-secret-change-in-production"

ANCHORS = {
    "BRAKET-A": (0.0, 0.0),
    "BRAKET-B": (5.0, 0.0),
    "BRAKET-C": (5.0, 4.0),
    "BRAKET-D": (0.0, 4.0),
}

TX_POWER = -59
N = 2.8


def true_rssi(tx: float, ty: float, ax: float, ay: float) -> int:
    dist = math.sqrt((tx - ax)**2 + (ty - ay)**2)
    dist = max(dist, 0.1)
    path_loss = TX_POWER - 10 * N * math.log10(dist)
    noise = random.gauss(0, 2.5)   # ±2.5 dBm noise
    return int(path_loss + noise)


def sign(payload_str: str) -> str:
    raw = hmac.new(
        SECRET.encode(), payload_str.encode(), hashlib.sha256
    ).digest()
    return base64.b64encode(raw).decode("ascii")


def figure8_path(t: float, cx: float = 2.5, cy: float = 2.0,
                 rx: float = 2.0, ry: float = 1.5) -> tuple[float, float]:
    """Lissajous figure-8: x=sin(t), y=sin(2t)"""
    x = cx + rx * math.sin(t)
    y = cy + ry * math.sin(2 * t)
    return x, y


async def run(host: str, port: int):
    import websockets
    uri = f"ws://{host}:{port}/ws"
    print(f"Connecting to {uri}…")

    async with websockets.connect(uri) as ws:
        print("Connected. Sending simulated packets at 10 Hz…")
        t = 0.0
        step_count = 0
        last_x, last_y = figure8_path(0)
        heading = 0.0

        while True:
            t += 0.1         # advance path parameter
            x, y = figure8_path(t)

            # Step detection simulation
            dist_step = math.sqrt((x - last_x)**2 + (y - last_y)**2)
            if dist_step > 0.6:
                step_count += 1
            dx = x - last_x
            dy = y - last_y
            if dist_step > 0.01:
                heading = math.degrees(math.atan2(dx, dy))
            last_x, last_y = x, y

            # Build anchor readings
            anchors = []
            for aid, (ax, ay) in ANCHORS.items():
                rssi = true_rssi(x, y, ax, ay)
                dist = 10 ** ((TX_POWER - rssi) / (10 * N))
                anchors.append({
                    "id": aid,
                    "rssi": rssi,
                    "tx_power": TX_POWER,
                    "dist_m": round(dist, 3)
                })

            # IMU simulation (simple walking model)
            ax_sim = random.gauss(0, 0.3)
            ay_sim = random.gauss(-9.81, 0.3)
            az_sim = random.gauss(0, 0.3)

            # Magnetometer simulation (static anomaly field)
            bx = 22.0 + 3 * math.sin(x) + random.gauss(0, 0.2)
            by = -14.0 + 3 * math.cos(y) + random.gauss(0, 0.2)
            bz = 42.0 + random.gauss(0, 0.2)

            payload = {
                "ts": int(time.time() * 1000),
                "device_id": "simulator-001",
                "anchors": anchors,
                "imu": {
                    "ax": round(ax_sim, 4), "ay": round(ay_sim, 4), "az": round(az_sim, 4),
                    "gx": round(random.gauss(0, 0.01), 4),
                    "gy": round(random.gauss(0, 0.01), 4),
                    "gz": round(random.gauss(0, 0.01), 4),
                    "steps": step_count,
                    "heading": round(heading, 2)
                },
                "mag": {
                    "bx": round(bx, 3), "by": round(by, 3), "bz": round(bz, 3),
                    "mag": round(math.sqrt(bx**2 + by**2 + bz**2), 3)
                },
                "pdr": {
                    "dx": round(dx, 4), "dy": round(dy, 4),
                    "heading": round(heading, 2),
                    "steps": step_count
                }
            }

            payload_str = json.dumps(payload, separators=(",", ":"))
            sig = sign(payload_str)
            payload["sig"] = sig

            await ws.send(json.dumps(payload))

            # Print server response
            try:
                resp = await asyncio.wait_for(ws.recv(), timeout=0.05)
                data = json.loads(resp)
                if data.get("type") == "position":
                    est_x = data.get("x", 0)
                    est_y = data.get("y", 0)
                    err = math.sqrt((est_x - x)**2 + (est_y - y)**2)
                    print(
                        f"True({x:.2f},{y:.2f}) → Est({est_x:.2f},{est_y:.2f}) "
                        f"err={err:.2f}m  acc=±{data.get('accuracy_m',0):.2f}m "
                        f"anchors={data.get('n_anchors',0)}"
                    )
                elif data.get("type") == "alert":
                    print(f"  ⚠ ALERT: {data.get('reason')}")
            except asyncio.TimeoutError:
                pass

            await asyncio.sleep(0.1)   # 10 Hz


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    asyncio.run(run(args.host, args.port))
