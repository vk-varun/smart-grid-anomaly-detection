import pytest
from common.message_schema import MeterReading
from simulator.data_generator import SmartMeterDataGenerator, create_meter_fleet


def test_smart_meter_data_ranges():
    """Verifies that generated telemetry values stay within expected physical smart grid bounds."""
    gen = SmartMeterDataGenerator(meter_id="meter_001", seed=12345)
    for step in range(50):
        reading = gen.generate_reading(time_step=step, interval_seconds=1.0)
        assert isinstance(reading, MeterReading)
        assert reading.meter_id == "meter_001"
        assert reading.sequence == step + 1
        assert 200.0 <= reading.voltage <= 260.0
        assert 0.1 <= reading.current <= 25.0
        assert 0.01 <= reading.power_kw <= 15.0
        assert 49.0 <= reading.frequency_hz <= 51.0
        assert reading.energy_kwh >= 0.0
        assert reading.ground_truth_anomaly is False
        assert reading.ground_truth_type is None


def test_deterministic_seed_reproducibility():
    """Verifies that identical seeds produce identical reading sequences."""
    gen1 = SmartMeterDataGenerator(meter_id="meter_001", seed=42)
    gen2 = SmartMeterDataGenerator(meter_id="meter_001", seed=42)

    readings1 = [gen1.generate_reading(step, 1.0) for step in range(20)]
    readings2 = [gen2.generate_reading(step, 1.0) for step in range(20)]

    for r1, r2 in zip(readings1, readings2):
        assert r1.voltage == r2.voltage
        assert r1.current == r2.current
        assert r1.power_kw == r2.power_kw
        assert r1.frequency_hz == r2.frequency_hz
        assert r1.energy_kwh == r2.energy_kwh


def test_create_meter_fleet():
    """Verifies fleet factory creates correct number of uniquely identified meters."""
    fleet = create_meter_fleet(num_meters=15, seed=99)
    assert len(fleet) == 15
    meter_ids = [m.meter_id for m in fleet]
    assert len(set(meter_ids)) == 15
    assert "meter_001" in meter_ids
    assert "meter_015" in meter_ids
