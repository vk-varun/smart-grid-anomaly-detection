import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
from pydantic import BaseModel

from cloud.database import DatabaseManager
from common.utils import get_project_root, load_config


app = FastAPI(
    title="Smart Grid Edge-Fog-Cloud Monitoring API",
    description="Backend API for Smart Grid Distributed Anomaly Detection Prototype",
    version="1.0.0",
)

# Enable CORS for local dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

root = get_project_root()
db = DatabaseManager()
dashboard_dir = root / "dashboard"
results_dir = root / "experiments" / "results"


@app.get("/api/health")
def get_health() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "database": "connected" if db.db_path.exists() else "uninitialized",
        "results_dir": str(results_dir),
    }


@app.get("/api/summary")
def get_system_summary() -> Dict[str, Any]:
    """Provides high-level monitoring summary metrics."""
    with db.get_connection() as conn:
        total_readings = conn.execute("SELECT COUNT(*) as cnt FROM readings").fetchone()["cnt"]
        total_detections = conn.execute("SELECT COUNT(*) as cnt FROM detections").fetchone()["cnt"]
        total_experiments = conn.execute("SELECT COUNT(*) as cnt FROM experiments").fetchone()["cnt"]
        avg_latency_row = conn.execute("SELECT AVG(latency_ms) as avg_lat FROM detections").fetchone()
        avg_latency = avg_latency_row["avg_lat"] if avg_latency_row and avg_latency_row["avg_lat"] else 0.0

    # Load latest bandwidth reduction if available
    bw_file = results_dir / "bandwidth_results.csv"
    bw_reduction = 0.0
    msg_reduction = 0.0
    if bw_file.exists():
        try:
            bw_df = pd.read_csv(bw_file)
            if not bw_df.empty:
                bw_reduction = float(bw_df.iloc[-1]["bandwidth_reduction_percent"])
                msg_reduction = float(bw_df.iloc[-1]["message_reduction_percent"])
        except Exception:
            pass

    return {
        "total_readings": total_readings,
        "total_detections": total_detections,
        "total_experiments": total_experiments,
        "avg_detection_latency_ms": round(float(avg_latency), 2),
        "bandwidth_reduction_percent": round(bw_reduction, 2),
        "message_reduction_percent": round(msg_reduction, 2),
    }


@app.get("/api/readings/recent")
def get_recent_readings(limit: int = Query(25, ge=1, le=100)) -> List[Dict[str, Any]]:
    """Fetches most recent telemetry readings."""
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT reading_id, experiment_id, meter_id, timestamp, voltage, current, power_kw, energy_kwh, frequency_hz, ground_truth_anomaly, ground_truth_type
            FROM readings
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/anomalies")
def get_recent_anomalies(limit: int = Query(25, ge=1, le=100)) -> List[Dict[str, Any]]:
    """Fetches recently detected anomalies across all layers."""
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT detection_id, experiment_id, reading_id, meter_id, detection_layer, anomaly_type, detected_at, source_timestamp, latency_ms, confidence
            FROM detections
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/experiments")
def get_all_experiments() -> List[Dict[str, Any]]:
    """Lists all executed experiments from database and CSV."""
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT experiment_id, architecture, num_meters, sampling_interval, duration, anomaly_rate, random_seed, start_time, end_time
            FROM experiments
            ORDER BY id DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/experiments/comparison/latest")
def get_latest_comparison() -> Dict[str, Any]:
    """Returns comparative summary from the latest experiment run."""
    summary_file = results_dir / "experiment_summary.csv"
    if not summary_file.exists():
        return {"status": "no_results_yet"}
    
    try:
        df = pd.read_csv(summary_file)
        if len(df) < 2:
            return {"status": "insufficient_runs"}
        
        latest_two = df.tail(2).to_dict(orient="records")
        return {
            "status": "success",
            "runs": latest_two,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# Serve Dashboard Static Files
if dashboard_dir.exists():
    app.mount("/static", StaticFiles(directory=str(dashboard_dir)), name="static")

    @app.get("/")
    def serve_dashboard():
        return FileResponse(str(dashboard_dir / "index.html"))
