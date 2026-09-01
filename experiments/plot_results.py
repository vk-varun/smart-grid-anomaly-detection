import json
from pathlib import Path
from typing import Optional
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from common.utils import get_project_root


def setup_matplotlib_style():
    """Applies academic styling parameters."""
    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.labelsize": 11,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "figure.titlesize": 14,
        "figure.dpi": 300,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
    })


def generate_all_dissertation_plots(results_dir: Optional[Path] = None):
    """Generates complete set of dissertation-quality plots from experiment result CSVs."""
    setup_matplotlib_style()
    root = get_project_root()
    res_dir = results_dir or (root / "experiments" / "results")
    plots_dir = res_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    summary_file = res_dir / "experiment_summary.csv"
    if not summary_file.exists():
        print(f"[WARNING] {summary_file} not found. Please run experiments first.")
        return

    df = pd.read_csv(summary_file)
    if len(df) == 0:
        print("[WARNING] experiment_summary.csv is empty.")
        return

    # Palette
    color_cloud = "#3498db"      # Blue
    color_dist = "#2ecc71"       # Green
    color_accent = "#e74c3c"     # Red

    # 1. LATENCY COMPARISON
    try:
        latest_runs = df.tail(2)
        fig, ax = plt.subplots(figsize=(7, 4.5))
        archs = latest_runs["architecture"].tolist()
        means = latest_runs["latency_mean_ms"].tolist()
        p95s = latest_runs["latency_p95_ms"].tolist()

        x = np.arange(len(archs))
        width = 0.35

        ax.bar(x - width/2, means, width, label="Mean Latency (ms)", color=color_cloud)
        ax.bar(x + width/2, p95s, width, label="95th Percentile Latency (ms)", color=color_accent)

        ax.set_ylabel("Detection Latency (ms)")
        ax.set_title("Anomaly Detection Latency Comparison")
        ax.set_xticks(x)
        ax.set_xticklabels(["Cloud-Only Baseline", "Edge–Fog–Cloud (Proposed)"])
        ax.legend()
        ax.grid(True, linestyle="--", alpha=0.6)

        for i in range(len(archs)):
            ax.text(x[i] - width/2, means[i] + 0.5, f"{means[i]:.2f}ms", ha="center", va="bottom", fontsize=9)
            ax.text(x[i] + width/2, p95s[i] + 0.5, f"{p95s[i]:.2f}ms", ha="center", va="bottom", fontsize=9)

        fig.savefig(plots_dir / "latency_comparison.png")
        plt.close(fig)
    except Exception as e:
        print(f"Error plotting latency comparison: {e}")

    # 2. BANDWIDTH & DATA TRANSMISSION TO CLOUD
    try:
        fig, ax = plt.subplots(figsize=(7, 4.5))
        latest_runs = df.tail(2)
        bytes_to_cloud_kb = [b / 1024.0 for b in latest_runs["bytes_to_cloud"].tolist()]

        bars = ax.bar(["Cloud-Only Baseline", "Edge–Fog–Cloud (Proposed)"], bytes_to_cloud_kb, color=[color_cloud, color_dist], width=0.5)
        ax.set_ylabel("Data Transmitted to Cloud (KB)")
        ax.set_title("WAN Cloud Data Transmission Volume")
        ax.grid(True, linestyle="--", alpha=0.6)

        if len(bytes_to_cloud_kb) >= 2 and bytes_to_cloud_kb[0] > 0:
            reduction = ((bytes_to_cloud_kb[0] - bytes_to_cloud_kb[1]) / bytes_to_cloud_kb[0]) * 100.0
            ax.text(
                1, bytes_to_cloud_kb[1] + (max(bytes_to_cloud_kb) * 0.05),
                f"↓ {reduction:.1f}% Reduction",
                ha="center", va="bottom", fontweight="bold", color="#27ae60"
            )

        fig.savefig(plots_dir / "bandwidth_transmission_comparison.png")
        plt.close(fig)
    except Exception as e:
        print(f"Error plotting bandwidth comparison: {e}")

    # 3. DETECTION ACCURACY & F1 SCORE
    try:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        latest_runs = df.tail(2)
        metrics = ["precision", "recall", "f1_score", "accuracy"]
        labels = ["Precision", "Recall", "F1-Score", "Accuracy"]
        
        cloud_vals = [latest_runs.iloc[0][m] for m in metrics]
        dist_vals = [latest_runs.iloc[1][m] for m in metrics]

        x = np.arange(len(labels))
        width = 0.35

        ax.bar(x - width/2, cloud_vals, width, label="Cloud-Only Baseline", color=color_cloud)
        ax.bar(x + width/2, dist_vals, width, label="Edge–Fog–Cloud (Proposed)", color=color_dist)

        ax.set_ylabel("Score")
        ax.set_title("Anomaly Detection Classification Performance")
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylim(0, 1.15)
        ax.legend()
        ax.grid(True, linestyle="--", alpha=0.6)

        for i in range(len(labels)):
            ax.text(x[i] - width/2, cloud_vals[i] + 0.02, f"{cloud_vals[i]:.2f}", ha="center", va="bottom", fontsize=8)
            ax.text(x[i] + width/2, dist_vals[i] + 0.02, f"{dist_vals[i]:.2f}", ha="center", va="bottom", fontsize=8)

        fig.savefig(plots_dir / "f1_accuracy_comparison.png")
        plt.close(fig)
    except Exception as e:
        print(f"Error plotting accuracy comparison: {e}")

    print(f"[PLOTS] All dissertation plots successfully generated in: {plots_dir}")


if __name__ == "__main__":
    generate_all_dissertation_plots()
