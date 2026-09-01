import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import paho.mqtt.client as mqtt
from common.logging_config import setup_logger


class MQTTClientWrapper:
    """A resilient wrapper around paho-mqtt for telemetry and event messaging."""

    def __init__(
        self,
        client_id: str,
        host: str = "localhost",
        port: int = 1883,
        keepalive: int = 60,
        qos: int = 1,
        logger: Optional[logging.Logger] = None,
    ):
        self.client_id = client_id
        self.host = host
        self.port = port
        self.keepalive = keepalive
        self.qos = qos
        self.logger = logger or setup_logger(f"MQTT-{client_id}")

        # Metrics tracking
        self.messages_sent = 0
        self.bytes_sent = 0
        self.messages_received = 0
        self.bytes_received = 0
        self._lock = threading.Lock()

        # Callbacks map: topic_pattern -> callback(topic, payload_str, payload_dict)
        self._subscriptions: Dict[str, Callable[[str, str, Dict[str, Any]], None]] = {}
        self._is_connected = False

        # Support both Paho MQTT v1 and v2
        try:
            # Paho MQTT v2.x
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                client_id=self.client_id,
            )
        except AttributeError:
            # Paho MQTT v1.x
            self.client = mqtt.Client(client_id=self.client_id)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._is_connected = True
            self.logger.info(f"Connected to MQTT broker at {self.host}:{self.port}")
            # Resubscribe existing topics upon reconnect
            for topic in self._subscriptions.keys():
                self.client.subscribe(topic, qos=self.qos)
                self.logger.debug(f"Subscribed to {topic} (QoS {self.qos})")
        else:
            self._is_connected = False
            self.logger.error(f"Failed to connect to MQTT broker, return code {rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._is_connected = False
        if rc != 0:
            self.logger.warning(f"Unexpected MQTT disconnection (rc={rc}). Will attempt auto-reconnect.")
        else:
            self.logger.info("Disconnected from MQTT broker.")

    def _on_message(self, client, userdata, msg):
        payload_bytes = len(msg.payload)
        with self._lock:
            self.messages_received += 1
            self.bytes_received += payload_bytes

        payload_str = msg.payload.decode("utf-8", errors="replace")
        try:
            payload_dict = json.loads(payload_str)
        except Exception:
            payload_dict = {}

        matched = False
        for topic_pattern, callback in list(self._subscriptions.items()):
            if mqtt.topic_matches_sub(topic_pattern, msg.topic):
                matched = True
                try:
                    callback(msg.topic, payload_str, payload_dict)
                except Exception as e:
                    self.logger.error(f"Error in callback for topic '{msg.topic}': {e}", exc_info=True)

        if not matched:
            self.logger.debug(f"No specific handler matched for topic: {msg.topic}")

    def connect(self, wait_seconds: float = 2.0) -> bool:
        """Connects to the broker and starts the background network loop."""
        try:
            self.client.connect(self.host, self.port, self.keepalive)
            self.client.loop_start()
            start_time = time.time()
            while time.time() - start_time < wait_seconds:
                if self._is_connected:
                    return True
                time.sleep(0.05)
            return self._is_connected
        except Exception as e:
            self.logger.error(f"Failed to connect to MQTT broker at {self.host}:{self.port} - {e}")
            return False

    def disconnect(self):
        """Stops the loop and disconnects cleanly."""
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception as e:
            self.logger.debug(f"Error during disconnect: {e}")

    def subscribe(self, topic: str, callback: Callable[[str, str, Dict[str, Any]], None]):
        """Registers a subscription and callback."""
        self._subscriptions[topic] = callback
        if self._is_connected:
            self.client.subscribe(topic, qos=self.qos)
            self.logger.info(f"Subscribed to topic: {topic}")

    def publish(self, topic: str, payload: Any, qos: Optional[int] = None) -> bool:
        """Publishes a payload (dict, Pydantic model, or str) to a topic."""
        if hasattr(payload, "model_dump_json"):
            payload_str = payload.model_dump_json()
        elif isinstance(payload, dict):
            payload_str = json.dumps(payload)
        elif isinstance(payload, str):
            payload_str = payload
        else:
            payload_str = str(payload)

        payload_bytes = len(payload_str.encode("utf-8"))
        use_qos = qos if qos is not None else self.qos

        info = self.client.publish(topic, payload_str, qos=use_qos)
        with self._lock:
            self.messages_sent += 1
            self.bytes_sent += payload_bytes
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def get_traffic_metrics(self) -> Dict[str, int]:
        """Returns message and byte counts."""
        with self._lock:
            return {
                "messages_sent": self.messages_sent,
                "bytes_sent": self.bytes_sent,
                "messages_received": self.messages_received,
                "bytes_received": self.bytes_received,
            }

    def reset_traffic_metrics(self):
        """Resets traffic counters."""
        with self._lock:
            self.messages_sent = 0
            self.bytes_sent = 0
            self.messages_received = 0
            self.bytes_received = 0
