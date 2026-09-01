from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml


def get_project_root() -> Path:
    """Returns the absolute Path of the project root directory."""
    return Path(__file__).resolve().parent.parent


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Loads configuration from YAML file with fallback to default config.yaml."""
    if config_path is None:
        target = get_project_root() / "config.yaml"
    else:
        target = Path(config_path)
        if not target.is_absolute():
            target = get_project_root() / target

    if not target.exists():
        raise FileNotFoundError(f"Configuration file not found at {target}")

    with open(target, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config or {}


def parse_iso_timestamp(ts_str: str) -> datetime:
    """Parses an ISO-8601 string to a timezone-aware UTC datetime."""
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


def calculate_latency_ms(source_ts_str: str, current_dt: Optional[datetime] = None) -> float:
    """Calculates latency in milliseconds between source ISO timestamp and current UTC time."""
    if current_dt is None:
        current_dt = datetime.now(timezone.utc)
    source_dt = parse_iso_timestamp(source_ts_str)
    diff = (current_dt - source_dt).total_seconds() * 1000.0
    return max(0.0, diff)
