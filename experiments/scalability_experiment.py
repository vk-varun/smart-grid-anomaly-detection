import argparse
from pathlib import Path
import sys
from typing import List

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from common.logging_config import setup_logger
from common.utils import get_project_root
from experiments.plot_results import generate_all_dissertation_plots
from experiments.run_experiment import ControlledExperimentHarness

logger = setup_logger("ScalabilityExperiment")


def run_scalability_benchmark(
    scales: List[int] = [10, 50, 100, 250],
    duration: int = 30,
    seed: int = 42,
):
    """Runs scalability experiments across different fleet sizes."""
    root = get_project_root()
    res_dir = root / "experiments" / "results"
    res_dir.mkdir(parents=True, exist_ok=True)

    benchmark_records = []

    for num_m in scales:
        logger.info(f"\n>>> Running Scalability Benchmark for {num_m} meters...")
        harness = ControlledExperimentHarness(
            num_meters=num_m,
            duration_seconds=duration,
            sampling_interval=1.0,
            anomaly_rate=0.03,
            random_seed=seed,
            results_dir=res_dir,
        )
        res = harness.run_comparative_experiment(base_exp_id=f"scale_{num_m}m")
        cr = res["cloud_report"]
        dr = res["distributed_report"]
        bw = res["bandwidth_reduction"]

        benchmark_records.append({
            "num_meters": num_m,
            "cloud_latency_mean_ms": cr["latency_mean_ms"],
            "dist_latency_mean_ms": dr["latency_mean_ms"],
            "cloud_bytes_to_cloud": cr["bytes_to_cloud"],
            "dist_bytes_to_cloud": dr["bytes_to_cloud"],
            "bandwidth_reduction_pct": bw["bandwidth_reduction_percent"],
            "cloud_f1": cr["f1_score"],
            "dist_f1": dr["f1_score"],
            "cloud_throughput": cr["throughput_readings_per_sec"],
            "dist_throughput": dr["throughput_readings_per_sec"],
            "cloud_cpu_pct": cr["avg_cpu_percent"],
            "dist_cpu_pct": dr["avg_cpu_percent"],
            "cloud_mem_mb": cr["avg_memory_mb"],
            "dist_mem_mb": dr["avg_memory_mb"],
        })

    b_df = pd.DataFrame(benchmark_records)
    b_path = res_dir / "scalability_benchmark.csv"
    b_df.to_csv(b_path, index=False)
    logger.info(f"\nScalability Benchmark completed. Saved to {b_path}")
    print("\n--- SCALABILITY BENCHMARK RESULTS ---")
    print(b_df[["num_meters", "cloud_latency_mean_ms", "dist_latency_mean_ms", "bandwidth_reduction_pct", "dist_f1"]].to_string(index=False))

    generate_all_dissertation_plots(res_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scalability Benchmark Runner")
    parser.add_argument("--duration", type=int, default=30, help="Duration in seconds per scale test")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()
    run_scalability_benchmark(scales=[10, 50, 100, 250], duration=args.duration, seed=args.seed)
