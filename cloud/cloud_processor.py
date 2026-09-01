import json
import logging
from typing import Any, Dict, List, Optional
from cloud.database import DatabaseManager
from common.logging_config import setup_logger
from common.message_schema import (
    AnomalyDetectionResult,
    EdgeForwardPayload,
    FogForwardPayload,
    MeterReading,
)
from common.mqtt_client import MQTTClientWrapper


class CloudProcessor:
    """
    Cloud processor for the Edge-Fog-Cloud Distributed architecture.
    Receives processed edge/fog payloads, stores results, and tracks WAN bandwidth.
    """

    def __init__(
        self,
        experiment_id: str = "exp_distributed_001",
        db_manager: Optional[DatabaseManager] = None,
        mqtt_client: Optional[MQTTClientWrapper] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.experiment_id = experiment_id
        self.db = db_manager or DatabaseManager()
        self.mqtt_client = mqtt_client
        self.logger = logger or setup_logger("CloudDistributed")

        # WAN Cloud Traffic Counters
        self.messages_to_cloud = 0
        self.bytes_to_cloud = 0
        self.edge_detections_received = 0
        self.fog_detections_received = 0
        self.all_detections: List[AnomalyDetectionResult] = []

    def handle_edge_stream(self, topic: str, payload_str: str, payload_dict: Dict[str, Any]):
        """Ingests forwarded edge data."""
        self.messages_to_cloud += 1
        self.bytes_to_cloud += len(payload_str.encode("utf-8"))

        try:
            edge_payload = EdgeForwardPayload.model_validate(payload_dict)
        except Exception as e:
            self.logger.error(f"Error parsing edge stream on {topic}: {e}")
            return

        # Store forwarded anomalous/suspicious readings
        for reading in edge_payload.individual_readings:
            self.db.insert_reading(reading, self.experiment_id)

        # Store edge detections
        for detection in edge_payload.detections:
            self.edge_detections_received += 1
            self.all_detections.append(detection)
            self.db.insert_detection(detection)

    def handle_fog_stream(self, topic: str, payload_str: str, payload_dict: Dict[str, Any]):
        """Ingests forwarded fog data."""
        self.messages_to_cloud += 1
        self.bytes_to_cloud += len(payload_str.encode("utf-8"))

        try:
            fog_payload = FogForwardPayload.model_validate(payload_dict)
        except Exception as e:
            self.logger.error(f"Error parsing fog stream on {topic}: {e}")
            return

        # Store fog detections
        for detection in fog_payload.detections:
            self.fog_detections_received += 1
            self.all_detections.append(detection)
            self.db.insert_detection(detection)

    def start_listening(self):
        """Subscribes to Edge and Fog processed topics."""
        if self.mqtt_client is None:
            raise ValueError("MQTT client must be configured to listen")
        self.mqtt_client.subscribe("smartgrid/edge/+/processed", self.handle_edge_stream)
        self.mqtt_client.subscribe("smartgrid/fog/processed", self.handle_fog_stream)
        self.logger.info("Cloud Distributed listening on Edge & Fog processed streams")

    def get_traffic_metrics(self) -> Dict[str, Any]:
        """Returns traffic metrics received at Cloud."""
        return {
            "experiment_id": self.experiment_id,
            "architecture": "distributed",
            "messages_to_cloud": self.messages_to_cloud,
            "bytes_to_cloud": self.bytes_to_cloud,
            "edge_detections": self.edge_detections_received,
            "fog_detections": self.fog_detections_received,
            "total_detections": len(self.all_detections),
        }
