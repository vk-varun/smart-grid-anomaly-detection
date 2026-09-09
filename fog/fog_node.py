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


def main():
    parser = argparse.ArgumentParser(description="Run Regional Fog Computing Node")
    parser.add_argument("--host", type=str, default="localhost", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--fog-id", type=str, default="fog_01", help="Fog Node ID")
    args = parser.parse_args()

    print(f"[{args.fog_id}] Connecting to MQTT broker at {args.host}:{args.port}...")
    mqtt_client = MQTTClientWrapper(client_id=f"{args.fog_id}_{int(time.time())}", host=args.host, port=args.port)
    if not mqtt_client.connect():
        print(f"[ERROR] Could not connect to MQTT broker at {args.host}:{args.port}")
        return

    fog_node = FogNode(fog_id=args.fog_id, mqtt_client=mqtt_client)
    fog_node.start_listening()
    print(f"[{args.fog_id}] Running IsolationForest on aggregated edge streams. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n[{args.fog_id}] Stopping...")
    finally:
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()
