"""
tests/server/test_core.py — Unit tests for EKF, trilateration, fingerprint, and auth.

Run: pytest tests/server/ -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../server"))

import json
import math
import pytest
import numpy as np


# ── EKF tests ─────────────────────────────────────────────────────────────────
class TestEKF:
    def setup_method(self):
        from core.ekf import ExtendedKalmanFilter
        self.ekf = ExtendedKalmanFilter(initial_x=0.0, initial_y=0.0)

    def test_initial_state(self):
        assert self.ekf.position == (0.0, 0.0)
        assert self.ekf.speed_ms == 0.0

    def test_predict_moves_covariance(self):
        p_before = self.ekf.P.copy()
        self.ekf.predict(dt=0.1)
        # Prediction should increase uncertainty
        assert self.ekf.P[0, 0] >= p_before[0, 0]

    def test_update_position_converges(self):
        for _ in range(20):
            self.ekf.predict(dt=0.1)
            self.ekf.update_position(3.0, 2.0)
        x, y = self.ekf.position
        assert abs(x - 3.0) < 0.5
        assert abs(y - 2.0) < 0.5

    def test_pdr_update_shifts_position(self):
        # Converge EKF to (2,2) first
        for _ in range(5):
            self.ekf.predict(dt=0.1)
            self.ekf.update_position(2.0, 2.0)
        x_before, _ = self.ekf.position
        self.ekf.predict(dt=0.1)
        self.ekf.update_pdr(0.5, 0.0)   # step east
        x_after, _ = self.ekf.position
        assert x_after > x_before, f"PDR did not shift position east: {x_before:.3f} → {x_after:.3f}"

    def test_nan_recovery(self):
        self.ekf.x[0] = float("nan")
        self.ekf.x[2] = float("inf")
        self.ekf._clamp_state()
        assert not math.isnan(self.ekf.x[0])
        assert not math.isinf(self.ekf.x[2])

    def test_uncertainty_decreases_with_measurements(self):
        acc_before = self.ekf.position_uncertainty_m
        for _ in range(10):
            self.ekf.predict(dt=0.1)
            self.ekf.update_position(1.0, 1.0)
        acc_after = self.ekf.position_uncertainty_m
        assert acc_after < acc_before


# ── Trilateration tests ───────────────────────────────────────────────────────
class TestTrilateration:
    def setup_method(self):
        from core.trilateration import trilaterate, AnchorMeasurement, rssi_to_distance
        self.trilaterate = trilaterate
        self.AnchorMeasurement = AnchorMeasurement
        self.rssi_to_distance = rssi_to_distance

    def test_rssi_to_distance_1m(self):
        # At 1m, RSSI should equal TX_POWER
        d = self.rssi_to_distance(rssi=-59, tx_power=-59, n=2.8)
        assert abs(d - 1.0) < 0.01

    def test_rssi_to_distance_increases_with_less_signal(self):
        d1 = self.rssi_to_distance(-60, -59, 2.8)
        d2 = self.rssi_to_distance(-70, -59, 2.8)
        assert d2 > d1

    def test_trilaterate_center(self):
        """Target at (2.5, 2.0) = centre of 5x4 room."""
        cx, cy = 2.5, 2.0
        anchors_pos = {"BRAKET-A": (0,0), "BRAKET-B": (5,0), "BRAKET-C": (5,4), "BRAKET-D": (0,4)}
        measurements = []
        for aid, (ax, ay) in anchors_pos.items():
            d = math.sqrt((cx-ax)**2 + (cy-ay)**2)
            rssi = int(-59 - 10 * 2.8 * math.log10(max(d, 0.1)))
            measurements.append(self.AnchorMeasurement(
                anchor_id=aid, rssi=rssi, tx_power=-59, dist_m=d
            ))
        result = self.trilaterate(measurements, rssi_state={})
        assert result is not None
        assert abs(result.x - cx) < 1.0
        assert abs(result.y - cy) < 1.0

    def test_insufficient_anchors_returns_none(self):
        meas = [self.AnchorMeasurement("BRAKET-A", -65, -59, 2.0),
                self.AnchorMeasurement("BRAKET-B", -70, -59, 3.0)]
        result = self.trilaterate(meas, {}, min_anchors=3)
        assert result is None


# ── Fingerprint tests ─────────────────────────────────────────────────────────
class TestFingerprint:
    def setup_method(self, tmp_path_fixture=None):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        from core.fingerprint import FingerprintDB
        self.db = FingerprintDB(db_path=os.path.join(self.tmp, "test_map.json"))

    def test_empty_db_returns_none(self):
        result = self.db.match({"BRAKET-A": -65})
        assert result is None

    def test_add_and_match_single_point(self):
        self.db.add_survey_point(
            x=1.0, y=1.0,
            rssi_samples={"BRAKET-A": [-65, -64, -66], "BRAKET-B": [-75, -74, -76]}
        )
        result = self.db.match({"BRAKET-A": -65.0, "BRAKET-B": -75.0})
        assert result is not None
        assert abs(result.x - 1.0) < 0.5

    def test_match_selects_nearest_point(self):
        self.db.add_survey_point(1.0, 1.0, {"BRAKET-A": [-60]*10, "BRAKET-B": [-80]*10})
        self.db.add_survey_point(4.0, 3.0, {"BRAKET-A": [-80]*10, "BRAKET-B": [-60]*10})
        # Near anchor A → should match first point
        result = self.db.match({"BRAKET-A": -61.0, "BRAKET-B": -79.0})
        assert result is not None
        assert abs(result.x - 1.0) < 1.5

    def test_persistence(self):
        self.db.add_survey_point(2.0, 3.0, {"BRAKET-A": [-70]*5})
        from core.fingerprint import FingerprintDB
        db2 = FingerprintDB(db_path=os.path.join(self.tmp, "test_map.json"))
        assert db2.size == 1


# ── Auth tests ────────────────────────────────────────────────────────────────
class TestAuth:
    def setup_method(self):
        from utils.auth import verify_packet, _sign
        self._sign = _sign
        self.verify = verify_packet

    def test_valid_signature_accepted(self):
        import json
        payload = {"ts": 1234567890, "device_id": "test", "anchors": []}
        payload_str = json.dumps(payload, separators=(",", ":"))
        sig = self._sign(payload_str)
        payload["sig"] = sig
        ok, data = self.verify(json.dumps(payload))
        assert ok
        assert data["device_id"] == "test"

    def test_tampered_payload_rejected(self):
        import json
        payload = {"ts": 1234567890, "device_id": "test"}
        payload_str = json.dumps(payload, separators=(",", ":"))
        sig = self._sign(payload_str)
        payload["device_id"] = "attacker"   # tamper after signing
        payload["sig"] = sig
        ok, _ = self.verify(json.dumps(payload))
        assert not ok

    def test_missing_sig_rejected(self):
        ok, _ = self.verify('{"ts": 123, "device_id": "x"}')
        assert not ok

    def test_malformed_json_rejected(self):
        ok, _ = self.verify("not json at all")
        assert not ok


# ── Watchdog tests ────────────────────────────────────────────────────────────
class TestWatchdog:
    def setup_method(self):
        import tempfile, os
        self.tmp = tempfile.mkdtemp()
        os.environ["BRAKET_SECRET"] = "test-secret"
        # Patch model path to tmp
        import utils.config as cfg
        cfg.ANOMALY_MODEL_PATH = os.path.join(self.tmp, "model.pkl")
        from ml.watchdog import SecurityWatchdog
        self.wd = SecurityWatchdog()

    def test_first_packet_accepted(self):
        result = self.wd.check(1.0, 1.0, [{"id": "BRAKET-A", "rssi": -65}])
        assert result.accepted

    def test_teleport_rejected(self):
        self.wd.check(0.0, 0.0, [])
        import time; time.sleep(0.01)
        # 50 m in 10 ms = 5000 m/s — clearly impossible
        result = self.wd.check(50.0, 50.0, [])
        assert not result.accepted
        assert result.reason == "velocity_gate"

    def test_normal_walk_accepted(self):
        import time
        self.wd.check(0.0, 0.0, [])
        time.sleep(0.5)
        # 0.5 m in 0.5 s = 1.0 m/s — normal walking pace
        result = self.wd.check(0.5, 0.0, [])
        assert result.accepted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
