from collections import deque
import math
from typing import Dict, List, Optional
import numpy as np
from common.message_schema import MeterReading


class FogFeatureAggregator:
    """
    Maintains temporal rolling windows per meter and computes engineered
    multi-metric features for Fog-layer Isolation Forest detection.
    """

    def __init__(self, window_size: int = 15):
        self.window_size = window_size
        # meter_id -> deque of recent readings
        self.meter_windows: Dict[str, deque] = {}

    def reset(self):
        """Clears buffers."""
        self.meter_windows.clear()

    def add_reading(self, reading: MeterReading) -> Optional[List[float]]:
        """
        Appends reading to meter window and computes feature vector:
        [voltage, current, power_kw, frequency_hz, rolling_mean_power, rolling_std_power, rate_of_change]
        """
        meter_id = reading.meter_id
        if meter_id not in self.meter_windows:
            self.meter_windows[meter_id] = deque(maxlen=self.window_size)

        buf = self.meter_windows[meter_id]
        buf.append(reading)

        if len(buf) < 3:
            return None

        # Compute engineered features
        powers = [r.power_kw for r in buf]
        rolling_mean_p = float(np.mean(powers))
        rolling_std_p = float(np.std(powers))
        
        # Rate of change over last 2 readings
        rate_of_change = (buf[-1].power_kw - buf[-2].power_kw) if len(buf) >= 2 else 0.0

        feature_vector = [
            reading.voltage,
            reading.current,
            reading.power_kw,
            reading.frequency_hz,
            rolling_mean_p,
            rolling_std_p,
            rate_of_change,
        ]
        return feature_vector
