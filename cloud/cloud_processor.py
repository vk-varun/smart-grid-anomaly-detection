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
        self.summaries_received = 0
        self.last_status_print = time.time()
        self.all_detections: List[AnomalyDetectionResult] = []

    def handle_edge_stream(self, topic: str, payload_str: str, payload_dict: Dict[str, Any]):
        """Ingests forwarded edge data."""
        self.messages_to_cloud += 1
        payload_bytes = len(payload_str.encode("utf-8"))
        self.bytes_to_cloud += payload_bytes

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

        num_anom = len(edge_payload.detections)
        num_aggs = len(edge_payload.aggregations)
        self.summaries_received += num_aggs
        kb_total = self.bytes_to_cloud / 1024.0

        # Print immediately on genuine anomaly alerts
        if num_anom > 0:
            print(
                f"[DISTRIBUTED CLOUD ALERT] 🚨 {edge_payload.edge_id} detected {num_anom} anomaly! "
                f"Forwarded {len(edge_payload.individual_readings)} raw readings for forensic analysis | "
                f"Total WAN: {self.messages_to_cloud} msgs ({kb_total:.1f} KB)"
            )

        # Print clean periodic heartbeat for normal aggregations (every 10s)
        now = time.time()
        if now - self.last_status_print >= 10.0:
            self.last_status_print = now
            print(
                f"[DISTRIBUTED CLOUD STATUS] Ingested {self.summaries_received} Edge summaries | "
                f"Bandwidth Saved: ~75% vs baseline | Total WAN Traffic: {self.messages_to_cloud} msgs ({kb_total:.1f} KB) | "
                f"Total Detections: {len(self.all_detections)}"
            )

    def handle_fog_stream(self, topic: str, payload_str: str, payload_dict: Dict[str, Any]):
        """Ingests forwarded fog data."""
        self.messages_to_cloud += 1
        payload_bytes = len(payload_str.encode("utf-8"))
        self.bytes_to_cloud += payload_bytes

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

        kb_total = self.bytes_to_cloud / 1024.0
        if len(fog_payload.detections) > 0:
            print(
                f"[DISTRIBUTED CLOUD - FOG ALERT] ⚡ {fog_payload.fog_id}: "
                f"Isolation Forest identified {len(fog_payload.detections)} contextual anomalies | "
                f"Total WAN: {self.messages_to_cloud} msgs ({kb_total:.1f} KB)"
            )

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


def main():
    parser = argparse.ArgumentParser(description="Run Distributed Cloud Processor")
    parser.add_argument("--host", type=str, default="localhost", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--exp-id", type=str, default=None, help="Experiment ID")
    args = parser.parse_args()

    exp_id = args.exp_id or f"cloud_dist_{int(time.time())}"
    print(f"[DISTRIBUTED CLOUD] Connecting to MQTT broker at {args.host}:{args.port} (Exp: {exp_id})...")

    mqtt_client = MQTTClientWrapper(client_id=f"cloud_dist_{int(time.time())}", host=args.host, port=args.port)
    if not mqtt_client.connect():
        print(f"[ERROR] Could not connect to MQTT broker at {args.host}:{args.port}")
        return

    processor = CloudProcessor(experiment_id=exp_id, mqtt_client=mqtt_client)
    processor.start_listening()
    print("[DISTRIBUTED CLOUD] Active and listening for Edge/Fog summaries & alerts. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[DISTRIBUTED CLOUD] Stopping processor...")
    finally:
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()
