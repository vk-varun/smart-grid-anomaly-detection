from collections import defaultdict
from typing import Dict, List, Optional
from common.message_schema import AggregatedReading, MeterReading


class EdgeDataFilter:
    """
    Manages edge-level data reduction by buffering normal readings
    into periodic aggregated window summaries.
    """

    def __init__(self, edge_id: str, aggregation_window_size: int = 5):
        self.edge_id = edge_id
        self.window_size = aggregation_window_size
        
        # Buffer: meter_id -> List[MeterReading]
        self.normal_buffers: Dict[str, List[MeterReading]] = defaultdict(list)
        
        # Traffic Counters
        self.raw_readings_received = 0
        self.readings_forwarded_individually = 0
        self.readings_aggregated = 0
        self.bytes_in = 0
        self.bytes_out = 0

    def reset(self):
        """Clears state."""
        self.normal_buffers.clear()
        self.raw_readings_received = 0
        self.readings_forwarded_individually = 0
        self.readings_aggregated = 0
        self.bytes_in = 0
        self.bytes_out = 0

    def buffer_normal_reading(self, reading: MeterReading) -> Optional[AggregatedReading]:
        """
        Adds normal reading to buffer. If buffer reaches window_size,
        computes and returns an AggregatedReading.
        """
        self.raw_readings_received += 1
        meter_id = reading.meter_id
        buf = self.normal_buffers[meter_id]
        buf.append(reading)

        if len(buf) >= self.window_size:
            count = len(buf)
            avg_v = sum(r.voltage for r in buf) / count
            avg_i = sum(r.current for r in buf) / count
            avg_p = sum(r.power_kw for r in buf) / count
            avg_f = sum(r.frequency_hz for r in buf) / count
            total_e = buf[-1].energy_kwh - buf[0].energy_kwh

            agg = AggregatedReading(
                edge_id=self.edge_id,
                meter_id=meter_id,
                start_time=buf[0].timestamp,
                end_time=buf[-1].timestamp,
                count=count,
                avg_voltage=round(avg_v, 2),
                avg_current=round(avg_i, 2),
                avg_power_kw=round(avg_p, 3),
                total_energy_kwh=round(max(0.0, total_e), 4),
                avg_frequency_hz=round(avg_f, 2),
            )
            self.readings_aggregated += count
            buf.clear()
            return agg
        return None

    def flush_remaining_aggregations(self) -> List[AggregatedReading]:
        """Flushes any remaining partial window buffers."""
        aggs = []
        for meter_id, buf in list(self.normal_buffers.items()):
            if buf:
                count = len(buf)
                avg_v = sum(r.voltage for r in buf) / count
                avg_i = sum(r.current for r in buf) / count
                avg_p = sum(r.power_kw for r in buf) / count
                avg_f = sum(r.frequency_hz for r in buf) / count
                total_e = buf[-1].energy_kwh - buf[0].energy_kwh

                agg = AggregatedReading(
                    edge_id=self.edge_id,
                    meter_id=meter_id,
                    start_time=buf[0].timestamp,
                    end_time=buf[-1].timestamp,
                    count=count,
                    avg_voltage=round(avg_v, 2),
                    avg_current=round(avg_i, 2),
                    avg_power_kw=round(avg_p, 3),
                    total_energy_kwh=round(max(0.0, total_e), 4),
                    avg_frequency_hz=round(avg_f, 2),
                )
                self.readings_aggregated += count
                aggs.append(agg)
                buf.clear()
        return aggs
