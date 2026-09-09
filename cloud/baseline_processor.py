import argparse
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cloud.baseline_detector import CloudBaselineDetector
from cloud.database import DatabaseManager
from common.logging_config import setup_logger
from common.message_schema import AnomalyDetectionResult, MeterReading
from common.mqtt_client import MQTTClientWrapper
from common.utils import load_config


class CloudBaselineProcessor:
    """Cloud-only baseline processor that subscribes to all raw meter readings."""

    def __init__(
        self,
        experiment_id: str = "exp_baseline_001",
        db_manager: Optional[DatabaseManager] = None,
        detector: Optional[CloudBaselineDetector] = None,
        mqtt_client: Optional[MQTTClientWrapper] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.experiment_id = experiment_id
        self.db = db_manager or DatabaseManager()
        self.detector = detector or CloudBaselineDetector()
        self.mqtt_client = mqtt_client
        self.logger = logger or setup_logger("CloudBaseline")

        self.messages_processed = 0
        self.bytes_processed = 0
        self.anomalies_detected = 0
        self.detected_list: List[AnomalyDetectionResult] = []

    def handle_raw_reading(self, topic: str, payload_str: str, payload_dict: Dict[str, Any]):
        """Callback for incoming meter reading MQTT messages."""
        self.messages_processed += 1
        self.bytes_processed += len(payload_str.encode("utf-8"))

        try:
            reading = MeterReading.model_validate(payload_dict)
        except Exception as e:
            self.logger.error(f"Malformed reading received on {topic}: {e}")
            return

        # Store every raw reading in cloud database
        self.db.insert_reading(reading, self.experiment_id)

        # Run anomaly detection
        detection = self.detector.process_reading(reading, self.experiment_id)
        if detection is not None:
            self.anomalies_detected += 1
            self.detected_list.append(detection)
            self.db.insert_detection(detection)
            self.logger.info(
                f"[BASELINE ALERT] Anomaly detected on {reading.meter_id}: "
                f"type={detection.anomaly_type}, latency={detection.latency_ms}ms"
            )

    def start_listening(self, topic_sub: str = "smartgrid/meters/+/readings"):
        """Subscribes to all meter readings."""
        if self.mqtt_client is None:
            raise ValueError("MQTT client must be configured to listen")
        self.mqtt_client.subscribe(topic_sub, self.handle_raw_reading)
        self.logger.info(f"Cloud Baseline listening on topic: {topic_sub}")

    def get_summary_metrics(self) -> Dict[str, Any]:
        """Returns processing metrics."""
        return {
            "experiment_id": self.experiment_id,
            "architecture": "cloud_baseline",
            "messages_processed": self.messages_processed,
            "bytes_processed": self.bytes_processed,
            "anomalies_detected": self.anomalies_detected,
        }


def main():
    parser = argparse.ArgumentParser(description="Run Cloud-Only Baseline Telemetry Processor")
    parser.add_argument("--host", type=str, default="localhost", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--exp-id", type=str, default=None, help="Experiment ID")
    args = parser.parse_args()

    exp_id = args.exp_id or f"cloud_baseline_{int(time.time())}"
    print(f"[CLOUD BASELINE] Connecting to MQTT broker at {args.host}:{args.port} (Exp: {exp_id})...")

    mqtt_client = MQTTClientWrapper(client_id=f"cloud_baseline_{int(time.time())}", host=args.host, port=args.port)
    if not mqtt_client.connect():
        print(f"[ERROR] Could not connect to MQTT broker at {args.host}:{args.port}")
        return

    processor = CloudBaselineProcessor(experiment_id=exp_id, mqtt_client=mqtt_client)
    processor.start_listening()
    print("[CLOUD BASELINE] Active and listening for raw smart meter readings. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[CLOUD BASELINE] Stopping processor...")
    finally:
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()
