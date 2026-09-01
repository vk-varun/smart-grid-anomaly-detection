import pytest
from cloud.baseline_detector import CloudBaselineDetector
from common.message_schema import MeterReading


def test_baseline_detector_normal_readings():
    detector = CloudBaselineDetector(zscore_threshold=3.0, rolling_window_size=10, min_samples=5)
    
    # Send normal consecutive readings for meter_001
    for step in range(15):
        reading = MeterReading(
            meter_id="meter_001",
            sequence=step + 1,
            voltage=230.0 + (step % 2) * 0.5,
            current=3.0,
            power_kw=0.69,
            energy_kwh=10.0 + step * 0.01,
            frequency_hz=50.0,
        )
        res = detector.process_reading(reading)
        # Normal steady state readings should not trigger anomaly
        assert res is None


def test_baseline_detector_anomaly_trigger():
    detector = CloudBaselineDetector(zscore_threshold=3.0, rolling_window_size=10, min_samples=5)
    
    # Warm up detector with normal readings
    for step in range(10):
        detector.process_reading(
            MeterReading(
                meter_id="meter_001",
                sequence=step + 1,
                voltage=230.0,
                current=3.0,
                power_kw=0.69,
                energy_kwh=1.0,
                frequency_hz=50.0,
            )
        )

    # Injected extreme spike reading
    spike_reading = MeterReading(
        meter_id="meter_001",
        sequence=11,
        voltage=230.0,
        current=3.0,
        power_kw=5.50,  # Huge spike relative to ~0.69 kW baseline
        energy_kwh=1.1,
        frequency_hz=50.0,
    )
    result = detector.process_reading(spike_reading)
    assert result is not None
    assert result.detected is True
    assert result.meter_id == "meter_001"
    assert result.detection_layer == "cloud_baseline"
