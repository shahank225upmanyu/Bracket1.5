"""
core/trilateration.py — Weighted Least Squares trilateration with NLOS rejection and GDOP.

Given N anchors at known positions with estimated distances, computes (x, y)
using WLS. Anchors whose signals are statistically anomalous (NLOS candidates)
are down-weighted before solving.
"""

import math
import numpy as np
from dataclasses import dataclass
from utils.config import (
    ANCHOR_POSITIONS,
    DEFAULT_TX_POWER_DBM,
    PATH_LOSS_EXPONENT,
)


@dataclass
class AnchorMeasurement:
    anchor_id: str
    rssi: int           # dBm
    tx_power: int       # dBm (from advertisement packet)
    dist_m: float       # pre-computed distance estimate


@dataclass
class TrilaterationResult:
    x: float
    y: float
    gdop: float         # Geometric Dilution of Precision (lower = better)
    n_anchors: int
    noise_scale: float  # suggests EKF measurement noise scaling


def rssi_to_distance(rssi: int, tx_power: int = DEFAULT_TX_POWER_DBM,
                     n: float = PATH_LOSS_EXPONENT) -> float:
    """Log-distance path loss model: d = 10^((tx_power - rssi) / (10*n))"""
    if rssi == 0:
        return 0.0
    return math.pow(10.0, (tx_power - rssi) / (10.0 * n))


def _kalman_smooth_rssi(rssi: int, state: dict, anchor_id: str) -> int:
    """
    Per-anchor scalar Kalman filter on raw RSSI.
    state is a mutable dict shared across calls (persistent per session).
    """
    if anchor_id not in state:
        state[anchor_id] = {"estimate": float(rssi), "error": 4.0}

    est, err = state[anchor_id]["estimate"], state[anchor_id]["error"]
    process_noise = 1.0
    meas_noise = 3.0
    gain = (err + process_noise) / (err + process_noise + meas_noise)
    new_est = est + gain * (rssi - est)
    new_err = (1 - gain) * (err + process_noise)
    state[anchor_id] = {"estimate": new_est, "error": new_err}
    return int(round(new_est))


def compute_gdop(positions: list[tuple[float, float]]) -> float:
    """
    Geometric Dilution of Precision.
    GDOP < 2.0 = excellent, 2–4 = good, >6 = poor geometry.
    Returns float('inf') if degenerate.
    """
    if len(positions) < 2:
        return float("inf")
    try:
        # H matrix: unit vectors from each anchor to centroid
        cx = sum(p[0] for p in positions) / len(positions)
        cy = sum(p[1] for p in positions) / len(positions)
        H = []
        for px, py in positions:
            d = math.sqrt((px - cx) ** 2 + (py - cy) ** 2)
            if d < 0.01:
                continue
            H.append([(px - cx) / d, (py - cy) / d])
        H = np.array(H, dtype=float)
        if H.shape[0] < 2:
            return float("inf")
        HtH_inv = np.linalg.inv(H.T @ H)
        return float(math.sqrt(np.trace(HtH_inv)))
    except np.linalg.LinAlgError:
        return float("inf")


def trilaterate(
    measurements: list[AnchorMeasurement],
    rssi_state: dict,
    min_anchors: int = 3
) -> TrilaterationResult | None:
    """
    Main trilateration function.

    Steps:
    1. Filter to known anchors only
    2. RSSI smoothing (per-anchor Kalman)
    3. NLOS rejection: down-weight anchors whose distance is an outlier
    4. Weighted Least Squares solve
    5. GDOP calculation
    """
    known = [m for m in measurements if m.anchor_id in ANCHOR_POSITIONS]
    if len(known) < min_anchors:
        return None

    # Smooth RSSI and recompute distances
    anchors = []
    for m in known:
        smooth_rssi = _kalman_smooth_rssi(m.rssi, rssi_state, m.anchor_id)
        dist = rssi_to_distance(smooth_rssi, m.tx_power)
        dist = max(0.1, min(dist, 50.0))   # clamp physically impossible values
        ax, ay = ANCHOR_POSITIONS[m.anchor_id]
        anchors.append((ax, ay, dist))

    # NLOS rejection via interquartile range on distances
    dists = [a[2] for a in anchors]
    q1, q3 = np.percentile(dists, 25), np.percentile(dists, 75)
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr

    # Weights: 1/dist² base, down-weight NLOS outliers by factor 10
    weights = []
    for ax, ay, dist in anchors:
        base_w = 1.0 / (dist ** 2 + 0.01)
        nlos_penalty = 0.1 if (dist < lo or dist > hi) else 1.0
        weights.append(base_w * nlos_penalty)
    weights = np.array(weights)

    # WLS trilateration: minimise Σ w_i [(x-xi)² + (y-yi)² - di²]²
    # Linearised: A·p = b
    if len(anchors) < 2:
        return None

    A, b = [], []
    x0, y0, d0 = anchors[0]
    w0 = weights[0]
    for i in range(1, len(anchors)):
        xi, yi, di = anchors[i]
        wi = weights[i]
        w = math.sqrt(wi * w0)
        A.append([
            w * 2 * (xi - x0),
            w * 2 * (yi - y0)
        ])
        b.append(w * (xi**2 + yi**2 - di**2 - x0**2 - y0**2 + d0**2))

    try:
        result = np.linalg.lstsq(np.array(A), np.array(b), rcond=None)
        pos = result[0]
        x, y = float(pos[0]), float(pos[1])
    except np.linalg.LinAlgError:
        return None

    gdop = compute_gdop([(ax, ay) for ax, ay, _ in anchors])
    noise_scale = max(1.0, gdop / 2.0)   # scale EKF uncertainty by GDOP

    return TrilaterationResult(
        x=round(x, 3),
        y=round(y, 3),
        gdop=round(gdop, 2),
        n_anchors=len(anchors),
        noise_scale=noise_scale
    )
