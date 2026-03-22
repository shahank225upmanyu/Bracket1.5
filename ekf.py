"""
core/ekf.py — Extended Kalman Filter for position tracking.

State vector: [x, y, vx, vy]
  x, y   = 2D position in metres
  vx, vy = velocity in m/s

Two measurement sources:
  1. BLE trilateration / fingerprint  → absolute (x, y) position update
  2. PDR dead reckoning               → relative (dx, dy) displacement update

Update rates:
  Prediction  : every packet (~10 Hz, driven by IMU data)
  BLE update  : every 1–2 Hz (when fresh trilateration is available)
  PDR update  : every step event (~1 Hz for walking pace)
"""

import numpy as np
import time
from utils.config import (
    EKF_PROCESS_NOISE_XY,
    EKF_PROCESS_NOISE_V,
    EKF_MEAS_NOISE_BLE,
    EKF_MEAS_NOISE_PDR,
)


class ExtendedKalmanFilter:

    def __init__(self, initial_x: float = 0.0, initial_y: float = 0.0):
        # State: [x, y, vx, vy]
        self.x = np.array([initial_x, initial_y, 0.0, 0.0], dtype=float)

        # State covariance — high initial uncertainty
        self.P = np.diag([4.0, 4.0, 1.0, 1.0])

        # Process noise covariance Q
        q_xy = EKF_PROCESS_NOISE_XY
        q_v  = EKF_PROCESS_NOISE_V
        self.Q = np.diag([q_xy, q_xy, q_v, q_v])

        # BLE measurement noise covariance R_ble (2×2, position)
        self.R_ble = np.eye(2) * EKF_MEAS_NOISE_BLE

        # PDR measurement noise covariance R_pdr (2×2, displacement)
        self.R_pdr = np.eye(2) * EKF_MEAS_NOISE_PDR

        # Measurement matrix H for absolute position (x, y) from state [x,y,vx,vy]
        self.H_abs = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0]
        ], dtype=float)

        self._last_predict_time = time.monotonic()

    # ── Prediction step ───────────────────────────────────────────────────────
    def predict(self, dt: float | None = None):
        """
        Kinematic prediction: propagate state forward by dt seconds.
        If dt is None, computes from wall clock since last predict().
        """
        now = time.monotonic()
        if dt is None:
            dt = now - self._last_predict_time
        self._last_predict_time = now

        dt = max(dt, 1e-6)   # guard against zero or negative dt

        # State transition matrix F (constant velocity model)
        F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1,  0],
            [0, 0, 0,  1],
        ], dtype=float)

        self.x = F @ self.x
        self.P = F @ self.P @ F.T + self.Q

    # ── BLE / fingerprint update ──────────────────────────────────────────────
    def update_position(self, meas_x: float, meas_y: float, noise_scale: float = 1.0):
        """
        Absolute position measurement from BLE trilateration or fingerprint match.
        noise_scale > 1 for uncertain fixes (few anchors, high GDOP).
        """
        z = np.array([meas_x, meas_y], dtype=float)
        H = self.H_abs
        R = self.R_ble * noise_scale

        y = z - H @ self.x                          # innovation
        S = H @ self.P @ H.T + R                    # innovation covariance
        K = self.P @ H.T @ np.linalg.inv(S)         # Kalman gain

        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ H) @ self.P
        self._clamp_state()

    # ── PDR displacement update ───────────────────────────────────────────────
    def update_pdr(self, dx: float, dy: float):
        """
        Relative displacement update from Pedestrian Dead Reckoning.
        Measures the *change* in position, not absolute position.
        H_pdr picks out [x, y] and computes predicted displacement from velocity.
        """
        # Expected displacement over the step period = velocity × step_dt
        # Simplified: treat PDR dx/dy directly as a velocity impulse measurement
        z = np.array([self.x[0] + dx, self.x[1] + dy], dtype=float)

        H = self.H_abs
        R = self.R_pdr

        y = z - H @ self.x
        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)

        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ H) @ self.P
        self._clamp_state()

    # ── Getters ───────────────────────────────────────────────────────────────
    @property
    def position(self) -> tuple[float, float]:
        return float(self.x[0]), float(self.x[1])

    @property
    def velocity(self) -> tuple[float, float]:
        return float(self.x[2]), float(self.x[3])

    @property
    def speed_ms(self) -> float:
        return float(np.linalg.norm(self.x[2:4]))

    @property
    def position_uncertainty_m(self) -> float:
        """1-sigma position uncertainty radius in metres."""
        return float(np.sqrt(self.P[0, 0] + self.P[1, 1]))

    def state_dict(self) -> dict:
        return {
            "x": round(float(self.x[0]), 3),
            "y": round(float(self.x[1]), 3),
            "vx": round(float(self.x[2]), 3),
            "vy": round(float(self.x[3]), 3),
            "accuracy_m": round(self.position_uncertainty_m, 3),
            "speed_ms": round(self.speed_ms, 3),
        }

    def _clamp_state(self):
        """Prevent state from diverging to NaN or physically impossible values."""
        if np.any(np.isnan(self.x)) or np.any(np.isinf(self.x)):
            # Replace any NaN/inf elements — keep finite position values, zero velocity
            for i in range(4):
                if not np.isfinite(self.x[i]):
                    self.x[i] = 0.0
            # Reset covariance to high uncertainty
            self.P = np.diag([4.0, 4.0, 1.0, 1.0])
        # Also sanitise P if it went bad
        if np.any(np.isnan(self.P)) or np.any(np.isinf(self.P)):
            self.P = np.diag([4.0, 4.0, 1.0, 1.0])
