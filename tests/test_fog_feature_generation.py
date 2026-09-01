import pytest
from common.message_schema import MeterReading
from fog.aggregator import FogFeatureAggregator
from fog.detector import FogIsolationForestDetector


def test_fog_feature_aggregator():
    agg = FogFeatureAggregator(window_size=5)
    
    # 2 readings (below min 3)
    r1 = MeterReading(meter_id="m1", sequence=1, voltage=230, current=3, power_kw=0.69, energy_kwh=1, frequency_hz=50)
    r2 = MeterReading(meter_id="m1", sequence=2, voltage=231, current=3, power_kw=0.70, energy_kwh=1.01, frequency_hz=50)
    assert agg.add_reading(r1) is None
    assert agg.add_reading(r2) is None

    # 3rd reading computes feature vector of 7 elements
    r3 = MeterReading(meter_id="m1", sequence=3, voltage=229, current=3, power_kw=0.68, energy_kwh=1.02, frequency_hz=50)
    feat = agg.add_reading(r3)
    assert feat is not None
    assert len(feat) == 7
    # Check features: [voltage, current, power_kw, frequency_hz, mean_p, std_p, roc]
    assert feat[0] == 229
    assert feat[2] == 0.68


def test_fog_isolation_forest_warmup_and_detection():
    detector = FogIsolationForestDetector(contamination=0.05, min_fit_samples=10, random_state=42)
    
    # Feed 15 normal readings to train/fit IsolationForest
    for i in range(15):
        detector.process(
            MeterReading(
                meter_id="m1",
                sequence=i+1,
                voltage=230.0 + (i % 3) * 0.2,
                current=3.0,
                power_kw=0.69 + (i % 2) * 0.01,
                energy_kwh=1.0 + i * 0.01,
                frequency_hz=50.0,
            )
        )

    # An extreme outlier reading
    outlier = MeterReading(
        meter_id="m1",
        sequence=16,
        voltage=230.0,
        current=12.0,
        power_kw=8.5,
        energy_kwh=2.0,
        frequency_hz=48.2,
    )
    res = detector.process(outlier)
    assert res is not None
    assert res.detection_layer == "fog"
    assert res.meter_id == "m1"
