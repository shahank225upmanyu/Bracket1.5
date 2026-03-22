# Bracket 1.5 — Smartphone Cluster Positioning System

> Sub-meter indoor & outdoor positioning using a cluster of Android smartphones as beacons — no proprietary hardware required.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    ANCHOR PHONES (3–4)                       │
│   BLE Advertise + Wi-Fi Hotspot + Magnetometer Stream        │
└────────────────────┬────────────────────────────────────────┘
                     │ BLE signals (10 Hz)
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    TARGET PHONE                              │
│  BLE Scanner │ IMU (Accel+Gyro) │ Magnetometer │ JSON Pack  │
└────────────────────┬────────────────────────────────────────┘
                     │ WebSocket JSON stream
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  LAPTOP SERVER (FastAPI)                     │
│  EKF Fusion │ RF Fingerprint │ KNN-SIPS │ Security Watchdog │
│                       ↓                                      │
│              x, y position output                            │
└─────────────────────────────────────────────────────────────┘
```

## Stack

| Layer | Technology |
|---|---|
| Android App | Kotlin, BLE API, SensorManager, OkHttp WebSocket |
| Server | Python 3.11+, FastAPI, WebSocket, asyncio |
| Math | Extended Kalman Filter, WLS Trilateration, KNN-SIPS |
| Security | HMAC-SHA256 auth, velocity gate, Isolation Forest |
| ML | scikit-learn (anomaly detection), numpy, scipy |

## Quick Start

### 1. Server
```bash
cd server
pip install -r requirements.txt
python main.py
# Server starts at ws://0.0.0.0:8765 and http://0.0.0.0:8000
```

### 2. Android App
```
Open /android in Android Studio
Set SERVER_IP in app/src/main/java/com/braket/positioning/network/Config.kt
Build & run on Target phone (minSdk 26)
```

### 3. Anchor phones
- Open the app → tap "Anchor Mode"
- Enter a unique Anchor ID (A, B, C, D)
- Place at the four corners of the space
- Tap "Start Broadcasting"

### 4. Target phone
- Open the app → tap "Target Mode"
- Walk the survey grid (floor plan shows RPs)
- Tap "Go Live" when survey is complete

## Project Structure

```
Bracket1.5/
├── android/                    # Android Studio project (Squad A)
│   └── app/src/main/java/com/braket/positioning/
│       ├── anchor/             # BLE advertising + anchor server
│       ├── target/             # BLE scanning + sensor fusion client
│       ├── sensor/             # IMU + magnetometer readers
│       ├── network/            # WebSocket client + auth
│       ├── fusion/             # On-device PDR dead reckoning
│       ├── security/           # HMAC packet signing
│       └── ui/                 # Activities + ViewModels
├── server/                     # Python backend (Squad B)
│   ├── main.py                 # FastAPI + WebSocket entry point
│   ├── core/
│   │   ├── ekf.py              # Extended Kalman Filter
│   │   ├── trilateration.py    # WLS trilateration
│   │   └── fingerprint.py      # KNN-SIPS radio map
│   ├── ml/
│   │   ├── watchdog.py         # Isolation Forest anomaly detector
│   │   └── trainer.py          # Model training scripts
│   ├── api/
│   │   └── routes.py           # REST endpoints (survey, config)
│   └── utils/
│       ├── config.py           # Anchor layout, calibration params
│       ├── auth.py             # HMAC verification
│       └── logger.py           # Structured logging
├── tests/                      # Unit + integration tests
├── scripts/                    # Setup + calibration helpers
└── docs/                       # Architecture docs
```

## Accuracy Targets

| Phase | Stack | Expected Error |
|---|---|---|
| Phase 1 | BLE + WLS Trilateration | 2–4 m |
| Phase 2 | + EKF + IMU fusion | 1–2 m |
| Phase 3 | + RF Fingerprint (KNN-SIPS) | 0.8–1.5 m |
| Phase 4 | + Geomagnetic layer | 0.5–1.0 m |

## Known Limitations

- Android 10+ throttles `WifiManager.startScan()` to 4 scans/2 min — this project uses BLE (unthrottled) as the primary signal
- Full CSI extraction requires Nexmon-patched firmware (BCM chipsets only) — treated as optional
- Geomagnetic map must be re-surveyed if large metal objects are moved
