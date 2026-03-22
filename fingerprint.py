"""
core/fingerprint.py — RF Fingerprint Radio Map with KNN-SIPS matching.

Offline phase: build_radio_map() collects RSSI vectors at known (x,y) Reference Points.
Online phase:  match() finds the K nearest neighbours in signal space and returns
               a weighted-average position estimate.

KNN-SIPS enhancement:
  Before matching, each anchor's current RSSI is tested against its historical
  distribution. Anchors deviating > 1.5σ are flagged as potentially blocked (NLOS)
  and excluded from the distance metric. This makes the system robust to radio
  map staleness from furniture changes or door states.
"""

import json
import math
import os
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import Optional
from utils.config import ANCHOR_POSITIONS, KNN_K, FINGERPRINT_DB_PATH


@dataclass
class ReferencePoint:
    x: float
    y: float
    # RSSI vector: {anchor_id: mean_rssi}
    rssi_mean: dict[str, float] = field(default_factory=dict)
    rssi_std: dict[str, float] = field(default_factory=dict)
    # Magnetometer fingerprint
    mag_mean: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    mag_std: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    n_samples: int = 0


@dataclass
class FingerprintMatch:
    x: float
    y: float
    confidence: float       # 0–1, higher = better
    n_anchors_used: int
    k_matches: int
    mag_assisted: bool = False


