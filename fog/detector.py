import math
from typing import Any, Dict, List, Optional
import numpy as np
from sklearn.ensemble import IsolationForest
from common.message_schema import AnomalyDetectionResult, MeterReading, utc_iso_now
from common.utils import calculate_latency_ms
from fog.aggregator import FogFeatureAggregator


class FogIsolationForestDetector:
    """Multi-variate machine learning anomaly detector utilizing scikit-learn IsolationForest."""

    def __init__(
        self,
        contamination: float = 0.03,
        window_size: int = 20,
        random_state: int = 42,
        min_fit_samples: int = 15,
    ):
        self.contamination = contamination
        self.window_size = window_size
        self.random_state = random_state
        self.min_fit_samples = min_fit_samples
        
        self.aggregator = FogFeatureAggregator(window_size=self.window_size)
        self.feature_history: List[List[float]] = []
        self.model: Optional[IsolationForest] = None
        self._is_fitted = False

    def reset(self):
        """Resets detector state and buffers."""
        self.aggregator.reset()
        self.feature_history.clear()
        self.model = None
        self._is_fitted = False

    def _fit_model_if_needed(self):
        """Fits or updates the Isolation Forest model once sufficient historical features are collected."""
        if len(self.feature_history) >= self.min_fit_samples:
            X = np.array(self.feature_history[-200:])  # fit on recent rolling window
            self.model = IsolationForest(
                contamination=self.contamination,
                random_state=self.random_state,
                n_estimators=50,
            )
            self.model.fit(X)
            self._is_fitted = True

    def process(
        self,
        reading: MeterReading,
        experiment_id: str = "exp_distributed",
        fog_id: str = "fog_01",
    ) -> Optional[AnomalyDetectionResult]:
        """
        Extracts multi-variate features and applies IsolationForest.
        Returns AnomalyDetectionResult if anomalous, else None.
        """
        features = self.aggregator.add_reading(reading)
        if features is None:
            return None

        self.feature_history.append(features)
        self._fit_model_if_needed()

        if not self._is_fitted or self.model is None:
            return None

        X_sample = np.array([features])
        pred = self.model.predict(X_sample)[0]  # -1 for anomaly, 1 for normal
        score = self.model.decision_function(X_sample)[0]  # lower = more anomalous

        if pred == -1:
            latency_ms = calculate_latency_ms(reading.timestamp)
            confidence = min(1.0, round(float(abs(score) * 2.5) + 0.5, 3))
            
            # Determine probable anomaly type from features
            rate_of_change = features[6]
            rolling_std_p = features[5]
            if abs(rate_of_change) > 1.0:
                atype = "point"
            elif rolling_std_p > 0.4:
                atype = "collective"
            else:
                atype = "contextual"

            return AnomalyDetectionResult(
                experiment_id=experiment_id,
                reading_id=reading.reading_id,
                meter_id=reading.meter_id,
                detection_layer="fog",
                anomaly_type=atype,
                detected=True,
                detected_at=utc_iso_now(),
                source_timestamp=reading.timestamp,
                latency_ms=round(latency_ms, 3),
                confidence=confidence,
                details={
                    "fog_id": fog_id,
                    "anomaly_score": round(float(score), 4),
                    "features": [round(f, 3) for f in features],
                },
            )

        return None
