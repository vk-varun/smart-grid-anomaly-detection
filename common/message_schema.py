from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import uuid


def utc_iso_now() -> str:
    """Returns current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


class MeterReading(BaseModel):
    """Telemetry reading from a smart meter."""
    reading_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    meter_id: str
    timestamp: str = Field(default_factory=utc_iso_now)
    sequence: int
    voltage: float
    current: float
    power_kw: float
    energy_kwh: float
    frequency_hz: float
    ground_truth_anomaly: bool = False
    ground_truth_type: Optional[str] = None  # "point", "contextual", "collective", or None

    def payload_bytes(self) -> int:
        """Calculates JSON payload size in bytes."""
        return len(self.model_dump_json().encode("utf-8"))


class AnomalyDetectionResult(BaseModel):
    """Detection outcome from Edge, Fog, or Cloud baseline."""
    detection_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    experiment_id: str = "exp_default"
    reading_id: Optional[str] = None
    meter_id: str
    detection_layer: str  # "edge", "fog", "cloud_baseline"
    anomaly_type: Optional[str] = None  # "point", "contextual", "collective", "statistical_outlier"
    detected: bool = True
    detected_at: str = Field(default_factory=utc_iso_now)
    source_timestamp: str
    latency_ms: float
    confidence: float = 1.0
    details: Optional[Dict[str, Any]] = None

    def payload_bytes(self) -> int:
        return len(self.model_dump_json().encode("utf-8"))


class AggregatedReading(BaseModel):
    """Summary aggregation of normal readings produced at Edge."""
    agg_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    edge_id: str
    meter_id: str
    start_time: str
    end_time: str
    count: int
    avg_voltage: float
    avg_current: float
    avg_power_kw: float
    total_energy_kwh: float
    avg_frequency_hz: float


class EdgeForwardPayload(BaseModel):
    """Data bundle forwarded from Edge to Fog/Cloud."""
    edge_id: str
    timestamp: str = Field(default_factory=utc_iso_now)
    individual_readings: List[MeterReading] = Field(default_factory=list)
    aggregations: List[AggregatedReading] = Field(default_factory=list)
    detections: List[AnomalyDetectionResult] = Field(default_factory=list)

    def payload_bytes(self) -> int:
        return len(self.model_dump_json().encode("utf-8"))


class FogForwardPayload(BaseModel):
    """Data bundle forwarded from Fog to Cloud."""
    fog_id: str = "fog_01"
    timestamp: str = Field(default_factory=utc_iso_now)
    detections: List[AnomalyDetectionResult] = Field(default_factory=list)
    summary_metrics: Optional[Dict[str, Any]] = None

    def payload_bytes(self) -> int:
        return len(self.model_dump_json().encode("utf-8"))
