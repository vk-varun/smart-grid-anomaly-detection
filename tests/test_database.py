import os
from pathlib import Path
import pytest
from cloud.database import DatabaseManager
from common.message_schema import AnomalyDetectionResult, MeterReading


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_db.sqlite"
    return DatabaseManager(str(db_file))


def test_database_experiment_lifecycle(temp_db):
    exp_id = "exp_test_001"
    temp_db.record_experiment_start(
        experiment_id=exp_id,
        architecture="cloud_baseline",
        num_meters=10,
        sampling_interval=1.0,
        duration=30.0,
        anomaly_rate=0.05,
        random_seed=42,
    )

    with temp_db.get_connection() as conn:
        row = conn.execute("SELECT * FROM experiments WHERE experiment_id = ?", (exp_id,)).fetchone()
        assert row is not None
        assert row["architecture"] == "cloud_baseline"
        assert row["num_meters"] == 10
        assert row["end_time"] is None

    temp_db.record_experiment_end(exp_id)
    with temp_db.get_connection() as conn:
        row = conn.execute("SELECT end_time FROM experiments WHERE experiment_id = ?", (exp_id,)).fetchone()
        assert row["end_time"] is not None


def test_database_insert_reading_and_detection(temp_db):
    exp_id = "exp_test_002"
    reading = MeterReading(
        meter_id="meter_001",
        sequence=1,
        voltage=230.5,
        current=3.5,
        power_kw=0.8,
        energy_kwh=10.0,
        frequency_hz=50.0,
        ground_truth_anomaly=True,
        ground_truth_type="point",
    )
    temp_db.insert_reading(reading, exp_id)

    detection = AnomalyDetectionResult(
        experiment_id=exp_id,
        reading_id=reading.reading_id,
        meter_id=reading.meter_id,
        detection_layer="cloud_baseline",
        anomaly_type="point",
        detected=True,
        source_timestamp=reading.timestamp,
        latency_ms=12.5,
        confidence=0.9,
    )
    temp_db.insert_detection(detection)

    with temp_db.get_connection() as conn:
        r_row = conn.execute("SELECT * FROM readings WHERE reading_id = ?", (reading.reading_id,)).fetchone()
        assert r_row is not None
        assert r_row["voltage"] == 230.5
        assert r_row["ground_truth_anomaly"] == 1

        d_row = conn.execute("SELECT * FROM detections WHERE detection_id = ?", (detection.detection_id,)).fetchone()
        assert d_row is not None
        assert d_row["latency_ms"] == 12.5
        assert d_row["detection_layer"] == "cloud_baseline"
