"""
server/main.py — Braket 1.5 positioning server.

Starts two services on the same process:
  1. FastAPI HTTP server  (port 8000) — REST API for survey, config, status
  2. WebSocket server     (port 8765) — real-time positioning stream from phones

Each connected Target phone gets its own session with:
  - Independent EKF state
  - Shared fingerprint DB (read-only)
  - Independent watchdog instance

Run: python main.py
"""

import asyncio
import json
import time
import websockets
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router, init_routes
from core.ekf import ExtendedKalmanFilter
from core.trilateration import trilaterate, AnchorMeasurement
from core.fingerprint import FingerprintDB
from ml.watchdog import SecurityWatchdog
from utils.auth import verify_packet
from utils.config import WS_HOST, WS_PORT, HTTP_HOST, HTTP_PORT, ANCHOR_POSITIONS
from utils.logger import get_logger

log = get_logger("main")

# ── Shared state ──────────────────────────────────────────────────────────────
fingerprint_db = FingerprintDB()
connected_clients: dict[str, dict] = {}   # device_id → session


def create_session(device_id: str) -> dict:
    return {
        "device_id": device_id,
        "ekf": ExtendedKalmanFilter(initial_x=0.0, initial_y=0.0),
        "watchdog": SecurityWatchdog(),
        "rssi_state": {},       # per-anchor RSSI Kalman smoother state
        "last_packet_ts": 0,
        "packet_count": 0,
        "alert_count": 0,
    }


# ── WebSocket handler ─────────────────────────────────────────────────────────
async def handle_client(websocket, path="/ws"):
    device_id = f"unknown-{id(websocket)}"
    session = None

    try:
        async for raw_msg in websocket:
            # 1. Verify HMAC signature
            ok, packet = verify_packet(raw_msg)
            if not ok:
                log.warning(f"[{device_id}] Rejected: invalid HMAC signature")
                await websocket.send(json.dumps({"type": "alert", "reason": "auth_failure"}))
                continue

            device_id = packet.get("device_id", device_id)

            # 2. Create or retrieve session
            if device_id not in connected_clients:
                connected_clients[device_id] = create_session(device_id)
                log.info(f"[{device_id}] New session started")
            session = connected_clients[device_id]
            session["packet_count"] += 1

            # 3. Rate-limit check (no more than 30 Hz)
            now_ms = packet.get("ts", int(time.time() * 1000))
            dt_ms = now_ms - session["last_packet_ts"]
            if dt_ms < 33:   # < 33 ms = > 30 Hz — suspicious replay
                continue
            session["last_packet_ts"] = now_ms
            dt_s = dt_ms / 1000.0

            # 4. EKF prediction step
            ekf: ExtendedKalmanFilter = session["ekf"]
            ekf.predict(dt=dt_s)

            # 5. Parse anchor readings
            anchors_raw = packet.get("anchors", [])
            measurements = [
                AnchorMeasurement(
                    anchor_id=a["id"],
                    rssi=int(a["rssi"]),
                    tx_power=int(a.get("tx_power", -59)),
                    dist_m=float(a.get("dist_m", 0.0))
                )
                for a in anchors_raw
                if a.get("id") in ANCHOR_POSITIONS
            ]

            # 6. PDR update from IMU dead reckoning
            pdr = packet.get("pdr", {})
            dx, dy = float(pdr.get("dx", 0.0)), float(pdr.get("dy", 0.0))
            if abs(dx) + abs(dy) > 0.01:
                ekf.update_pdr(dx, dy)

            # 7. BLE trilateration → EKF update
            tril_result = None
            if len(measurements) >= 3:
                tril_result = trilaterate(measurements, session["rssi_state"])
                if tril_result:
                    ekf.update_position(
                        tril_result.x,
                        tril_result.y,
                        noise_scale=tril_result.noise_scale
                    )

            # 8. RF Fingerprint update (if radio map is available)
            live_rssi = {a["id"]: float(a["rssi"]) for a in anchors_raw if a.get("id") in ANCHOR_POSITIONS}
            mag_raw = packet.get("mag", {})
            live_mag = [mag_raw.get("bx", 0), mag_raw.get("by", 0), mag_raw.get("bz", 0)]

            if fingerprint_db.size >= 5 and live_rssi:
                fp_match = fingerprint_db.match(live_rssi, live_mag if any(live_mag) else None)
                if fp_match and fp_match.confidence > 0.3:
                    # Fingerprint updates carry less noise when confidence is high
                    noise = 1.5 / max(fp_match.confidence, 0.1)
                    ekf.update_position(fp_match.x, fp_match.y, noise_scale=noise)

            # 9. Security watchdog
            pos = ekf.position
            watchdog_result = session["watchdog"].check(pos[0], pos[1], anchors_raw)

            if not watchdog_result.accepted:
                session["alert_count"] += 1
                log.warning(
                    f"[{device_id}] SECURITY ALERT: {watchdog_result.reason} "
                    f"speed={watchdog_result.speed_estimate_ms} m/s "
                    f"alerts={session['alert_count']}"
                )
                await websocket.send(json.dumps({
                    "type": "alert",
                    "reason": watchdog_result.reason,
                    "speed_ms": watchdog_result.speed_estimate_ms,
                }))
                # Don't emit a position on rejected packets
                continue

            # 10. Build and send position response
            state = ekf.state_dict()
            response = {
                "type": "position",
                "device_id": device_id,
                "x": state["x"],
                "y": state["y"],
                "accuracy_m": state["accuracy_m"],
                "speed_ms": state["speed_ms"],
                "n_anchors": len(measurements),
                "gdop": tril_result.gdop if tril_result else None,
                "fp_active": fingerprint_db.size >= 5,
                "ts": now_ms,
            }
            await websocket.send(json.dumps(response))

            # Console log every 10 packets
            if session["packet_count"] % 10 == 0:
                log.info(
                    f"[{device_id}] x={state['x']:.2f}m y={state['y']:.2f}m "
                    f"acc=±{state['accuracy_m']:.2f}m anchors={len(measurements)} "
                    f"pkts={session['packet_count']}"
                )

    except websockets.exceptions.ConnectionClosedOK:
        log.info(f"[{device_id}] Connection closed normally")
    except websockets.exceptions.ConnectionClosedError as e:
        log.warning(f"[{device_id}] Connection closed with error: {e}")
    except Exception as e:
        log.error(f"[{device_id}] Unhandled error: {e}", exc_info=True)
    finally:
        connected_clients.pop(device_id, None)
        log.info(f"[{device_id}] Session removed. Active sessions: {len(connected_clients)}")


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Braket 1.5 Positioning Server",
    version="1.0.0",
    description="Indoor/outdoor positioning via smartphone BLE beacon cluster"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_routes(fingerprint_db, SecurityWatchdog())
