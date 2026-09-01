from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional
from common.message_schema import AnomalyDetectionResult, MeterReading
from common.utils import get_project_root


class DatabaseManager:
    """Manages SQLite storage for experiments, readings, detections, and metrics."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            self.db_path = get_project_root() / "data" / "database.db"
        else:
            p = Path(db_path)
            self.db_path = p if p.is_absolute() else get_project_root() / p

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Returns a configured SQLite connection."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Initializes database schema with required tables and indexes."""
        with self._lock, self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Experiments Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS experiments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT UNIQUE NOT NULL,
                    architecture TEXT NOT NULL,
                    num_meters INTEGER NOT NULL,
                    sampling_interval REAL NOT NULL,
                    duration REAL NOT NULL,
                    anomaly_rate REAL NOT NULL,
                    random_seed INTEGER NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT
                )
            """)

            # Readings Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reading_id TEXT NOT NULL,
                    experiment_id TEXT NOT NULL,
                    meter_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    voltage REAL NOT NULL,
                    current REAL NOT NULL,
                    power_kw REAL NOT NULL,
                    energy_kwh REAL NOT NULL,
                    frequency_hz REAL NOT NULL,
                    ground_truth_anomaly INTEGER NOT NULL DEFAULT 0,
                    ground_truth_type TEXT
                )
            """)

            # Detections Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    detection_id TEXT NOT NULL,
                    experiment_id TEXT NOT NULL,
                    reading_id TEXT,
                    meter_id TEXT NOT NULL,
                    detection_layer TEXT NOT NULL,
                    anomaly_type TEXT,
                    detected_at TEXT NOT NULL,
                    source_timestamp TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0
                )
            """)

            # Metrics Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    metric_value REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    component TEXT NOT NULL
                )
            """)

            # Create Indexes for Query Optimization
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_readings_exp_meter ON readings(experiment_id, meter_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON readings(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_detections_exp_meter ON detections(experiment_id, meter_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_detections_layer ON detections(detection_layer)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_metrics_exp ON metrics(experiment_id)")
            conn.commit()

    def record_experiment_start(
        self,
        experiment_id: str,
        architecture: str,
        num_meters: int,
        sampling_interval: float,
        duration: float,
        anomaly_rate: float,
        random_seed: int,
        start_time: Optional[str] = None,
    ):
        """Inserts a new experiment record."""
        st = start_time or datetime.now(timezone.utc).isoformat()
        with self._lock, self.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO experiments 
                (experiment_id, architecture, num_meters, sampling_interval, duration, anomaly_rate, random_seed, start_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (experiment_id, architecture, num_meters, sampling_interval, duration, anomaly_rate, random_seed, st),
            )
            conn.commit()

    def record_experiment_end(self, experiment_id: str, end_time: Optional[str] = None):
        """Updates experiment record with end timestamp."""
        et = end_time or datetime.now(timezone.utc).isoformat()
        with self._lock, self.get_connection() as conn:
            conn.execute(
                "UPDATE experiments SET end_time = ? WHERE experiment_id = ?",
                (et, experiment_id),
            )
            conn.commit()

    def insert_reading(self, reading: MeterReading, experiment_id: str):
        """Inserts a single meter reading."""
        with self._lock, self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO readings 
                (reading_id, experiment_id, meter_id, timestamp, voltage, current, power_kw, energy_kwh, frequency_hz, ground_truth_anomaly, ground_truth_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reading.reading_id,
                    experiment_id,
                    reading.meter_id,
                    reading.timestamp,
                    reading.voltage,
                    reading.current,
                    reading.power_kw,
                    reading.energy_kwh,
                    reading.frequency_hz,
                    1 if reading.ground_truth_anomaly else 0,
                    reading.ground_truth_type,
                ),
            )
            conn.commit()

    def insert_readings_batch(self, readings: List[MeterReading], experiment_id: str):
        """Batch inserts multiple meter readings."""
        if not readings:
            return
        rows = [
            (
                r.reading_id,
                experiment_id,
                r.meter_id,
                r.timestamp,
                r.voltage,
                r.current,
                r.power_kw,
                r.energy_kwh,
                r.frequency_hz,
                1 if r.ground_truth_anomaly else 0,
                r.ground_truth_type,
            )
            for r in readings
        ]
        with self._lock, self.get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO readings 
                (reading_id, experiment_id, meter_id, timestamp, voltage, current, power_kw, energy_kwh, frequency_hz, ground_truth_anomaly, ground_truth_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()

    def insert_detection(self, detection: AnomalyDetectionResult):
        """Inserts an anomaly detection result."""
        with self._lock, self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO detections 
                (detection_id, experiment_id, reading_id, meter_id, detection_layer, anomaly_type, detected_at, source_timestamp, latency_ms, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    detection.detection_id,
                    detection.experiment_id,
                    detection.reading_id,
                    detection.meter_id,
                    detection.detection_layer,
                    detection.anomaly_type,
                    detection.detected_at,
                    detection.source_timestamp,
                    detection.latency_ms,
                    detection.confidence,
                ),
            )
            conn.commit()

    def insert_detections_batch(self, detections: List[AnomalyDetectionResult]):
        """Batch inserts anomaly detections."""
        if not detections:
            return
        rows = [
            (
                d.detection_id,
                d.experiment_id,
                d.reading_id,
                d.meter_id,
                d.detection_layer,
                d.anomaly_type,
                d.detected_at,
                d.source_timestamp,
                d.latency_ms,
                d.confidence,
            )
            for d in detections
        ]
        with self._lock, self.get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO detections 
                (detection_id, experiment_id, reading_id, meter_id, detection_layer, anomaly_type, detected_at, source_timestamp, latency_ms, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()

    def insert_metric(self, experiment_id: str, metric_name: str, metric_value: float, component: str, timestamp: Optional[str] = None):
        """Records an evaluation or resource metric."""
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        with self._lock, self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO metrics (experiment_id, metric_name, metric_value, timestamp, component)
                VALUES (?, ?, ?, ?, ?)
                """,
                (experiment_id, metric_name, metric_value, ts, component),
            )
            conn.commit()

    def clear_experiment(self, experiment_id: str):
        """Cleans up data for a specific experiment."""
        with self._lock, self.get_connection() as conn:
            conn.execute("DELETE FROM readings WHERE experiment_id = ?", (experiment_id,))
            conn.execute("DELETE FROM detections WHERE experiment_id = ?", (experiment_id,))
            conn.execute("DELETE FROM metrics WHERE experiment_id = ?", (experiment_id,))
            conn.execute("DELETE FROM experiments WHERE experiment_id = ?", (experiment_id,))
            conn.commit()

    def reset_all_data(self):
        """Clears all tables while preserving schema."""
        with self._lock, self.get_connection() as conn:
            conn.execute("DELETE FROM readings")
            conn.execute("DELETE FROM detections")
            conn.execute("DELETE FROM metrics")
            conn.execute("DELETE FROM experiments")
            conn.commit()
