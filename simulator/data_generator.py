import math
import random
from typing import Dict, List, Optional
from common.message_schema import MeterReading, utc_iso_now


class SmartMeterDataGenerator:
    """Generates realistic telemetry for individual or groups of smart meters."""

    def __init__(self, meter_id: str, seed: Optional[int] = None):
        self.meter_id = meter_id
        self.rng = random.Random(seed if seed is not None else random.randint(0, 1000000))
        
        # Meter-specific baseline characteristics
        self.base_voltage = 230.0 + self.rng.uniform(-3.0, 3.0)
        self.base_current = self.rng.uniform(1.5, 6.0)
        self.energy_accumulated = self.rng.uniform(10.0, 50.0)
        self.sequence = 0
        self.phase_offset = self.rng.uniform(0, 2 * math.pi)

    def generate_reading(
        self,
        time_step: int = 0,
        interval_seconds: float = 1.0,
        timestamp: Optional[str] = None,
    ) -> MeterReading:
        """Generates the next plausible normal telemetry reading."""
        self.sequence += 1
        ts = timestamp or utc_iso_now()

        # Diurnal / cyclic variation to simulate changing daily household demand
        daily_factor = 1.0 + 0.25 * math.sin((time_step * interval_seconds / 3600.0) + self.phase_offset)

        # Realistic normal Gaussian variations around nominal grid parameters
        voltage = round(self.base_voltage + self.rng.gauss(0.0, 1.2), 2)
        # Keep voltage within standard regulatory range (207V - 253V)
        voltage = max(210.0, min(250.0, voltage))

        current = round(max(0.2, (self.base_current * daily_factor) + self.rng.gauss(0.0, 0.25)), 2)
        
        # Active power in kW (P = V * I / 1000 with realistic power factor ~0.95)
        power_factor = self.rng.uniform(0.92, 0.98)
        power_kw = round(max(0.05, (voltage * current * power_factor) / 1000.0), 3)

        # Frequency in Hz (Nominal 50Hz, European standard grid ±0.2Hz tolerance)
        frequency = round(50.0 + self.rng.gauss(0.0, 0.04), 2)

        # Energy accumulated in kWh
        energy_delta = (power_kw * interval_seconds) / 3600.0
        self.energy_accumulated += energy_delta
        energy_kwh = round(self.energy_accumulated, 4)

        return MeterReading(
            meter_id=self.meter_id,
            timestamp=ts,
            sequence=self.sequence,
            voltage=voltage,
            current=current,
            power_kw=power_kw,
            energy_kwh=energy_kwh,
            frequency_hz=frequency,
            ground_truth_anomaly=False,
            ground_truth_type=None,
        )


def create_meter_fleet(num_meters: int, seed: Optional[int] = 42) -> List[SmartMeterDataGenerator]:
    """Factory helper to create a deterministic fleet of smart meters."""
    rng = random.Random(seed)
    fleet = []
    for i in range(1, num_meters + 1):
        meter_id = f"meter_{i:03d}"
        meter_seed = rng.randint(1, 10000000)
        fleet.append(SmartMeterDataGenerator(meter_id=meter_id, seed=meter_seed))
    return fleet
