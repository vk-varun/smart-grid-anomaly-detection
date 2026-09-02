import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import psutil

from cloud.baseline_detector import CloudBaselineDetector
from cloud.database import DatabaseManager
from common.logging_config import setup_logger
from common.message_schema import (
    AnomalyDetectionResult,
    EdgeForwardPayload,
    FogForwardPayload,
    MeterReading,
)
from common.metrics import ExperimentEvaluationReport, MetricsCalculator
from common.utils import calculate_latency_ms, get_project_root, load_config
from edge.detector import EdgeZScoreDetector
from edge.filter import EdgeDataFilter
from fog.detector import FogIsolationForestDetector
from simulator.anomaly_generator import AnomalyGenerator
from simulator.data_generator import create_meter_fleet
from simulator.meter_simulator import SmartMeterSimulator


logger = setup_logger("ExperimentRunner")


class ControlledExperimentHarness:
    """
    Executes fair, controlled, reproducible comparative experiments
    between Cloud-only Baseline and Proposed Edge-Fog-Cloud architecture.
    """

    def __init__(
        self,
        num_meters: int = 50,
        duration_seconds: int = 60,
        sampling_interval: float = 1.0,
        anomaly_rate: float = 0.03,
        random_seed: int = 42,
        results_dir: Optional[Path] = None,
        db_path: Optional[str] = None,
    ):
        self.num_meters = num_meters
        self.duration_seconds = duration_seconds
        self.sampling_interval = sampling_interval
        self.anomaly_rate = anomaly_rate
        self.random_seed = random_seed

        self.root = get_project_root()
        self.results_dir = results_dir or (self.root / "experiments" / "results")
        self.results_dir.mkdir(parents=True, exist_ok=True)
        (self.results_dir / "plots").mkdir(parents=True, exist_ok=True)

        self.db = DatabaseManager(db_path)

    def generate_shared_workload(self) -> List[MeterReading]:
        """Generates a deterministic dataset for exact replay across both architectures."""
        logger.info(
            f"Generating shared workload: {self.num_meters} meters, {self.duration_seconds}s duration, "
            f"sampling={self.sampling_interval}s, anomaly_rate={self.anomaly_rate}, seed={self.random_seed}"
        )
        sim = SmartMeterSimulator(
            num_meters=self.num_meters,
            sampling_interval_seconds=self.sampling_interval,
            duration_seconds=self.duration_seconds,
            anomaly_rate=self.anomaly_rate,
            random_seed=self.random_seed,
        )
        workload = sim.generate_all_readings_offline()
        logger.info(f"Shared workload ready: {len(workload)} total readings generated.")
        return workload

    def run_cloud_baseline(
        self,
        workload: List[MeterReading],
        experiment_id: str,
    ) -> Tuple[ExperimentEvaluationReport, List[AnomalyDetectionResult]]:
        """Executes the Cloud-Only Baseline architecture on the shared workload."""
        logger.info(f"Starting Cloud-Only Baseline run for {experiment_id}...")
        self.db.record_experiment_start(
            experiment_id=experiment_id,
            architecture="cloud_baseline",
            num_meters=self.num_meters,
            sampling_interval=self.sampling_interval,
            duration=self.duration_seconds,
            anomaly_rate=self.anomaly_rate,
            random_seed=self.random_seed,
        )

        detector = CloudBaselineDetector(zscore_threshold=3.0, rolling_window_size=15, min_samples=5)
        detections: List[AnomalyDetectionResult] = []
        latencies_ms: List[float] = []

        total_bytes_generated = sum(r.payload_bytes() for r in workload)
        total_msgs_generated = len(workload)
        # In cloud-only baseline, every raw reading travels to the Cloud
        messages_to_cloud = total_msgs_generated
        bytes_to_cloud = total_bytes_generated

        # Resource monitoring
        process = psutil.Process()
        cpu_samples = []
        mem_samples = []

        start_time = time.time()
        for idx, reading in enumerate(workload):
            if idx % 100 == 0:
                cpu_samples.append(process.cpu_percent())
                mem_samples.append(process.memory_info().rss / (1024 * 1024))

            # Store reading in DB
            self.db.insert_reading(reading, experiment_id)

            # Centralized cloud detection
            t0 = time.perf_counter()
            det = detector.process_reading(reading, experiment_id)
            proc_time_ms = (time.perf_counter() - t0) * 1000.0

            if det is not None:
                # Total latency = source network transmission + processing latency
                e2e_latency = calculate_latency_ms(reading.timestamp) + proc_time_ms
                det.latency_ms = round(e2e_latency, 3)
                detections.append(det)
                latencies_ms.append(det.latency_ms)
                self.db.insert_detection(det)

        wall_duration = max(0.001, time.time() - start_time)
        self.db.record_experiment_end(experiment_id)

        # Classification metrics
        class_metrics = MetricsCalculator.calculate_classification_metrics(workload, detections)
        lat_stats = MetricsCalculator.calculate_latency_stats(latencies_ms)
        throughput = len(workload) / wall_duration

        avg_cpu = float(np.mean(cpu_samples)) if cpu_samples else process.cpu_percent()
        peak_cpu = float(np.max(cpu_samples)) if cpu_samples else avg_cpu
        avg_mem = float(np.mean(mem_samples)) if mem_samples else (process.memory_info().rss / (1024 * 1024))
        peak_mem = float(np.max(mem_samples)) if mem_samples else avg_mem

        report = ExperimentEvaluationReport(
            experiment_id=experiment_id,
            architecture="cloud_baseline",
            total_readings=len(workload),
            duration_seconds=round(wall_duration, 2),
            true_positives=class_metrics["true_positives"],
            false_positives=class_metrics["false_positives"],
            true_negatives=class_metrics["true_negatives"],
            false_negatives=class_metrics["false_negatives"],
            precision=class_metrics["precision"],
            recall=class_metrics["recall"],
            f1_score=class_metrics["f1_score"],
            accuracy=class_metrics["accuracy"],
            metrics_by_type=class_metrics["metrics_by_type"],
            latency_mean_ms=lat_stats["latency_mean_ms"],
            latency_median_ms=lat_stats["latency_median_ms"],
            latency_p95_ms=lat_stats["latency_p95_ms"],
            latency_min_ms=lat_stats["latency_min_ms"],
            latency_max_ms=lat_stats["latency_max_ms"],
            total_messages_generated=total_msgs_generated,
            total_bytes_generated=total_bytes_generated,
            messages_to_cloud=messages_to_cloud,
            bytes_to_cloud=bytes_to_cloud,
            throughput_readings_per_sec=round(throughput, 2),
            avg_cpu_percent=round(avg_cpu, 2),
            peak_cpu_percent=round(peak_cpu, 2),
            avg_memory_mb=round(avg_mem, 2),
            peak_memory_mb=round(peak_mem, 2),
        )
        return report, detections

    def run_distributed_pipeline(
        self,
        workload: List[MeterReading],
        experiment_id: str,
        num_edge_nodes: int = 3,
    ) -> Tuple[ExperimentEvaluationReport, List[AnomalyDetectionResult]]:
        """Executes the proposed Edge-Fog-Cloud distributed architecture on the shared workload."""
        logger.info(f"Starting Distributed Edge-Fog-Cloud run for {experiment_id}...")
        self.db.record_experiment_start(
            experiment_id=experiment_id,
            architecture="distributed",
            num_meters=self.num_meters,
            sampling_interval=self.sampling_interval,
            duration=self.duration_seconds,
            anomaly_rate=self.anomaly_rate,
            random_seed=self.random_seed,
        )

        # 1. Setup Edge Nodes with meter partition mapping
        all_meters = sorted(list({r.meter_id for r in workload}))
        edge_nodes = {}
        for i in range(num_edge_nodes):
            edge_id = f"edge_{i+1:02d}"
            assigned = {m for idx, m in enumerate(all_meters) if (idx % num_edge_nodes) == i}
            edge_nodes[edge_id] = {
                "detector": EdgeZScoreDetector(zscore_threshold=3.0, rolling_window_size=10, min_samples=5),
                "filter": EdgeDataFilter(edge_id=edge_id, aggregation_window_size=5),
                "assigned": assigned,
            }

        # 2. Setup Fog Node
        fog_detector = FogIsolationForestDetector(contamination=self.anomaly_rate, random_state=self.random_seed)

        # Tracking collections
        all_detections: List[AnomalyDetectionResult] = []
        latencies_ms: List[float] = []
        
        # Traffic Counters
        total_msgs_generated = len(workload)
        total_bytes_generated = sum(r.payload_bytes() for r in workload)
        messages_to_cloud = 0
        bytes_to_cloud = 0

        # Resource monitoring
        process = psutil.Process()
        cpu_samples = []
        mem_samples = []

        start_time = time.time()

        for idx, reading in enumerate(workload):
            if idx % 100 == 0:
                cpu_samples.append(process.cpu_percent())
                mem_samples.append(process.memory_info().rss / (1024 * 1024))

            # Determine responsible Edge node
            assigned_edge_id = f"edge_{(all_meters.index(reading.meter_id) % num_edge_nodes) + 1:02d}"
            edge_inst = edge_nodes[assigned_edge_id]
            edge_det = edge_inst["detector"]
            edge_filt = edge_inst["filter"]

            # Edge Processing Pipeline
            t0 = time.perf_counter()
            d_edge = edge_det.process(reading, experiment_id=experiment_id, edge_id=assigned_edge_id)
            edge_proc_ms = (time.perf_counter() - t0) * 1000.0

            if d_edge is not None:
                # Immediate Edge detection
                e2e_lat = calculate_latency_ms(reading.timestamp) + edge_proc_ms
                d_edge.latency_ms = round(e2e_lat, 3)
                all_detections.append(d_edge)
                latencies_ms.append(d_edge.latency_ms)
                self.db.insert_detection(d_edge)
                self.db.insert_reading(reading, experiment_id)

                # Forwarded payload (individual anomaly) travels to Fog & Cloud
                edge_payload = EdgeForwardPayload(
                    edge_id=assigned_edge_id,
                    individual_readings=[reading],
                    aggregations=[],
                    detections=[d_edge],
                )
                payload_bytes = edge_payload.payload_bytes()
                messages_to_cloud += 1
                bytes_to_cloud += payload_bytes

                # Fog also receives forwarded reading to analyze temporal patterns
                t_fog = time.perf_counter()
                d_fog = fog_detector.process(reading, experiment_id=experiment_id)
                fog_proc_ms = (time.perf_counter() - t_fog) * 1000.0
                if d_fog is not None:
                    d_fog.latency_ms = round(calculate_latency_ms(reading.timestamp) + edge_proc_ms + fog_proc_ms, 3)
                    all_detections.append(d_fog)
                    self.db.insert_detection(d_fog)
            else:
                # Normal reading: aggregated at Edge
                agg = edge_filt.buffer_normal_reading(reading)
                if agg is not None:
                    # Send aggregated window summary instead of raw readings
                    agg_payload = EdgeForwardPayload(
                        edge_id=assigned_edge_id,
                        individual_readings=[],
                        aggregations=[agg],
                        detections=[],
                    )
                    payload_bytes = agg_payload.payload_bytes()
                    messages_to_cloud += 1
                    bytes_to_cloud += payload_bytes

        # Flush remaining edge aggregations
        for edge_id, edge_inst in edge_nodes.items():
            rem_aggs = edge_inst["filter"].flush_remaining_aggregations()
            if rem_aggs:
                agg_payload = EdgeForwardPayload(
                    edge_id=edge_id,
                    individual_readings=[],
                    aggregations=rem_aggs,
                    detections=[],
                )
                messages_to_cloud += 1
                bytes_to_cloud += agg_payload.payload_bytes()

        wall_duration = max(0.001, time.time() - start_time)
        self.db.record_experiment_end(experiment_id)

        # Classification metrics
        class_metrics = MetricsCalculator.calculate_classification_metrics(workload, all_detections)
        lat_stats = MetricsCalculator.calculate_latency_stats(latencies_ms)
        throughput = len(workload) / wall_duration

        avg_cpu = float(np.mean(cpu_samples)) if cpu_samples else process.cpu_percent()
        peak_cpu = float(np.max(cpu_samples)) if cpu_samples else avg_cpu
        avg_mem = float(np.mean(mem_samples)) if mem_samples else (process.memory_info().rss / (1024 * 1024))
        peak_mem = float(np.max(mem_samples)) if mem_samples else avg_mem

        report = ExperimentEvaluationReport(
            experiment_id=experiment_id,
            architecture="distributed",
            total_readings=len(workload),
            duration_seconds=round(wall_duration, 2),
            true_positives=class_metrics["true_positives"],
            false_positives=class_metrics["false_positives"],
            true_negatives=class_metrics["true_negatives"],
            false_negatives=class_metrics["false_negatives"],
            precision=class_metrics["precision"],
            recall=class_metrics["recall"],
            f1_score=class_metrics["f1_score"],
            accuracy=class_metrics["accuracy"],
            metrics_by_type=class_metrics["metrics_by_type"],
            latency_mean_ms=lat_stats["latency_mean_ms"],
            latency_median_ms=lat_stats["latency_median_ms"],
            latency_p95_ms=lat_stats["latency_p95_ms"],
            latency_min_ms=lat_stats["latency_min_ms"],
            latency_max_ms=lat_stats["latency_max_ms"],
            total_messages_generated=total_msgs_generated,
            total_bytes_generated=total_bytes_generated,
            messages_to_cloud=messages_to_cloud,
            bytes_to_cloud=bytes_to_cloud,
            throughput_readings_per_sec=round(throughput, 2),
            avg_cpu_percent=round(avg_cpu, 2),
            peak_cpu_percent=round(peak_cpu, 2),
            avg_memory_mb=round(avg_mem, 2),
            peak_memory_mb=round(peak_mem, 2),
        )
        return report, all_detections

    def run_comparative_experiment(
        self,
        base_exp_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Runs the exact same workload through both Cloud-only and Distributed pipelines."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        exp_id_cloud = f"exp_cloud_{ts}" if base_exp_id is None else f"{base_exp_id}_cloud"
        exp_id_dist = f"exp_dist_{ts}" if base_exp_id is None else f"{base_exp_id}_dist"

        # 1. Generate workload once
        workload = self.generate_shared_workload()

        # 2. Run Cloud-Only Baseline
        report_cloud, dets_cloud = self.run_cloud_baseline(workload, exp_id_cloud)

        # 3. Run Edge-Fog-Cloud Distributed
        report_dist, dets_dist = self.run_distributed_pipeline(workload, exp_id_dist)

        # 4. Compute bandwidth reduction
        bw_res = MetricsCalculator.calculate_bandwidth_reduction(
            cloud_bytes=report_cloud.bytes_to_cloud,
            distributed_bytes=report_dist.bytes_to_cloud,
            cloud_msgs=report_cloud.messages_to_cloud,
            distributed_msgs=report_dist.messages_to_cloud,
        )

        # 5. Export results to CSV
        self.export_results_csv(
            reports=[report_cloud, report_dist],
            all_detections={"cloud": dets_cloud, "distributed": dets_dist},
            bandwidth_comparison=bw_res,
        )

        return {
            "cloud_report": report_cloud.model_dump(),
            "distributed_report": report_dist.model_dump(),
            "bandwidth_reduction": bw_res,
        }

    def export_results_csv(
        self,
        reports: List[ExperimentEvaluationReport],
        all_detections: Dict[str, List[AnomalyDetectionResult]],
        bandwidth_comparison: Dict[str, float],
    ):
        """Saves experiment results into structured CSV files."""
        # 1. experiment_summary.csv
        summary_rows = [r.model_dump() for r in reports]
        summary_df = pd.DataFrame(summary_rows)
        summary_file = self.results_dir / "experiment_summary.csv"
        if summary_file.exists():
            existing = pd.read_csv(summary_file)
            summary_df = pd.concat([existing, summary_df]).drop_duplicates(subset=["experiment_id"], keep="last")
        summary_df.to_csv(summary_file, index=False)

        # 2. bandwidth_results.csv
        bw_file = self.results_dir / "bandwidth_results.csv"
        bw_row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "num_meters": self.num_meters,
            "duration_seconds": self.duration_seconds,
            "cloud_bytes": reports[0].bytes_to_cloud,
            "distributed_bytes": reports[1].bytes_to_cloud,
            "bandwidth_reduction_percent": bandwidth_comparison["bandwidth_reduction_percent"],
            "cloud_messages": reports[0].messages_to_cloud,
            "distributed_messages": reports[1].messages_to_cloud,
            "message_reduction_percent": bandwidth_comparison["message_reduction_percent"],
        }
        bw_df = pd.DataFrame([bw_row])
        if bw_file.exists():
            existing_bw = pd.read_csv(bw_file)
            bw_df = pd.concat([existing_bw, bw_df], ignore_index=True)
        bw_df.to_csv(bw_file, index=False)

        # 3. detection_results.csv
        det_rows = []
        for arch, dets in all_detections.items():
            for d in dets:
                det_rows.append(d.model_dump())
        if det_rows:
            det_df = pd.DataFrame(det_rows)
            det_file = self.results_dir / "detection_results.csv"
            det_df.to_csv(det_file, index=False)

        # 4. resource_metrics.csv
        res_rows = [
            {
                "experiment_id": r.experiment_id,
                "architecture": r.architecture,
                "avg_cpu_percent": r.avg_cpu_percent,
                "peak_cpu_percent": r.peak_cpu_percent,
                "avg_memory_mb": r.avg_memory_mb,
                "peak_memory_mb": r.peak_memory_mb,
                "throughput_per_sec": r.throughput_readings_per_sec,
            }
            for r in reports
        ]
        res_df = pd.DataFrame(res_rows)
        res_file = self.results_dir / "resource_metrics.csv"
        res_df.to_csv(res_file, index=False)

        logger.info(f"Results exported successfully to {self.results_dir}")


