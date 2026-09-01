import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
from common.logging_config import setup_logger
from common.message_schema import MeterReading
from common.mqtt_client import MQTTClientWrapper
from common.utils import get_project_root, load_config
from simulator.anomaly_generator import AnomalyGenerator
from simulator.data_generator import SmartMeterDataGenerator, create_meter_fleet


class SmartMeterSimulator:
    """Orchestrates smart meter simulation, anomaly injection, and MQTT publishing."""

    def __init__(
        self,
        num_meters: int = 50,
        sampling_interval_seconds: float = 1.0,
        duration_seconds: int = 120,
        anomaly_rate: float = 0.03,
        random_seed: int = 42,
        mqtt_client: Optional[MQTTClientWrapper] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.num_meters = num_meters
        self.sampling_interval = sampling_interval_seconds
        self.duration_seconds = duration_seconds
        self.anomaly_rate = anomaly_rate
        self.random_seed = random_seed
        self.logger = logger or setup_logger("Simulator")

        self.mqtt_client = mqtt_client
        self._running = False
        
        # Statistics
        self.total_readings_generated = 0
        self.total_anomalies_injected = 0
        self.anomaly_counts: Dict[str, int] = {"point": 0, "contextual": 0, "collective": 0}

        # Initialize fleet and anomaly generator
        self.fleet: List[SmartMeterDataGenerator] = create_meter_fleet(self.num_meters, seed=self.random_seed)
        self.anomaly_gen = AnomalyGenerator(
            anomaly_rate=self.anomaly_rate,
            seed=self.random_seed,
        )

    def generate_all_readings_offline(self) -> List[MeterReading]:
        """Pre-generates an entire deterministic experiment dataset for exact replay comparisons."""
        readings: List[MeterReading] = []
        steps = int(self.duration_seconds / self.sampling_interval)
        self.anomaly_gen.reset(seed=self.random_seed)

        for step in range(steps):
            for meter in self.fleet:
                raw_reading = meter.generate_reading(time_step=step, interval_seconds=self.sampling_interval)
                final_reading = self.anomaly_gen.process_reading(raw_reading)
                readings.append(final_reading)
                
                self.total_readings_generated += 1
                if final_reading.ground_truth_anomaly and final_reading.ground_truth_type:
                    self.total_anomalies_injected += 1
                    self.anomaly_counts[final_reading.ground_truth_type] = (
                        self.anomaly_counts.get(final_reading.ground_truth_type, 0) + 1
                    )
        return readings

    def save_workload(self, filepath: Path, readings: Optional[List[MeterReading]] = None):
        """Saves generated workload to a JSON file."""
        if readings is None:
            readings = self.generate_all_readings_offline()
        filepath.parent.mkdir(parents=True, exist_ok=True)
        data = [r.model_dump() for r in readings]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.logger.info(f"Saved {len(readings)} readings workload to {filepath}")

    @classmethod
    def load_workload(cls, filepath: Path) -> List[MeterReading]:
        """Loads a pre-generated workload from JSON file."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [MeterReading(**item) for item in data]

    def stop(self):
        """Signals the simulator to stop publishing."""
        self._running = False

    def run_live(self, on_reading_callback: Optional[callable] = None):
        """Runs the live simulation and publishes each reading to MQTT."""
        if self.mqtt_client is None:
            raise ValueError("MQTT client must be configured to run live simulation")

        self._running = True
        steps = int(self.duration_seconds / self.sampling_interval)
        self.logger.info(
            f"Starting live simulation: {self.num_meters} meters, {self.duration_seconds}s duration, "
            f"{self.sampling_interval}s interval, anomaly_rate={self.anomaly_rate}"
        )

        for step in range(steps):
            if not self._running:
                break
            step_start = time.time()

            for meter in self.fleet:
                raw_reading = meter.generate_reading(time_step=step, interval_seconds=self.sampling_interval)
                final_reading = self.anomaly_gen.process_reading(raw_reading)
                
                self.total_readings_generated += 1
                if final_reading.ground_truth_anomaly and final_reading.ground_truth_type:
                    self.total_anomalies_injected += 1
                    self.anomaly_counts[final_reading.ground_truth_type] = (
                        self.anomaly_counts.get(final_reading.ground_truth_type, 0) + 1
                    )

                # Publish to topic smartgrid/meters/{meter_id}/readings
                topic = f"smartgrid/meters/{final_reading.meter_id}/readings"
                self.mqtt_client.publish(topic, final_reading)

                if on_reading_callback:
                    on_reading_callback(final_reading)

            elapsed = time.time() - step_start
            sleep_time = max(0.0, self.sampling_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

        self._running = False
        self.logger.info(
            f"Simulation complete. Total generated: {self.total_readings_generated}, "
            f"Anomalies: {self.total_anomalies_injected} ({self.anomaly_counts})"
        )


def run_standalone_simulator():
    """Entrypoint to run the simulator directly from CLI or script."""
    cfg = load_config()
    sim_cfg = cfg.get("simulation", {})
    mqtt_cfg = cfg.get("mqtt", {})

    client = MQTTClientWrapper(
        client_id="standalone_simulator",
        host=mqtt_cfg.get("host", "localhost"),
        port=mqtt_cfg.get("port", 1883),
        qos=mqtt_cfg.get("qos", 1),
    )

    if not client.connect():
        print("[WARNING] Could not connect to MQTT broker. Running offline data generation check.")
        sim = SmartMeterSimulator(
            num_meters=sim_cfg.get("num_meters", 10),
            duration_seconds=10,
            sampling_interval_seconds=1.0,
            anomaly_rate=0.05,
            random_seed=42,
        )
        readings = sim.generate_all_readings_offline()
        print(f"Generated {len(readings)} readings offline successfully.")
        return

    sim = SmartMeterSimulator(
        num_meters=sim_cfg.get("num_meters", 50),
        sampling_interval_seconds=sim_cfg.get("sampling_interval_seconds", 1.0),
        duration_seconds=sim_cfg.get("duration_seconds", 60),
        anomaly_rate=sim_cfg.get("anomaly_rate", 0.03),
        random_seed=sim_cfg.get("random_seed", 42),
        mqtt_client=client,
    )

    try:
        sim.run_live()
    finally:
        client.disconnect()


if __name__ == "__main__":
    run_standalone_simulator()
