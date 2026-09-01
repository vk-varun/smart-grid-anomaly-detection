import json
import logging
from typing import Any, Dict, List, Optional
from common.logging_config import setup_logger
from common.message_schema import (
    AnomalyDetectionResult,
    EdgeForwardPayload,
    FogForwardPayload,
    MeterReading,
)
from common.mqtt_client import MQTTClientWrapper
from fog.detector import FogIsolationForestDetector


class FogNode:
    """Fog computing node aggregating data from multiple edge nodes and running IsolationForest."""

    def __init__(
        self,
        fog_id: str = "fog_01",
        detector: Optional[FogIsolationForestDetector] = None,
        mqtt_client: Optional[MQTTClientWrapper] = None,
        experiment_id: str = "exp_distributed",
        logger: Optional[logging.Logger] = None,
    ):
        self.fog_id = fog_id
        self.detector = detector or FogIsolationForestDetector()
        self.mqtt_client = mqtt_client
        self.experiment_id = experiment_id
        self.logger = logger or setup_logger(f"Fog-{fog_id}")

        self.messages_received = 0
        self.bytes_received = 0
        self.anomalies_detected = 0
        self.fog_detections_list: List[AnomalyDetectionResult] = []

    def handle_edge_payload(self, topic: str, payload_str: str, payload_dict: Dict[str, Any]):
        """Processes incoming EdgeForwardPayload from an edge node."""
        self.messages_received += 1
        self.bytes_received += len(payload_str.encode("utf-8"))

        try:
            edge_payload = EdgeForwardPayload.model_validate(payload_dict)
        except Exception as e:
            self.logger.error(f"Error parsing edge payload on {topic}: {e}")
            return

        new_fog_detections: List[AnomalyDetectionResult] = []

        # Run Fog-level ML detector on individually forwarded readings
        for reading in edge_payload.individual_readings:
            det = self.detector.process(
                reading=reading,
                experiment_id=self.experiment_id,
                fog_id=self.fog_id,
            )
            if det is not None:
                self.anomalies_detected += 1
                self.fog_detections_list.append(det)
                new_fog_detections.append(det)
                self.logger.info(
                    f"[{self.fog_id}] IsolationForest detected anomaly on {reading.meter_id} "
                    f"(latency: {det.latency_ms}ms)"
                )

        # Forward fog detection events to Cloud
        if new_fog_detections and self.mqtt_client is not None:
            fog_out = FogForwardPayload(
                fog_id=self.fog_id,
                detections=new_fog_detections,
                summary_metrics={
                    "total_edge_messages": self.messages_received,
                    "fog_anomalies_count": self.anomalies_detected,
                },
            )
            self.mqtt_client.publish("smartgrid/fog/processed", fog_out)

    def start_listening(self, topic_sub: str = "smartgrid/edge/+/processed"):
        """Subscribes to all edge node outputs."""
        if self.mqtt_client is None:
            raise ValueError("MQTT client must be configured to listen")
        self.mqtt_client.subscribe(topic_sub, self.handle_edge_payload)
        self.logger.info(f"[{self.fog_id}] Listening on {topic_sub}")
