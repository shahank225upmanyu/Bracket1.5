"""
api/routes.py — REST API endpoints (HTTP, not WebSocket).

Used for:
  POST /survey    — submit a survey point (RSSI + known coordinates)
  GET  /map       — retrieve current radio map stats
  POST /config    — update anchor positions or calibration params at runtime
  GET  /status    — health check + connected clients
  POST /watchdog/retrain — force watchdog model retrain
  DELETE /survey  — clear radio map (start over)
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional
from core.fingerprint import FingerprintDB
from ml.watchdog import SecurityWatchdog
from utils.logger import get_logger

log = get_logger("api")
router = APIRouter()

# These are injected by main.py via dependency overrides
_db: FingerprintDB = None
_watchdog: SecurityWatchdog = None


def get_db() -> FingerprintDB:
    return _db

def get_watchdog() -> SecurityWatchdog:
    return _watchdog


# ── Survey endpoint ───────────────────────────────────────────────────────────
class SurveyPoint(BaseModel):
    x: float = Field(..., description="X coordinate in metres")
    y: float = Field(..., description="Y coordinate in metres")
    rssi_samples: dict[str, list[int]] = Field(
        ..., description="{anchor_id: [rssi1, rssi2, ...]} — min 10 samples per anchor"
    )
    mag_samples: Optional[list[list[float]]] = Field(
        None, description="[[bx,by,bz], ...] magnetometer samples"
    )


@router.post("/survey", summary="Add a reference point to the radio map")
def add_survey_point(point: SurveyPoint, db: FingerprintDB = Depends(get_db)):
    for anchor_id, samples in point.rssi_samples.items():
        if len(samples) < 5:
            raise HTTPException(400, f"Need ≥5 samples for anchor {anchor_id}, got {len(samples)}")
    db.add_survey_point(point.x, point.y, point.rssi_samples, point.mag_samples)
    log.info(f"Survey point added at ({point.x}, {point.y}) — DB now has {db.size} RPs")
    return {"status": "ok", "db_size": db.size, "x": point.x, "y": point.y}


@router.get("/map", summary="Get radio map statistics")
def get_map(db: FingerprintDB = Depends(get_db)):
    return {
        "reference_points": db.size,
        "points": [
            {"x": rp.x, "y": rp.y, "anchors": list(rp.rssi_mean.keys()), "samples": rp.n_samples}
            for rp in db.reference_points
        ]
    }


@router.delete("/survey", summary="Clear all survey data")
def clear_survey(db: FingerprintDB = Depends(get_db)):
    db.clear()
    log.warning("Radio map cleared by API request")
    return {"status": "cleared"}


# ── Status endpoint ───────────────────────────────────────────────────────────
@router.get("/status", summary="Server health + stats")
def status(db: FingerprintDB = Depends(get_db)):
    return {
        "status": "ok",
        "radio_map_size": db.size,
    }


# ── Watchdog retrain ──────────────────────────────────────────────────────────
@router.post("/watchdog/retrain", summary="Force watchdog anomaly model retrain")
def retrain_watchdog(wd: SecurityWatchdog = Depends(get_watchdog)):
    wd.retrain()
    return {"status": "retraining — collecting new baseline data"}


def init_routes(db: FingerprintDB, watchdog: SecurityWatchdog):
    """Called from main.py to inject dependencies."""
    global _db, _watchdog
    _db = db
    _watchdog = watchdog
