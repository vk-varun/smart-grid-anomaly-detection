import pytest
from common.message_schema import MeterReading
from simulator.anomaly_generator import AnomalyGenerator
from simulator.data_generator import SmartMeterDataGenerator


def test_anomaly_injection_and_ground_truth():
    """Verifies that injected anomalies correctly mark ground truth flags and types."""
    gen = SmartMeterDataGenerator(meter_id="meter_001", seed=10)
    anomaly_gen = AnomalyGenerator(anomaly_rate=1.0, seed=10)  # 100% anomaly injection for test

    anomalies_detected = 0
    types_seen = set()

    for step in range(30):
        normal_reading = gen.generate_reading(time_step=step, interval_seconds=1.0)
        processed_reading = anomaly_gen.process_reading(normal_reading)
        
        assert processed_reading.ground_truth_anomaly is True
        assert processed_reading.ground_truth_type in {"point", "contextual", "collective"}
        types_seen.add(processed_reading.ground_truth_type)
        anomalies_detected += 1

    assert anomalies_detected == 30
    assert len(types_seen) > 0


def test_collective_anomaly_continuity():
    """Verifies that collective anomalies persist across multiple consecutive steps."""
    anomaly_gen = AnomalyGenerator(
        anomaly_rate=1.0,
        point_prob=0.0,
        contextual_prob=0.0,
        collective_prob=1.0,
        seed=42,
    )
    gen = SmartMeterDataGenerator(meter_id="meter_002", seed=42)

    # First reading initiates a collective sequence
    r0 = anomaly_gen.process_reading(gen.generate_reading(0, 1.0))
    assert r0.ground_truth_anomaly is True
    assert r0.ground_truth_type == "collective"
    assert "meter_002" in anomaly_gen.active_collective_anomalies

    remaining = anomaly_gen.active_collective_anomalies["meter_002"]["remaining_steps"]
    assert remaining >= 4