app.include_router(router, prefix="/api")


@app.get("/")
def root():
    return {
        "service": "Braket 1.5",
        "ws_url": f"ws://{WS_HOST}:{WS_PORT}/ws",
        "http_url": f"http://{HTTP_HOST}:{HTTP_PORT}",
        "active_sessions": len(connected_clients),
        "radio_map_size": fingerprint_db.size,
    }


# ── Entry point ───────────────────────────────────────────────────────────────
async def main():
    log.info("=" * 60)
    log.info("  Braket 1.5 Positioning Server")
    log.info(f"  WebSocket : ws://{WS_HOST}:{WS_PORT}/ws")
    log.info(f"  HTTP API  : http://{HTTP_HOST}:{HTTP_PORT}/api")
    log.info(f"  Radio map : {fingerprint_db.size} reference points loaded")
    log.info("=" * 60)

    # Start WebSocket server
    ws_server = await websockets.serve(
        handle_client,
        WS_HOST,
        WS_PORT,
        ping_interval=10,
        ping_timeout=20,
        max_size=1_000_000,  # 1 MB max message size
    )

    # Start FastAPI/uvicorn server
    config = uvicorn.Config(
        app, host=HTTP_HOST, port=HTTP_PORT,
        log_level="warning",   # uvicorn's own logs are too verbose
        access_log=False
    )
    uv_server = uvicorn.Server(config)

    log.info("Both servers running. Press Ctrl+C to stop.")
    await asyncio.gather(
        ws_server.wait_closed(),
        uv_server.serve()
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Server stopped.")
