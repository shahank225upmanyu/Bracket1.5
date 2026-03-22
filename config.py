"""
utils/config.py — Central configuration for the Braket 1.5 server.

Edit ANCHOR_POSITIONS to match your physical anchor placement (in metres).
(0, 0) is the origin corner you marked on the floor during setup.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Security ──────────────────────────────────────────────────────────────────
# MUST match android Config.kt HMAC_SECRET
SECRET_KEY: str = os.getenv("BRAKET_SECRET", "braket-1.5-secret-change-in-production")

# ── Anchor physical positions (metres) ───────────────────────────────────────
# Key = anchorId as advertised in BLE packet ("BRAKET-A", etc.)
# Value = (x, y) in your coordinate system
ANCHOR_POSITIONS: dict[str, tuple[float, float]] = {
    "BRAKET-A": (0.0, 0.0),     # Origin corner
    "BRAKET-B": (5.0, 0.0),     # Along X axis
    "BRAKET-C": (5.0, 4.0),     # Far corner
    "BRAKET-D": (0.0, 4.0),     # Along Y axis
}

ROOM_WIDTH_M: float = 5.0
ROOM_HEIGHT_M: float = 4.0

# ── Path Loss Model ───────────────────────────────────────────────────────────
# These are calibrated per-environment during Phase 0 setup.
# Run scripts/calibrate.py to find your values.
DEFAULT_TX_POWER_DBM: int = -59          # RSSI at 1 m reference distance
PATH_LOSS_EXPONENT: float = 2.8          # n — 2.0 free space, 3.5+ dense office
PATH_LOSS_EXPONENT_NLOS: float = 3.8     # n for identified NLOS paths

# ── EKF Noise Parameters ──────────────────────────────────────────────────────
EKF_PROCESS_NOISE_XY: float = 0.05      # How uncertain is our motion model (m²)
EKF_PROCESS_NOISE_V: float = 0.10       # How uncertain is velocity (m/s)²
EKF_MEAS_NOISE_BLE: float = 1.5         # BLE position measurement noise (m²)
EKF_MEAS_NOISE_PDR: float = 0.3         # PDR measurement noise (m²)

# ── KNN Fingerprint ───────────────────────────────────────────────────────────
KNN_K: int = 3                           # Number of nearest neighbours
KNN_DISTANCE_METRIC: str = "euclidean"
FINGERPRINT_DB_PATH: str = "data/radio_map.json"
MAG_MAP_PATH: str = "data/mag_map.json"

# ── Security Watchdog ─────────────────────────────────────────────────────────
MAX_HUMAN_SPEED_MS: float = 2.5          # m/s — sprint walking limit
VELOCITY_GATE_FACTOR: float = 1.5        # Allow burst up to 1.5× max speed
ANOMALY_CONTAMINATION: float = 0.05      # Expected fraction of spoofed packets
ANOMALY_MODEL_PATH: str = "data/watchdog_model.pkl"

# ── WebSocket Server ──────────────────────────────────────────────────────────
WS_HOST: str = "0.0.0.0"
WS_PORT: int = 8765
HTTP_HOST: str = "0.0.0.0"
HTTP_PORT: int = 8000

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE: str = "logs/braket.log"
