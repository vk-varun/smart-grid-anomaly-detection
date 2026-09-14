from collections import deque
import math
from typing import Dict, Optional, Tuple
from common.message_schema import AnomalyDetectionResult, MeterReading, utc_iso_now
from common.utils import calculate_latency_ms


class CloudBaselineDetector:
    """Baseline anomaly detector operating at the Cloud layer."""

    def __init__(
        self,
        zscore_threshold: float = 3.0,
        rolling_window_size: int = 15,
        min_samples: int = 5,
        target_feature: str = "power_kw",
    ):
        self.zscore_threshold = zscore_threshold
        self.rolling_window_size = rolling_window_size
        self.min_samples = min_samples
        self.target_feature = target_feature

        # Per-meter rolling buffers: meter_id -> deque([val1, val2, ...])
        self.history: Dict[str, deque] = {}
        self.consecutive_anomalies: Dict[str, int] = {}

    def reset(self):
        """Clears detector state."""
        self.history.clear()
        self.consecutive_anomalies.clear()

    def _update_and_calculate_zscore(self, meter_id: str, value: float) -> Tuple[float, float, float]:
        """Calculates z-score against historical baseline window and updates buffer."""
        if meter_id not in self.history:
            self.history[meter_id] = deque(maxlen=self.rolling_window_size)

        buf = self.history[meter_id]

        if len(buf) < self.min_samples:
            buf.append(value)
            return 0.0, value, 0.0

        n = len(buf)
        mean = sum(buf) / n
        variance = sum((x - mean) ** 2 for x in buf) / (n - 1) if n > 1 else 0.0
        std = math.sqrt(variance)

        # Realistic electrical variance floor: 15% of mean or 0.12 kW minimum
        effective_std = max(std, 0.15 * abs(mean), 0.12)

        z_score = abs(value - mean) / effective_std

        # Adapt to legitimate persistent load step shifts
        if z_score >= self.zscore_threshold:
            streak = self.consecutive_anomalies.get(meter_id, 0) + 1
            self.consecutive_anomalies[meter_id] = streak
            if streak >= 4:
                buf.append(value)
                self.consecutive_anomalies[meter_id] = 0
        else:
            self.consecutive_anomalies[meter_id] = 0
            buf.append(value)

        return z_score, mean, std

    def process_reading(
        self,
        reading: MeterReading,
        experiment_id: str = "exp_baseline",
    ) -> Optional[AnomalyDetectionResult]:
        """Evaluates a reading. Returns AnomalyDetectionResult if anomalous, else None."""
        val = getattr(reading, self.target_feature, reading.power_kw)
        z_score, mean, std = self._update_and_calculate_zscore(reading.meter_id, val)

        is_anomalous = False
        anomaly_type = "statistical_outlier"
        confidence = 0.5

        # 1. Z-Score threshold trigger
        if z_score >= self.zscore_threshold:
            is_anomalous = True
            anomaly_type = "point" if z_score > 4.5 else "contextual"
            confidence = min(1.0, round(z_score / (self.zscore_threshold + 2.0), 3))

        # 2. Extreme physical voltage/frequency violation safety triggers
        elif reading.voltage < 195.0 or reading.voltage > 265.0:
            is_anomalous = True
            anomaly_type = "point"
            confidence = 0.95
        elif reading.frequency_hz < 49.0 or reading.frequency_hz > 51.0:
            is_anomalous = True
            anomaly_type = "contextual"
            confidence = 0.85

        if is_anomalous:
            latency_ms = calculate_latency_ms(reading.timestamp)
            return AnomalyDetectionResult(
                experiment_id=experiment_id,
                reading_id=reading.reading_id,
                meter_id=reading.meter_id,
                detection_layer="cloud_baseline",
                anomaly_type=anomaly_type,
                detected=True,
                detected_at=utc_iso_now(),
                source_timestamp=reading.timestamp,
                latency_ms=round(latency_ms, 3),
                confidence=confidence,
                details={
                    "feature": self.target_feature,
                    "value": val,
                    "mean": round(mean, 3),
                    "std": round(std, 3),
                    "z_score": round(z_score, 3),
                },
            )

        return None
