import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.logging_config import setup_logger
import argparse
import random
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
        self.stabilize_until = 0.0
        self.forced_fault: Optional[Dict[str, Any]] = None

        # Statistics
        self.total_readings_generated = 0
        self.total_anomalies_injected = 0
        self.anomaly_counts: Dict[str, int] = {}

        # Components
        self.fleet: List[SmartMeterDataGenerator] = create_meter_fleet(self.num_meters, seed=self.random_seed)
        self.anomaly_gen = AnomalyGenerator(anomaly_rate=self.anomaly_rate, seed=self.random_seed)

    def handle_control_command(self, topic: str, payload_str: str, payload_dict: Dict[str, Any]):
        """Receives live remote commands from dashboard (e.g. auto-restore or inject-fault)."""
        cmd = payload_dict.get("command") or payload_dict.get("action")
        if cmd == "stabilize":
            duration = float(payload_dict.get("duration_seconds", 30.0))
            self.stabilize_until = time.time() + duration
            self.anomaly_gen.reset(seed=int(time.time()))
            self.forced_fault = None
            print(f"\n[SIMULATOR] 🛡️ AUTO-RESTORE GRID received: Volt-VAR Stabilization active for {duration:.0f}s (anomalies suppressed)")
        elif cmd == "inject_fault":
            ftype = payload_dict.get("fault_type", "voltage_spike")
            meter_id = payload_dict.get("meter_id")
            if not meter_id and self.fleet:
                meter_id = random.choice(self.fleet).meter_id
            self.forced_fault = {"type": ftype, "meter_id": meter_id or "meter_001"}
            print(f"\n[SIMULATOR] ⚡ INJECT FAULT command received: {ftype} on {meter_id}")

    def generate_all_readings_offline(self) -> List[MeterReading]:
        """Pre-generates full workload for offline/batch experiments."""
        steps = int(self.duration_seconds / self.sampling_interval)
        all_readings: List[MeterReading] = []

        self.logger.info(
            f"Generating offline workload: {self.num_meters} meters, {self.duration_seconds}s duration, "
            f"{self.sampling_interval}s interval ({steps} steps)"
        )

        for step in range(steps):
            for meter in self.fleet:
                raw_reading = meter.generate_reading(time_step=step, interval_seconds=self.sampling_interval)
                final_reading = self.anomaly_gen.process_reading(raw_reading)
                
                self.total_readings_generated += 1
                if final_reading.ground_truth_anomaly and final_reading.ground_truth_type:
                    self.total_anomalies_injected += 1
                    self.anomaly_counts[final_reading.ground_truth_type] = (
                        self.anomaly_counts.get(final_reading.ground_truth_type, 0) + 1
                    )
                
                all_readings.append(final_reading)

        self.logger.info(
            f"Workload generated: {len(all_readings)} total readings, "
            f"{self.total_anomalies_injected} anomalies ({self.anomaly_counts})"
        )
        return all_readings

    def save_workload(self, readings: List[MeterReading], filepath: Path):
        """Saves generated workload to a JSON file."""
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

        # Subscribe to SCADA remote control commands (Auto-Restore, Inject Fault)
        try:
            self.mqtt_client.subscribe("smartgrid/control/commands", self.handle_control_command)
            self.logger.info("Subscribed to control commands on smartgrid/control/commands")
        except Exception as e:
            self.logger.warning(f"Could not subscribe to control topic: {e}")

        self._running = True
        steps = int(self.duration_seconds / self.sampling_interval)
        print(
            f"[SIMULATOR] Starting live simulation: {self.num_meters} meters, {self.duration_seconds}s, "
            f"rate={self.anomaly_rate:.2f}. Press Ctrl+C to stop."
        )

        for step in range(steps):
            if not self._running:
                break
            step_start = time.time()
            is_stabilized = time.time() < self.stabilize_until

            for meter in self.fleet:
                raw_reading = meter.generate_reading(time_step=step, interval_seconds=self.sampling_interval)

                if is_stabilized:
                    raw_reading.voltage = round(230.0 + random.uniform(-0.4, 0.4), 2)
                    raw_reading.frequency_hz = round(50.00 + random.uniform(-0.01, 0.01), 2)
                    raw_reading.ground_truth_anomaly = False
                    raw_reading.ground_truth_type = None
                    final_reading = raw_reading
                else:
                    final_reading = self.anomaly_gen.process_reading(raw_reading)

                # Check forced fault from dashboard command
                if self.forced_fault and self.forced_fault.get("meter_id") == meter.meter_id:
                    ftype = self.forced_fault["type"]
                    final_reading.ground_truth_anomaly = True
                    if ftype == "voltage_spike":
                        final_reading.voltage = 278.5
                        final_reading.ground_truth_type = "point"
                    elif ftype == "voltage_sag":
                        final_reading.voltage = 175.2
                        final_reading.ground_truth_type = "point"
                    elif ftype == "power_surge":
                        final_reading.power_kw = round(final_reading.power_kw * 5.5, 3)
                        final_reading.ground_truth_type = "point"
                    elif ftype == "frequency_drop":
                        final_reading.frequency_hz = 48.65
                        final_reading.ground_truth_type = "contextual"
                    elif ftype == "collective_ramp":
                        final_reading.power_kw = round(final_reading.power_kw * 2.8, 3)
                        final_reading.ground_truth_type = "collective"
                    self.forced_fault = None
                
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
        print(
            f"[SIMULATOR] Finished. Total generated: {self.total_readings_generated}, "
            f"Anomalies: {self.total_anomalies_injected}"
        )


def run_standalone_simulator():
    """Entrypoint to run the simulator directly from CLI."""
    parser = argparse.ArgumentParser(description="Run Smart Grid Meter Simulator")
    parser.add_argument("--host", type=str, default="localhost", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--meters", type=int, default=50, help="Number of simulated smart meters")
    parser.add_argument("--duration", type=int, default=600, help="Duration in seconds")
    parser.add_argument("--interval", type=float, default=1.0, help="Sampling interval in seconds")
    parser.add_argument("--rate", type=float, default=0.03, help="Anomaly injection probability rate")
    args = parser.parse_args()

    print(f"[SIMULATOR] Connecting to MQTT broker at {args.host}:{args.port}...")
    client = MQTTClientWrapper(
        client_id=f"laptop_sim_{int(time.time())}",
        host=args.host,
        port=args.port,
        qos=1,
    )

    if not client.connect():
        print(f"[ERROR] Could not connect to MQTT broker at {args.host}:{args.port}")
        return

    sim = SmartMeterSimulator(
        num_meters=args.meters,
        sampling_interval_seconds=args.interval,
        duration_seconds=args.duration,
        anomaly_rate=args.rate,
        random_seed=int(time.time()),
        mqtt_client=client,
    )

    try:
        sim.run_live()
    except KeyboardInterrupt:
        print("\n[SIMULATOR] Stopped by user.")
    finally:
        client.disconnect()


if __name__ == "__main__":
    run_standalone_simulator()
