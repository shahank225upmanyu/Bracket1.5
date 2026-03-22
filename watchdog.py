"""
ml/watchdog.py — Two-layer security watchdog.

Layer 1 — Deterministic velocity gate (no ML needed):
  Rejects any position update that implies physically impossible movement.
  Threshold: 2.5 m/s × 1.5 = 3.75 m/s (sprint pace).
  This catches obvious spoofing: "I'm at corner A, now instantly at corner C."

Layer 2 — Isolation Forest anomaly detector (sklearn):
  Learns the statistical distribution of legitimate BLE signals from real anchors.
  At inference time, packets whose RSSI patterns are statistically implausible
  are flagged. This catches: replay attacks, fake BLE beacons, signal injection.

  Features per packet:
    - RSSI values from each anchor (up to 4)
    - RSSI variance across anchors
    - Number of visible anchors
    - Dominant anchor change rate (anchor identity flipping = suspicious)
    - Packet inter-arrival time

  The model is trained once on the first ~200 legitimate packets and saved.
  It auto-retrains when moved to a new environment.
"""

import os
import pickle
import time
import numpy as np
from dataclasses import dataclass
from typing import Optional
from utils.config import (
    MAX_HUMAN_SPEED_MS,
    VELOCITY_GATE_FACTOR,
    ANOMALY_CONTAMINATION,
    ANOMALY_MODEL_PATH,
    ANCHOR_POSITIONS,
)

try:
    from sklearn.ensemble import IsolationForest
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False


@dataclass
class WatchdogResult:
    accepted: bool
    reason: str          # "ok", "velocity_gate", "anomaly", "insufficient_data"
    speed_estimate_ms: Optional[float] = None
    anomaly_score: Optional[float] = None


class SecurityWatchdog:

    def __init__(self):
        # ── Velocity gate state ───────────────────────────────────────────────
        self._last_position: Optional[tuple[float, float]] = None
        self._last_position_time: float = 0.0
        self._max_speed = MAX_HUMAN_SPEED_MS * VELOCITY_GATE_FACTOR

        # ── Anomaly detector state ────────────────────────────────────────────
        self._training_buffer: list[list[float]] = []
        self._training_target = 200          # collect 200 packets before first train
        self._model: Optional[object] = None
        self._last_anchor_ids: set = set()
        self._last_packet_time: float = time.monotonic()
        self._load_model()

    # ── Public interface ──────────────────────────────────────────────────────
    def check(
        self,
        new_x: float,
        new_y: float,
        anchor_readings: list[dict],         # [{"id":…, "rssi":…}, …]
    ) -> WatchdogResult:

        # 1. Velocity gate
        speed = self._check_velocity(new_x, new_y)
        if speed is not None and speed > self._max_speed:
            return WatchdogResult(
                accepted=False,
                reason="velocity_gate",
                speed_estimate_ms=round(speed, 2)
            )

        # 2. Anomaly detection
        features = self._extract_features(anchor_readings)
        self._training_buffer.append(features)

        anomaly_score = None
        if self._model is not None:
            score = self._model.decision_function([features])[0]
            anomaly_score = round(float(score), 4)
            is_anomaly = self._model.predict([features])[0] == -1
            if is_anomaly:
                return WatchdogResult(
                    accepted=False,
                    reason="anomaly",
                    anomaly_score=anomaly_score,
                    speed_estimate_ms=round(speed, 2) if speed else None
                )
        elif len(self._training_buffer) >= self._training_target:
            self._train_model()

        # Accept — update state
        self._last_position = (new_x, new_y)
        self._last_position_time = time.monotonic()

        return WatchdogResult(
            accepted=True,
            reason="ok",
            speed_estimate_ms=round(speed, 2) if speed else None,
            anomaly_score=anomaly_score
        )

    def reset_position(self):
        """Call when user is known to have teleported (e.g. new session start)."""
        self._last_position = None
        self._last_position_time = 0.0

    # ── Velocity gate ─────────────────────────────────────────────────────────
    def _check_velocity(self, x: float, y: float) -> Optional[float]:
        now = time.monotonic()
        if self._last_position is None:
            return None
        dt = now - self._last_position_time
        if dt < 0.01:
            return None   # too close in time to compute reliable speed
        dx = x - self._last_position[0]
        dy = y - self._last_position[1]
        dist = (dx**2 + dy**2) ** 0.5
        return dist / dt

    # ── Feature extraction ────────────────────────────────────────────────────
    def _extract_features(self, anchor_readings: list[dict]) -> list[float]:
        anchor_ids = sorted(ANCHOR_POSITIONS.keys())
        now = time.monotonic()
        inter_arrival = now - self._last_packet_time
        self._last_packet_time = now

        rssi_by_anchor: dict[str, float] = {}
        for r in anchor_readings:
            aid = r.get("id", "")
            rssi = r.get("rssi", -100)
            rssi_by_anchor[aid] = float(rssi)

        # Per-anchor RSSI (default -100 if not visible)
        feats = [rssi_by_anchor.get(a, -100.0) for a in anchor_ids]

        # RSSI variance
        visible_rssi = [v for v in rssi_by_anchor.values() if v > -100]
        variance = float(np.var(visible_rssi)) if len(visible_rssi) > 1 else 0.0

        # Number of visible anchors
        n_visible = float(len(visible_rssi))

        # Anchor identity change (new anchors appearing = possible spoof)
        current_ids = set(rssi_by_anchor.keys())
        id_change = float(len(current_ids.symmetric_difference(self._last_anchor_ids)))
        self._last_anchor_ids = current_ids

        # Inter-arrival time (very fast = replay, very slow = stale)
        iat = min(inter_arrival, 5.0)

        feats.extend([variance, n_visible, id_change, iat])
        return feats

    # ── Isolation Forest ──────────────────────────────────────────────────────
    def _train_model(self):
        if not SKLEARN_AVAILABLE:
            print("[Watchdog] scikit-learn not available — anomaly detection disabled")
            return
        X = np.array(self._training_buffer)
        self._model = IsolationForest(
            contamination=ANOMALY_CONTAMINATION,
            n_estimators=100,
            random_state=42,
            n_jobs=-1
        )
        self._model.fit(X)
        self._save_model()
        print(f"[Watchdog] Isolation Forest trained on {len(X)} samples.")

    def retrain(self):
        """Force retrain — call when moving to a new environment."""
        self._training_buffer = []
        self._model = None
        if os.path.exists(ANOMALY_MODEL_PATH):
            os.remove(ANOMALY_MODEL_PATH)
        print("[Watchdog] Model cleared. Collecting new training data…")

    def _save_model(self):
        os.makedirs(os.path.dirname(ANOMALY_MODEL_PATH), exist_ok=True)
        with open(ANOMALY_MODEL_PATH, "wb") as f:
            pickle.dump(self._model, f)

    def _load_model(self):
        if not os.path.exists(ANOMALY_MODEL_PATH):
            return
        try:
            with open(ANOMALY_MODEL_PATH, "rb") as f:
                self._model = pickle.load(f)
            print("[Watchdog] Loaded existing anomaly model.")
        except Exception as e:
            print(f"[Watchdog] Could not load model: {e}")
