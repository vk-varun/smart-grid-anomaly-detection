import pytest
from common.message_schema import MeterReading
from edge.detector import EdgeZScoreDetector
from edge.filter import EdgeDataFilter
from edge.edge_node import EdgeNode


def test_edge_detector_warmup_and_detection():
    detector = EdgeZScoreDetector(zscore_threshold=3.0, rolling_window_size=10, min_samples=5)
    
    # 5 warmup samples
    for i in range(5):
        res = detector.process(
            MeterReading(meter_id="m1", sequence=i+1, voltage=230.0, current=3.0, power_kw=0.69, energy_kwh=1.0, frequency_hz=50.0)
        )
        assert res is None  # warmup

    # Normal sample
    normal = detector.process(
        MeterReading(meter_id="m1", sequence=6, voltage=230.0, current=3.0, power_kw=0.70, energy_kwh=1.01, frequency_hz=50.0)
    )
    assert normal is None

    # Anomaly spike
    spike = detector.process(
        MeterReading(meter_id="m1", sequence=7, voltage=230.0, current=3.0, power_kw=6.0, energy_kwh=1.02, frequency_hz=50.0)
    )
    assert spike is not None
    assert spike.detection_layer == "edge"
    assert spike.meter_id == "m1"


def test_edge_filter_aggregation():
    filter_h = EdgeDataFilter(edge_id="edge_01", aggregation_window_size=3)
    
    r1 = MeterReading(meter_id="m1", sequence=1, voltage=230.0, current=2.0, power_kw=0.46, energy_kwh=10.0, frequency_hz=50.0)
    r2 = MeterReading(meter_id="m1", sequence=2, voltage=232.0, current=2.0, power_kw=0.46, energy_kwh=10.001, frequency_hz=50.0)
    r3 = MeterReading(meter_id="m1", sequence=3, voltage=228.0, current=2.0, power_kw=0.46, energy_kwh=10.002, frequency_hz=50.0)

    assert filter_h.buffer_normal_reading(r1) is None
    assert filter_h.buffer_normal_reading(r2) is None
    agg = filter_h.buffer_normal_reading(r3)

    assert agg is not None
    assert agg.count == 3
    assert agg.avg_voltage == 230.0
    assert agg.edge_id == "edge_01"
