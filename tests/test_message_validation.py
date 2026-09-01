import pytest
from common.message_schema import (
    AggregatedReading,
    AnomalyDetectionResult,
    EdgeForwardPayload,
    FogForwardPayload,
    MeterReading,
)


def test_meter_reading_serialization():
    reading = MeterReading(
        meter_id="meter_005",
        sequence=1,
        voltage=231.5,
        current=4.2,
        power_kw=0.97,
        energy_kwh=12.45,
        frequency_hz=50.01,
        ground_truth_anomaly=False,
    )
    raw_json = reading.model_dump_json()
    assert "meter_005" in raw_json
    assert reading.payload_bytes() > 0

    reconstructed = MeterReading.model_validate_json(raw_json)
    assert reconstructed.meter_id == reading.meter_id
    assert reconstructed.voltage == reading.voltage
    assert reconstructed.reading_id == reading.reading_id


def test_anomaly_detection_result_schema():
    det = AnomalyDetectionResult(
        experiment_id="exp_test_01",
        reading_id="test-uuid",
        meter_id="meter_001",
        detection_layer="edge",
        anomaly_type="point",
        detected=True,
        source_timestamp="2026-08-31T20:00:00Z",
        latency_ms=15.4,
        confidence=0.95,
    )
    json_str = det.model_dump_json()
    reconstructed = AnomalyDetectionResult.model_validate_json(json_str)
    assert reconstructed.latency_ms == 15.4
    assert reconstructed.detection_layer == "edge"


def test_edge_forward_payload_schema():
    reading = MeterReading(
        meter_id="meter_001",
        sequence=10,
        voltage=240.0,
        current=3.0,
        power_kw=0.72,
        energy_kwh=1.0,
        frequency_hz=50.0,
        ground_truth_anomaly=True,
        ground_truth_type="point",
    )
    agg = AggregatedReading(
        edge_id="edge_01",
        meter_id="meter_002",
        start_time="2026-08-31T20:00:00Z",
        end_time="2026-08-31T20:00:05Z",
        count=5,
        avg_voltage=230.1,
        avg_current=2.5,
        avg_power_kw=0.57,
        total_energy_kwh=0.005,
        avg_frequency_hz=50.0,
    )
    payload = EdgeForwardPayload(
        edge_id="edge_01",
        individual_readings=[reading],
        aggregations=[agg],
    )
    assert payload.payload_bytes() > 0
    reconstructed = EdgeForwardPayload.model_validate_json(payload.model_dump_json())
    assert len(reconstructed.individual_readings) == 1
    assert len(reconstructed.aggregations) == 1
