// Dashboard client-side polling and state rendering

const API_BASE = window.location.origin;

async function fetchSummary() {
  try {
    const res = await fetch(`${API_BASE}/api/summary`);
    if (!res.ok) throw new Error("Summary request failed");
    const data = await res.json();
    
    document.getElementById("kpi-readings").textContent = (data.total_readings || 0).toLocaleString();
    document.getElementById("kpi-anomalies").textContent = (data.total_detections || 0).toLocaleString();
    document.getElementById("kpi-latency").innerHTML = `${data.avg_detection_latency_ms || 0} <span class="unit">ms</span>`;
    document.getElementById("kpi-bandwidth").textContent = `${data.bandwidth_reduction_percent || 0}%`;

    document.getElementById("connection-status").textContent = "API Live (Connected)";
    document.getElementById("connection-status").style.color = "var(--accent-green)";
  } catch (err) {
    document.getElementById("connection-status").textContent = "API Offline";
    document.getElementById("connection-status").style.color = "var(--accent-red)";
  }
}

async function fetchRecentReadings() {
  try {
    const res = await fetch(`${API_BASE}/api/readings/recent?limit=20`);
    if (!res.ok) return;
    const readings = await res.json();
    const tbody = document.getElementById("telemetry-tbody");

    if (!readings || readings.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="placeholder-row">No telemetry readings received yet.</td></tr>';
      return;
    }

    tbody.innerHTML = readings.map(r => {
      const isAnomaly = r.ground_truth_anomaly === 1;
      const statusClass = isAnomaly ? "status-anomaly" : "status-normal";
      const statusText = isAnomaly ? `ANOMALY (${r.ground_truth_type || 'point'})` : "NORMAL";
      const timeStr = r.timestamp ? r.timestamp.split("T")[1].substring(0, 8) : "--";

      return `
        <tr>
          <td>${timeStr}</td>
          <td><strong>${r.meter_id}</strong></td>
          <td>${r.voltage.toFixed(1)}</td>
          <td>${r.current.toFixed(2)}</td>
          <td>${r.power_kw.toFixed(3)}</td>
          <td>${r.frequency_hz.toFixed(2)}</td>
          <td class="${statusClass}">${statusText}</td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    console.error("Telemetry fetch error:", err);
  }
}

async function fetchAnomalies() {
  try {
    const res = await fetch(`${API_BASE}/api/anomalies?limit=20`);
    if (!res.ok) return;
    const anomalies = await res.json();
    const tbody = document.getElementById("anomaly-tbody");

    if (!anomalies || anomalies.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="placeholder-row">No anomalies detected yet.</td></tr>';
      return;
    }

    tbody.innerHTML = anomalies.map(a => {
      let layerClass = "layer-edge";
      if (a.detection_layer === "fog") layerClass = "layer-fog";
      if (a.detection_layer === "cloud_baseline" || a.detection_layer === "cloud") layerClass = "layer-cloud";

      const timeStr = a.detected_at ? a.detected_at.split("T")[1].substring(0, 8) : "--";

      return `
        <tr>
          <td>${timeStr}</td>
          <td><strong>${a.meter_id}</strong></td>
          <td><span class="tag-layer ${layerClass}">${a.detection_layer}</span></td>
          <td>${a.anomaly_type || 'outlier'}</td>
          <td>${a.latency_ms.toFixed(1)} ms</td>
          <td>${(a.confidence * 100).toFixed(0)}%</td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    console.error("Anomaly fetch error:", err);
  }
}

async function fetchComparison() {
  try {
    const res = await fetch(`${API_BASE}/api/experiments/comparison/latest`);
    if (!res.ok) return;
    const data = await res.json();
    const tbody = document.getElementById("comparison-tbody");

    if (data.status !== "success" || !data.runs || data.runs.length < 2) {
      tbody.innerHTML = '<tr><td colspan="4" class="placeholder-row">Run a comparative experiment to see benchmarks.</td></tr>';
      return;
    }

    const cloud = data.runs[0].architecture.includes("cloud") ? data.runs[0] : data.runs[1];
    const dist = data.runs[0].architecture.includes("dist") ? data.runs[0] : data.runs[1];

    const latDiff = (cloud.latency_mean_ms - dist.latency_mean_ms).toFixed(1);
    const bwRedPct = (((cloud.bytes_to_cloud - dist.bytes_to_cloud) / (cloud.bytes_to_cloud || 1)) * 100).toFixed(1);

    tbody.innerHTML = `
      <tr>
        <td><strong>Mean Detection Latency</strong></td>
        <td>${cloud.latency_mean_ms.toFixed(2)} ms (P95: ${cloud.latency_p95_ms.toFixed(2)} ms)</td>
        <td>${dist.latency_mean_ms.toFixed(2)} ms (P95: ${dist.latency_p95_ms.toFixed(2)} ms)</td>
        <td class="gain-positive">↓ ${latDiff} ms Faster (${((latDiff / cloud.latency_mean_ms) * 100).toFixed(0)}%)</td>
      </tr>
      <tr>
        <td><strong>Data Volume Sent to Cloud</strong></td>
        <td>${(cloud.bytes_to_cloud / 1024).toFixed(1)} KB (${cloud.messages_to_cloud} msgs)</td>
        <td>${(dist.bytes_to_cloud / 1024).toFixed(1)} KB (${dist.messages_to_cloud} msgs)</td>
        <td class="gain-positive">↓ ${bwRedPct}% Bandwidth Saved</td>
      </tr>
      <tr>
        <td><strong>Detection F1-Score</strong></td>
        <td>${cloud.f1_score.toFixed(3)} (P: ${cloud.precision.toFixed(2)}, R: ${cloud.recall.toFixed(2)})</td>
        <td>${dist.f1_score.toFixed(3)} (P: ${dist.precision.toFixed(2)}, R: ${dist.recall.toFixed(2)})</td>
        <td>${dist.f1_score >= cloud.f1_score ? '✓ Maintained/Improved' : 'Acceptable Tradeoff'}</td>
      </tr>
      <tr>
        <td><strong>System Throughput</strong></td>
        <td>${cloud.throughput_readings_per_sec.toFixed(1)} readings/sec</td>
        <td>${dist.throughput_readings_per_sec.toFixed(1)} readings/sec</td>
        <td>Distributed Parallelism</td>
      </tr>
    `;
  } catch (err) {
    console.error("Comparison fetch error:", err);
  }
}

function refreshAll() {
  fetchSummary();
  fetchRecentReadings();
  fetchAnomalies();
  fetchComparison();
}

document.getElementById("btn-refresh").addEventListener("click", refreshAll);

// Initial call + periodic 2s polling
refreshAll();
setInterval(refreshAll, 2000);