def main():
    parser = argparse.ArgumentParser(description="Automated Smart Grid Anomaly Detection Experiment Runner")
    parser.add_argument("--architecture", choices=["cloud", "distributed", "both"], default="both", help="Architecture mode")
    parser.add_argument("--meters", type=int, default=50, help="Number of simulated smart meters")
    parser.add_argument("--duration", type=int, default=60, help="Simulation duration in seconds")
    parser.add_argument("--sampling", type=float, default=1.0, help="Sampling interval in seconds")
    parser.add_argument("--anomaly-rate", type=float, default=0.03, help="Probability of anomaly injection")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--plot", action="store_true", help="Generate dissertation plots after experiment")

    args = parser.parse_args()

    harness = ControlledExperimentHarness(
        num_meters=args.meters,
        duration_seconds=args.duration,
        sampling_interval=args.sampling,
        anomaly_rate=args.anomaly_rate,
        random_seed=args.seed,
    )

    if args.architecture == "both":
        results = harness.run_comparative_experiment()
        print("\n================ EXPERIMENT SUMMARY ================")
        print(f"Meters: {args.meters} | Duration: {args.duration}s | Seed: {args.seed}")
        print("----------------------------------------------------")
        cr = results["cloud_report"]
        dr = results["distributed_report"]
        bw = results["bandwidth_reduction"]
        print(f"Cloud-Only Latency Mean: {cr['latency_mean_ms']} ms (P95: {cr['latency_p95_ms']} ms)")
        print(f"Distributed Latency Mean: {dr['latency_mean_ms']} ms (P95: {dr['latency_p95_ms']} ms)")
        print(f"Cloud-Only Data Volume:  {cr['bytes_to_cloud']:,} bytes ({cr['messages_to_cloud']} msgs)")
        print(f"Distributed Data Volume: {dr['bytes_to_cloud']:,} bytes ({dr['messages_to_cloud']} msgs)")
        print(f"Bandwidth Reduction:     {bw['bandwidth_reduction_percent']}%")
        print(f"Message Reduction:       {bw['message_reduction_percent']}%")
        print(f"Cloud-Only F1 Score:     {cr['f1_score']} (Precision: {cr['precision']}, Recall: {cr['recall']})")
        print(f"Distributed F1 Score:    {dr['f1_score']} (Precision: {dr['precision']}, Recall: {dr['recall']})")
        print("====================================================\n")
    elif args.architecture == "cloud":
        workload = harness.generate_shared_workload()
        rep, dets = harness.run_cloud_baseline(workload, f"exp_cloud_{args.meters}m")
        print(f"Cloud Baseline F1: {rep.f1_score}, Latency: {rep.latency_mean_ms} ms, Bytes: {rep.bytes_to_cloud}")
    else:
        workload = harness.generate_shared_workload()
        rep, dets = harness.run_distributed_pipeline(workload, f"exp_dist_{args.meters}m")
        print(f"Distributed F1: {rep.f1_score}, Latency: {rep.latency_mean_ms} ms, Bytes: {rep.bytes_to_cloud}")

    if args.plot:
        from experiments.plot_results import generate_all_dissertation_plots
        generate_all_dissertation_plots()


if __name__ == "__main__":
    main()
