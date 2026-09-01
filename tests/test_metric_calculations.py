import pytest
from common.message_schema import AnomalyDetectionResult, MeterReading
from common.metrics import MetricsCalculator


def test_perfect_classification():
    r1 = MeterReading(meter_id="m1", sequence=1, voltage=230, current=3, power_kw=0.7, energy_kwh=1, frequency_hz=50, ground_truth_anomaly=True, ground_truth_type="point")
    r2 = MeterReading(meter_id="m2", sequence=1, voltage=230, current=3, power_kw=0.7, energy_kwh=1, frequency_hz=50, ground_truth_anomaly=False)
    
    d1 = AnomalyDetectionResult(experiment_id="e1", reading_id=r1.reading_id, meter_id="m1", detection_layer="edge", detected=True, source_timestamp=r1.timestamp, latency_ms=10.0)
    
    metrics = MetricsCalculator.calculate_classification_metrics([r1, r2], [d1])
    assert metrics["true_positives"] == 1
    assert metrics["false_positives"] == 0
    assert metrics["true_negatives"] == 1
    assert metrics["false_negatives"] == 0
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1_score"] == 1.0


def test_latency_statistics():
    latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    stats = MetricsCalculator.calculate_latency_stats(latencies)
    assert stats["latency_mean_ms"] == 55.0
    assert stats["latency_median_ms"] == 55.0
    assert stats["latency_min_ms"] == 10.0
    assert stats["latency_max_ms"] == 100.0
    assert stats["latency_p95_ms"] > 90.0


def test_bandwidth_reduction():
    cloud_bytes = 100000
    dist_bytes = 25000
    cloud_msgs = 1000
    dist_msgs = 300
    res = MetricsCalculator.calculate_bandwidth_reduction(cloud_bytes, dist_bytes, cloud_msgs, dist_msgs)
    assert res["bandwidth_reduction_percent"] == 75.0
    assert res["message_reduction_percent"] == 70.0
