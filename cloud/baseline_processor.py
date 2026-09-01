import json
import logging
import time
from typing import Any, Dict, List, Optional
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
