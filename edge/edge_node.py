import logging
from typing import Any, Dict, List, Optional, Set
from common.logging_config import setup_logger
from common.message_schema import (
    AnomalyDetectionResult,
    EdgeForwardPayload,
    MeterReading,
)
from common.mqtt_client import MQTTClientWrapper
from edge.detector import EdgeZScoreDetector
from edge.filter import EdgeDataFilter


class EdgeNode:
    """Represents a localized Edge computing node monitoring a partition of smart meters."""

    def __init__(
        self,
        edge_id: str = "edge_01",
        assigned_meter_ids: Optional[Set[str]] = None,
        detector: Optional[EdgeZScoreDetector] = None,
        filter_handler: Optional[EdgeDataFilter] = None,
        mqtt_client: Optional[MQTTClientWrapper] = None,
        experiment_id: str = "exp_distributed",
        logger: Optional[logging.Logger] = None,
    ):
        self.edge_id = edge_id
        self.assigned_meter_ids = assigned_meter_ids or set()
        self.detector = detector or EdgeZScoreDetector()
        self.filter = filter_handler or EdgeDataFilter(edge_id=edge_id)
        self.mqtt_client = mqtt_client
        self.experiment_id = experiment_id
        self.logger = logger or setup_logger(f"Edge-{edge_id}")

        self.anomalies_detected = 0
        self.detections_list: List[AnomalyDetectionResult] = []

    def handles_meter(self, meter_id: str) -> bool:
        """Determines if this edge node is responsible for the given meter."""
        if not self.assigned_meter_ids:
            return True  # If empty set, handles all assigned
        return meter_id in self.assigned_meter_ids

    def process_incoming_reading(self, reading: MeterReading) -> Optional[EdgeForwardPayload]:
        """
        Core edge processing pipeline:
        1. Localized Anomaly Detection (Rolling Z-Score)
        2. Immediate forwarding for anomalies
        3. Aggregated windowing for normal readings
        """
        if not self.handles_meter(reading.meter_id):
            return None

        # 1. Evaluate lightweight anomaly detector
        detection = self.detector.process(
            reading=reading,
            experiment_id=self.experiment_id,
            edge_id=self.edge_id,
        )

        payload = None
        if detection is not None:
            self.anomalies_detected += 1
            self.detections_list.append(detection)
            self.filter.readings_forwarded_individually += 1

            # Anomaly detected: immediately package individual reading and detection result
            payload = EdgeForwardPayload(
                edge_id=self.edge_id,
                individual_readings=[reading],
                aggregations=[],
                detections=[detection],
            )
            self.logger.info(
                f"[{self.edge_id}] Detected {detection.anomaly_type} anomaly on {reading.meter_id} "
                f"(latency: {detection.latency_ms}ms)"
            )
        else:
            # Normal reading: buffer for periodic aggregation
            agg = self.filter.buffer_normal_reading(reading)
            if agg is not None:
                payload = EdgeForwardPayload(
                    edge_id=self.edge_id,
                    individual_readings=[],
                    aggregations=[agg],
                    detections=[],
                )

        if payload is not None and self.mqtt_client is not None:
            topic = f"smartgrid/edge/{self.edge_id}/processed"
            self.mqtt_client.publish(topic, payload)

        return payload

    def handle_mqtt_message(self, topic: str, payload_str: str, payload_dict: Dict[str, Any]):
        """MQTT message handler callback."""
        try:
            reading = MeterReading.model_validate(payload_dict)
            self.process_incoming_reading(reading)
        except Exception as e:
            self.logger.error(f"[{self.edge_id}] Error parsing message on {topic}: {e}")

    def start_listening(self, topic_sub: str = "smartgrid/meters/+/readings"):
        """Subscribes to smart meter readings."""
        if self.mqtt_client is None:
            raise ValueError("MQTT client must be provided to listen")
        self.mqtt_client.subscribe(topic_sub, self.handle_mqtt_message)
        self.logger.info(f"[{self.edge_id}] Listening on {topic_sub}")

    def flush_and_send(self):
        """Flushes remaining buffered aggregations and sends to downstream."""
        remaining_aggs = self.filter.flush_remaining_aggregations()
        if remaining_aggs and self.mqtt_client is not None:
            payload = EdgeForwardPayload(
                edge_id=self.edge_id,
                individual_readings=[],
                aggregations=remaining_aggs,
                detections=[],
            )
            topic = f"smartgrid/edge/{self.edge_id}/processed"
            self.mqtt_client.publish(topic, payload)
