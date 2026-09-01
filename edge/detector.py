from collections import deque
import math
from typing import Dict, Optional, Tuple
from common.message_schema import AnomalyDetectionResult, MeterReading, utc_iso_now
from common.utils import calculate_latency_ms


class EdgeZScoreDetector:
    """Lightweight statistical anomaly detector designed for low-power edge nodes."""

    def __init__(
        self,
        zscore_threshold: float = 3.0,
        rolling_window_size: int = 10,
        min_samples: int = 5,
        target_feature: str = "power_kw",
    ):
        self.zscore_threshold = zscore_threshold
        self.rolling_window_size = rolling_window_size
        self.min_samples = min_samples
        self.target_feature = target_feature

        # Rolling history per meter: meter_id -> deque(maxlen=rolling_window_size)
        self.history: Dict[str, deque] = {}

    def reset(self):
        """Clears rolling buffers."""
        self.history.clear()

    def process(
        self,
        reading: MeterReading,
        experiment_id: str = "exp_distributed",
        edge_id: str = "edge_01",
    ) -> Optional[AnomalyDetectionResult]:
        """
        Evaluates a reading in constant O(1) space.
        Returns AnomalyDetectionResult if anomalous, else None.
        """
        meter_id = reading.meter_id
        val = getattr(reading, self.target_feature, reading.power_kw)

        if meter_id not in self.history:
            self.history[meter_id] = deque(maxlen=self.rolling_window_size)

        buf = self.history[meter_id]
        buf.append(val)

        # Allow sufficient warmup samples before flagging
        if len(buf) < self.min_samples:
            return None

        n = len(buf)
        mean = sum(buf) / n
        variance = sum((x - mean) ** 2 for x in buf) / (n - 1) if n > 1 else 0.0
        std = math.sqrt(variance)

        if std < 1e-6:
            return None

        z_score = abs(val - mean) / std

        # Fast threshold comparison
        is_anomalous = False
        anomaly_type = "statistical_outlier"
        confidence = 0.5

        if z_score >= self.zscore_threshold:
            is_anomalous = True
            anomaly_type = "point" if z_score > 4.5 else "contextual"
            confidence = min(1.0, round(z_score / (self.zscore_threshold + 2.0), 3))
        # Edge physical limits check (e.g. overvoltage / severe sag)
        elif reading.voltage < 195.0 or reading.voltage > 265.0:
            is_anomalous = True
            anomaly_type = "point"
            confidence = 0.95

        if is_anomalous:
            latency_ms = calculate_latency_ms(reading.timestamp)
            return AnomalyDetectionResult(
                experiment_id=experiment_id,
                reading_id=reading.reading_id,
                meter_id=reading.meter_id,
                detection_layer="edge",
                anomaly_type=anomaly_type,
                detected=True,
                detected_at=utc_iso_now(),
                source_timestamp=reading.timestamp,
                latency_ms=round(latency_ms, 3),
                confidence=confidence,
                details={
                    "edge_id": edge_id,
                    "feature": self.target_feature,
                    "value": val,
                    "mean": round(mean, 3),
                    "std": round(std, 3),
                    "z_score": round(z_score, 3),
                },
            )

        return None