class FingerprintDB:
    """
    Manages the offline radio map and performs online KNN-SIPS matching.
    Thread-safe for read (match) — writes during survey should be serialised.
    """

    def __init__(self, db_path: str = FINGERPRINT_DB_PATH):
        self.db_path = db_path
        self.reference_points: list[ReferencePoint] = []
        self._load()

    # ── Offline Survey API ────────────────────────────────────────────────────
    def add_survey_point(
        self,
        x: float,
        y: float,
        rssi_samples: dict[str, list[int]],          # {anchor_id: [rssi1, rssi2, ...]}
        mag_samples: Optional[list[list[float]]] = None   # [[bx,by,bz], ...]
    ):
        """
        Add or update a Reference Point from survey measurements.
        Calling with the same (x, y) merges samples into existing RP.
        """
        # Find existing RP within 0.3 m or create new
        existing = next(
            (rp for rp in self.reference_points
             if math.sqrt((rp.x - x)**2 + (rp.y - y)**2) < 0.3),
            None
        )
        rp = existing or ReferencePoint(x=x, y=y)
        if existing is None:
            self.reference_points.append(rp)

        # Compute statistics for each anchor
        for anchor_id, samples in rssi_samples.items():
            if not samples:
                continue
            arr = np.array(samples, dtype=float)
            rp.rssi_mean[anchor_id] = float(np.mean(arr))
            rp.rssi_std[anchor_id] = float(max(np.std(arr), 1.0))  # min std = 1 dBm

        # Magnetometer stats
        if mag_samples and len(mag_samples) > 2:
            mag_arr = np.array(mag_samples)
            rp.mag_mean = mag_arr.mean(axis=0).tolist()
            rp.mag_std = np.maximum(mag_arr.std(axis=0), 0.5).tolist()

        rp.n_samples += sum(len(s) for s in rssi_samples.values())
        self._save()

    # ── Online KNN-SIPS Matching ──────────────────────────────────────────────
    def match(
        self,
        live_rssi: dict[str, float],     # {anchor_id: current_rssi}
        live_mag: Optional[list[float]] = None,
        k: int = KNN_K
    ) -> Optional[FingerprintMatch]:
        """
        Find the K nearest RPs in signal space and return a weighted position.

        SIPS step: anchors whose live RSSI deviates > 1.5σ from their trained
        mean are excluded from the Euclidean distance computation (NLOS likely).
        """
        if not self.reference_points:
            return None

        # Determine which anchors to trust (SIPS filter)
        trusted_anchors = set()
        for anchor_id, live_val in live_rssi.items():
            rp_with_anchor = [rp for rp in self.reference_points
                              if anchor_id in rp.rssi_mean]
            if not rp_with_anchor:
                continue
            # Global mean/std across all RPs for this anchor
            all_means = [rp.rssi_mean[anchor_id] for rp in rp_with_anchor]
            global_mean = np.mean(all_means)
            global_std = max(np.std(all_means), 3.0)
            deviation = abs(live_val - global_mean)
            if deviation <= 1.5 * global_std:
                trusted_anchors.add(anchor_id)

        if len(trusted_anchors) < 2:
            # Fall back to using all anchors if too few pass SIPS
            trusted_anchors = set(live_rssi.keys())

        # Compute Euclidean distance in signal space for each RP
        distances = []
        for rp in self.reference_points:
            common = trusted_anchors & set(rp.rssi_mean.keys()) & set(live_rssi.keys())
            if len(common) < 2:
                distances.append(float("inf"))
                continue

            sq_sum = sum(
                (live_rssi[a] - rp.rssi_mean[a]) ** 2
                for a in common
            )
            # Penalise fewer anchors to prefer RPs with more signal overlap
            coverage_penalty = len(trusted_anchors) / max(len(common), 1)
            distances.append(math.sqrt(sq_sum) * coverage_penalty)

        distances = np.array(distances)

        # Take K nearest
        k_actual = min(k, len(self.reference_points))
        top_k_idx = np.argsort(distances)[:k_actual]
        top_k_dist = distances[top_k_idx]

        if top_k_dist[0] == float("inf"):
            return None

        # Weighted average: weight = 1 / (dist + ε)
        weights = 1.0 / (top_k_dist + 0.01)
        total_w = weights.sum()
        x_est = sum(weights[i] * self.reference_points[top_k_idx[i]].x
                    for i in range(k_actual)) / total_w
        y_est = sum(weights[i] * self.reference_points[top_k_idx[i]].y
                    for i in range(k_actual)) / total_w

        # Confidence: inverse of normalised min distance (0 = far match, 1 = exact)
        max_possible = 10.0 * len(trusted_anchors)
        confidence = max(0.0, 1.0 - top_k_dist[0] / max_possible)

        # Magnetometer refinement: if mag is available, re-rank K candidates
        mag_assisted = False
        if live_mag and len(live_mag) == 3:
            x_est, y_est, mag_assisted = self._refine_with_mag(
                x_est, y_est, live_mag,
                [self.reference_points[i] for i in top_k_idx],
                weights
            )

        return FingerprintMatch(
            x=round(x_est, 3),
            y=round(y_est, 3),
            confidence=round(confidence, 3),
            n_anchors_used=len(trusted_anchors),
            k_matches=k_actual,
            mag_assisted=mag_assisted
        )

    def _refine_with_mag(
        self,
        x0: float, y0: float,
        live_mag: list[float],
        candidates: list[ReferencePoint],
        weights: np.ndarray
    ) -> tuple[float, float, bool]:
        """Re-weight candidates using magnetometer distance."""
        live = np.array(live_mag)
        mag_weights = []
        for rp in candidates:
            if not rp.mag_mean or all(v == 0 for v in rp.mag_mean):
                mag_weights.append(1.0)
                continue
            mean = np.array(rp.mag_mean)
            std = np.array(rp.mag_std)
            # Mahalanobis-like distance in mag space
            diff = np.abs(live - mean) / std
            mag_dist = float(np.linalg.norm(diff))
            mag_weights.append(1.0 / (mag_dist + 0.1))

        combined = weights * np.array(mag_weights)
        total = combined.sum()
        if total < 1e-9:
            return x0, y0, False

        x = sum(combined[i] * candidates[i].x for i in range(len(candidates))) / total
        y = sum(combined[i] * candidates[i].y for i in range(len(candidates))) / total
        return round(x, 3), round(y, 3), True

    # ── Persistence ───────────────────────────────────────────────────────────
    def _save(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        data = [asdict(rp) for rp in self.reference_points]
        with open(self.db_path, "w") as f:
            json.dump(data, f, indent=2)

    def _load(self):
        if not os.path.exists(self.db_path):
            return
        try:
            with open(self.db_path) as f:
                data = json.load(f)
            self.reference_points = [ReferencePoint(**d) for d in data]
        except Exception as e:
            print(f"[FingerprintDB] Load error: {e}")

    @property
    def size(self) -> int:
        return len(self.reference_points)

    def clear(self):
        self.reference_points = []
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
