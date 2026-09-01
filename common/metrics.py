import math
from typing import Any, Dict, List, Optional, Set
import numpy as np
from pydantic import BaseModel
from common.message_schema import AnomalyDetectionResult, MeterReading


class ExperimentEvaluationReport(BaseModel):
    """Structured evaluation report summarizing experimental results."""
    experiment_id: str
    architecture: str  # "cloud_baseline" or "distributed"
    total_readings: int
    duration_seconds: float
    
    # Classification Performance
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float
    recall: float
    f1_score: float
    accuracy: float
    
    # By Anomaly Type
    metrics_by_type: Dict[str, Dict[str, float]]
    
    # Detection Latency (in milliseconds)
    latency_mean_ms: float
    latency_median_ms: float
    latency_p95_ms: float
    latency_min_ms: float
    latency_max_ms: float
    
    # Bandwidth and Transmission
    total_messages_generated: int
    total_bytes_generated: int
    messages_to_cloud: int
    bytes_to_cloud: int
    
    # Throughput & Resources
    throughput_readings_per_sec: float
    avg_cpu_percent: Optional[float] = None
    peak_cpu_percent: Optional[float] = None
    avg_memory_mb: Optional[float] = None
    peak_memory_mb: Optional[float] = None


class MetricsCalculator:
    """Computes academic-rigor evaluation metrics for smart grid monitoring experiments."""

    @staticmethod
    def calculate_classification_metrics(
        ground_truth_readings: List[MeterReading],
        detections: List[AnomalyDetectionResult],
    ) -> Dict[str, Any]:
        """
        Calculates TP, FP, TN, FN, Precision, Recall, F1 score and type breakdown.
        A reading is considered a True Positive if ground_truth_anomaly is True and
        a detection was registered for that reading_id (or corresponding meter/time).
        """
        # Set of reading IDs flagged by detectors
        detected_reading_ids: Set[str] = {
            d.reading_id for d in detections if d.reading_id is not None
        }

        # Backup map for detections without reading_id (e.g. window-based): (meter_id, source_timestamp)
        detected_meter_timestamps: Set[Tuple] = {
            (d.meter_id, d.source_timestamp) for d in detections
        }

        tp = 0
        fp = 0
        tn = 0
        fn = 0

        # Type-specific counters: type -> {"tp": int, "fn": int}
        type_counts: Dict[str, Dict[str, int]] = {
            "point": {"tp": 0, "fn": 0},
            "contextual": {"tp": 0, "fn": 0},
            "collective": {"tp": 0, "fn": 0},
        }

        for r in ground_truth_readings:
            is_detected = (r.reading_id in detected_reading_ids) or (
                (r.meter_id, r.timestamp) in detected_meter_timestamps
            )
            is_actual_anomaly = bool(r.ground_truth_anomaly)
            atype = r.ground_truth_type or "unknown"

            if is_actual_anomaly and is_detected:
                tp += 1
                if atype in type_counts:
                    type_counts[atype]["tp"] += 1
            elif not is_actual_anomaly and is_detected:
                fp += 1
            elif not is_actual_anomaly and not is_detected:
                tn += 1
            elif is_actual_anomaly and not is_detected:
                fn += 1
                if atype in type_counts:
                    type_counts[atype]["fn"] += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            (2.0 * precision * recall) / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        total = tp + fp + tn + fn
        accuracy = (tp + tn) / total if total > 0 else 0.0

        # Compute recall by anomaly type
        type_metrics = {}
        for k, v in type_counts.items():
            type_total = v["tp"] + v["fn"]
            type_recall = v["tp"] / type_total if type_total > 0 else 0.0
            type_metrics[k] = {
                "tp": v["tp"],
                "fn": v["fn"],
                "total": type_total,
                "recall": round(type_recall, 4),
            }

        return {
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "accuracy": round(accuracy, 4),
            "metrics_by_type": type_metrics,
        }

    @staticmethod
    def calculate_latency_stats(latencies_ms: List[float]) -> Dict[str, float]:
        """Calculates latency statistics: mean, median, p95, min, max."""
        if not latencies_ms:
            return {
                "latency_mean_ms": 0.0,
                "latency_median_ms": 0.0,
                "latency_p95_ms": 0.0,
                "latency_min_ms": 0.0,
                "latency_max_ms": 0.0,
            }

        arr = np.array(latencies_ms)
        return {
            "latency_mean_ms": round(float(np.mean(arr)), 3),
            "latency_median_ms": round(float(np.median(arr)), 3),
            "latency_p95_ms": round(float(np.percentile(arr, 95)), 3),
            "latency_min_ms": round(float(np.min(arr)), 3),
            "latency_max_ms": round(float(np.max(arr)), 3),
        }

    @staticmethod
    def calculate_bandwidth_reduction(
        cloud_bytes: int,
        distributed_bytes: int,
        cloud_msgs: int,
        distributed_msgs: int,
    ) -> Dict[str, float]:
        """Calculates percentage reduction in bytes and messages transmitted to Cloud."""
        byte_reduction = (
            ((cloud_bytes - distributed_bytes) / cloud_bytes) * 100.0
            if cloud_bytes > 0
            else 0.0
        )
        msg_reduction = (
            ((cloud_msgs - distributed_msgs) / cloud_msgs) * 100.0
            if cloud_msgs > 0
            else 0.0
        )
        return {
            "bandwidth_reduction_percent": round(max(0.0, byte_reduction), 2),
            "message_reduction_percent": round(max(0.0, msg_reduction), 2),
        }
