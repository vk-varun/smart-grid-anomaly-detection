import random
from typing import Dict, Optional
from common.message_schema import MeterReading


class AnomalyGenerator:
    """Injects controlled point, contextual, and collective anomalies into telemetry."""

    def __init__(
        self,
        anomaly_rate: float = 0.03,
        point_prob: float = 0.4,
        contextual_prob: float = 0.3,
        collective_prob: float = 0.3,
        seed: Optional[int] = 42,
    ):
        self.anomaly_rate = anomaly_rate
        self.point_prob = point_prob
        self.contextual_prob = contextual_prob
        self.collective_prob = collective_prob
        self.rng = random.Random(seed)

        # Track ongoing collective anomalies per meter:
        # meter_id -> {"remaining_steps": int, "type": str, "factor": float, "step_count": int}
        self.active_collective_anomalies: Dict[str, Dict] = {}

    def reset(self, seed: Optional[int] = None):
        """Resets the state and re-seeds the generator."""
        if seed is not None:
            self.rng = random.Random(seed)
        self.active_collective_anomalies.clear()

    def process_reading(self, reading: MeterReading) -> MeterReading:
        """Evaluates and conditionally injects an anomaly into a telemetry reading."""
        meter_id = reading.meter_id

        # 1. Check if meter is currently in an ongoing collective anomaly sequence
        if meter_id in self.active_collective_anomalies:
            state = self.active_collective_anomalies[meter_id]
            state["step_count"] += 1
            progress = state["step_count"]
            factor = state["factor"]

            # Collective gradual ramp anomaly (e.g. undetected power leakage / heating load)
            ramped_power = round(reading.power_kw * (1.0 + (factor * progress)), 3)
            ramped_current = round(reading.current * (1.0 + (factor * progress)), 2)
            
            reading.power_kw = ramped_power
            reading.current = ramped_current
            reading.ground_truth_anomaly = True
            reading.ground_truth_type = "collective"

            state["remaining_steps"] -= 1
            if state["remaining_steps"] <= 0:
                del self.active_collective_anomalies[meter_id]
            return reading

        # 2. Check if a new anomaly should be triggered
        if self.rng.random() >= self.anomaly_rate:
            return reading

        # Decide anomaly type based on probability distribution
        choice = self.rng.random()
        
        if choice < self.point_prob:
            # Point Anomaly: single spike or sag
            subtype = self.rng.choice(["voltage_spike", "voltage_sag", "current_spike", "power_spike"])
            reading.ground_truth_anomaly = True
            reading.ground_truth_type = "point"

            if subtype == "voltage_spike":
                # Spike beyond normal limits (e.g. 265V - 280V)
                reading.voltage = round(self.rng.uniform(262.0, 280.0), 2)
            elif subtype == "voltage_sag":
                # Brownout sag (e.g. 170V - 195V)
                reading.voltage = round(self.rng.uniform(170.0, 195.0), 2)
            elif subtype == "current_spike":
                # Sudden high inrush current
                reading.current = round(reading.current * self.rng.uniform(3.5, 6.0), 2)
                reading.power_kw = round((reading.voltage * reading.current * 0.95) / 1000.0, 3)
            elif subtype == "power_spike":
                # Unexpected transient load spike
                reading.power_kw = round(reading.power_kw * self.rng.uniform(4.0, 7.0), 3)

        elif choice < (self.point_prob + self.contextual_prob):
            # Contextual Anomaly: uncharacteristic values relative to temporal context
            # e.g., high consumption during base period or irregular frequency dip
            reading.ground_truth_anomaly = True
            reading.ground_truth_type = "contextual"
            
            if self.rng.random() < 0.5:
                # Moderate sudden power shift (2.2x to 3.2x normal base)
                reading.power_kw = round(reading.power_kw * self.rng.uniform(2.5, 3.5), 3)
                reading.current = round(reading.current * self.rng.uniform(2.2, 3.2), 2)
            else:
                # Frequency deviation outside 49.5Hz - 50.5Hz standard
                reading.frequency_hz = round(self.rng.choice([48.8, 51.2]) + self.rng.gauss(0, 0.1), 2)

        else:
            # Collective Anomaly: start a new sequence over 5-10 consecutive readings
            length = self.rng.randint(5, 10)
            ramp_factor = self.rng.uniform(0.15, 0.30)
            self.active_collective_anomalies[meter_id] = {
                "remaining_steps": length,
                "step_count": 1,
                "factor": ramp_factor,
            }
            reading.power_kw = round(reading.power_kw * (1.0 + ramp_factor), 3)
            reading.current = round(reading.current * (1.0 + ramp_factor), 2)
            reading.ground_truth_anomaly = True
            reading.ground_truth_type = "collective"

        return reading
