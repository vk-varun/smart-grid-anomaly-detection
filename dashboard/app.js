// Smart Grid SCADA & EMS Command Center Application Logic

const API_BASE = window.location.origin;

let loadChartInstance = null;
let freqVoltageChartInstance = null;
let isSimulationActive = false;
let audioEnabled = true;
let lastKnownAnomalyId = null;

// Synthetic Web Audio Alert Beep
function playAlertTone() {
  if (!audioEnabled) return;
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = "sine";
    osc.frequency.setValueAtTime(880, ctx.currentTime); // A5
    osc.frequency.exponentialRampToValueAtTime(440, ctx.currentTime + 0.15); // Drop to A4

    gain.gain.setValueAtTime(0.12, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.18);

    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start();
    osc.stop(ctx.currentTime + 0.2);
  } catch (e) {
    // Audio may be blocked by autoplay policies until user interaction
  }
}

// Clock Updater
function updateClock() {
  const now = new Date();
  const utcString = now.toUTCString().split(" ")[4];
  const clockEl = document.getElementById("scada-time");
  if (clockEl) clockEl.textContent = utcString;
}
setInterval(updateClock, 1000);
updateClock();

// Chart Initialization
function initCharts() {
  const loadCtx = document.getElementById("loadChart");
  const fvCtx = document.getElementById("freqVoltageChart");

  if (!loadCtx || !fvCtx || typeof Chart === "undefined") return;

  // Chart 1: Active Power Load Curve
  loadChartInstance = new Chart(loadCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Active Load (kW)",
          data: [],
          borderColor: "#00f0ff",
          backgroundColor: "rgba(0, 240, 255, 0.08)",
          borderWidth: 2,
          fill: true,
          tension: 0.35,
          pointRadius: 2,
          pointHoverRadius: 6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: {
          grid: { color: "rgba(255, 255, 255, 0.05)" },
          ticks: { color: "#64748b", font: { family: "JetBrains Mono", size: 9 }, maxTicksLimit: 8 },
        },
        y: {
          grid: { color: "rgba(255, 255, 255, 0.05)" },
          ticks: { color: "#64748b", font: { family: "JetBrains Mono", size: 9 } },
          suggestedMin: 0.2,
          suggestedMax: 2.5,
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#090f1d",
          titleColor: "#00f0ff",
          bodyFont: { family: "JetBrains Mono" },
          borderColor: "rgba(0, 240, 255, 0.4)",
          borderWidth: 1,
        },
      },
    },
  });

  // Chart 2: Voltage & Frequency Curves
  freqVoltageChartInstance = new Chart(fvCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Bus Voltage (V)",
          data: [],
          borderColor: "#38bdf8",
          borderWidth: 2,
          tension: 0.3,
          pointRadius: 0,
          yAxisID: "yVoltage",
        },
        {
          label: "Grid Frequency (Hz)",
          data: [],
          borderColor: "#a855f7",
          borderWidth: 2,
          borderDash: [4, 4],
          tension: 0.3,
          pointRadius: 0,
          yAxisID: "yFreq",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: {
          grid: { color: "rgba(255, 255, 255, 0.05)" },
          ticks: { color: "#64748b", font: { family: "JetBrains Mono", size: 9 }, maxTicksLimit: 8 },
        },
        yVoltage: {
          type: "linear",
          position: "left",
          min: 210,
          max: 250,
          grid: { color: "rgba(255, 255, 255, 0.04)" },
          ticks: { color: "#38bdf8", font: { family: "JetBrains Mono", size: 9 } },
        },
        yFreq: {
          type: "linear",
          position: "right",
          min: 49.6,
          max: 50.4,
          grid: { drawOnChartArea: false },
          ticks: { color: "#a855f7", font: { family: "JetBrains Mono", size: 9 } },
        },
      },
      plugins: {
        legend: {
          display: true,
          labels: { color: "#94a3b8", font: { family: "JetBrains Mono", size: 10 }, boxWidth: 12 },
        },
        tooltip: {
          backgroundColor: "#090f1d",
          bodyFont: { family: "JetBrains Mono" },
          borderColor: "rgba(168, 85, 247, 0.4)",
          borderWidth: 1,
        },
      },
    },
  });
}

// Fetch and Update Grid SCADA Status
async function updateGridStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/grid-status`);
    if (!res.ok) return;
    const data = await res.json();

    // Frequency
    const freqEl = document.getElementById("strip-frequency");
    const freqDevEl = document.getElementById("strip-frequency-dev");
    const freqBar = document.getElementById("gauge-freq-bar");
    if (freqEl) freqEl.innerHTML = `${data.avg_frequency.toFixed(2)} <span class="unit">Hz</span>`;
    if (freqDevEl) {
      const sign = data.frequency_deviation >= 0 ? "+" : "";
      freqDevEl.textContent = `Δf: ${sign}${data.frequency_deviation.toFixed(3)} Hz`;
    }
    if (freqBar) {
      const pct = Math.min(100, Math.max(0, ((data.avg_frequency - 49.5) / 1.0) * 100));
      freqBar.style.width = `${pct}%`;
    }

    // Voltage
    const voltEl = document.getElementById("strip-voltage");
    const voltRangeEl = document.getElementById("strip-voltage-range");
    const voltBar = document.getElementById("gauge-voltage-bar");
    if (voltEl) voltEl.innerHTML = `${data.avg_voltage.toFixed(1)} <span class="unit">V</span>`;
    if (voltRangeEl) voltRangeEl.textContent = `Min: ${data.min_voltage}V | Max: ${data.max_voltage}V`;
    if (voltBar) {
      const pct = Math.min(100, Math.max(0, ((data.avg_voltage - 200) / 60) * 100));
      voltBar.style.width = `${pct}%`;
    }

    // Load
    const loadEl = document.getElementById("strip-load");
    if (loadEl) loadEl.innerHTML = `${data.total_load_kw.toFixed(2)} <span class="unit">kW</span>`;

    // Latency
    const latEl = document.getElementById("strip-latency");
    const latCloudEl = document.getElementById("strip-cloud-lat-compare");
    if (latEl) latEl.innerHTML = `${data.avg_latency_edge_ms.toFixed(1)} <span class="unit">ms</span>`;
    if (latCloudEl) latCloudEl.textContent = `vs. Cloud: ${data.avg_latency_cloud_ms.toFixed(1)} ms`;

    // Status Badge
    const statusBadge = document.getElementById("grid-status-badge");
    const statusText = document.getElementById("grid-status-text");
    if (statusBadge && statusText) {
      statusText.textContent = data.status_label;
      statusBadge.className = "grid-status-pill";
      if (data.stability_status === "NOMINAL_STABLE") {
        statusBadge.classList.add("status-nominal");
      } else if (data.stability_status === "TRANSIENT_WARNING") {
        statusBadge.classList.add("status-warning");
      } else {
        statusBadge.classList.add("status-critical");
        playAlertTone();
      }
    }
  } catch (err) {
    console.error("Grid status error:", err);
  }
}

// Fetch and Update Summary
async function updateSummary() {
  try {
    const res = await fetch(`${API_BASE}/api/summary`);
    if (!res.ok) return;
    const data = await res.json();

    const rdCountEl = document.getElementById("strip-readings-count");
    if (rdCountEl) rdCountEl.textContent = `${(data.total_readings || 0).toLocaleString()} Readings Ingested`;

    const bwEl = document.getElementById("strip-bandwidth");
    const bwBar = document.getElementById("gauge-bw-bar");
    if (bwEl) bwEl.innerHTML = `${data.bandwidth_reduction_percent.toFixed(1)}<span class="unit">%</span>`;
    if (bwBar) bwBar.style.width = `${data.bandwidth_reduction_percent}%`;

    // Update simulation button state
    isSimulationActive = Boolean(data.simulation_running);
    const btnStream = document.getElementById("btn-stream-text");
    const btnStreamIcon = document.querySelector("#btn-stream-toggle .btn-icon");
    if (btnStream && btnStreamIcon) {
      if (isSimulationActive) {
        btnStream.textContent = "STOP LIVE STREAM";
        btnStreamIcon.textContent = "⏹";
        document.getElementById("btn-stream-toggle").classList.add("btn-scada-danger");
        document.getElementById("btn-stream-toggle").classList.remove("btn-scada-primary");
      } else {
        btnStream.textContent = "START LIVE STREAM";
        btnStreamIcon.textContent = "▶";
        document.getElementById("btn-stream-toggle").classList.remove("btn-scada-danger");
        document.getElementById("btn-stream-toggle").classList.add("btn-scada-primary");
      }
    }
  } catch (err) {
    console.error("Summary error:", err);
  }
}

// Update Chart Series
async function updateChartSeries() {
  try {
    const res = await fetch(`${API_BASE}/api/telemetry/chart-data?points=35`);
    if (!res.ok) return;
    const data = await res.json();

    if (loadChartInstance && data.timestamps && data.timestamps.length > 0) {
      loadChartInstance.data.labels = data.timestamps;
      loadChartInstance.data.datasets[0].data = data.power_kw;
      loadChartInstance.update();
    }

    if (freqVoltageChartInstance && data.timestamps && data.timestamps.length > 0) {
      freqVoltageChartInstance.data.labels = data.timestamps;
      freqVoltageChartInstance.data.datasets[0].data = data.voltage;
      freqVoltageChartInstance.data.datasets[1].data = data.frequency;
      freqVoltageChartInstance.update();
    }
  } catch (err) {
    console.error("Chart update error:", err);
  }
}

// Update Meter Matrix (50 Nodes)
async function updateMeterMatrix() {
  try {
    const res = await fetch(`${API_BASE}/api/meters/matrix`);
    if (!res.ok) return;
    const meters = await res.json();
    const container = document.getElementById("meter-matrix-grid");
    if (!container || !meters) return;

    container.innerHTML = meters.map(m => {
      const isAnomaly = m.status === "ANOMALY";
      const cellClass = isAnomaly ? "meter-cell cell-anomaly" : "meter-cell cell-normal";
      const statusText = isAnomaly ? (m.anomaly_type ? m.anomaly_type.toUpperCase() : "FAULT") : "OK";
      const meterShort = m.meter_id.replace("meter_", "M-");

      return `
        <div class="${cellClass}" title="${m.meter_id}: ${m.voltage}V | ${m.current}A | ${m.power_kw}kW">
          <div class="meter-cell-id">${meterShort}</div>
          <div class="meter-cell-val">${m.power_kw.toFixed(2)}<span style="font-size:8px;">kW</span></div>
          <div class="meter-cell-status">${statusText}</div>
        </div>
      `;
    }).join("");
  } catch (err) {
    console.error("Meter matrix error:", err);
  }
}

// Update Recent Telemetry Table
async function updateTelemetryTable() {
  try {
    const res = await fetch(`${API_BASE}/api/readings/recent?limit=25`);
    if (!res.ok) return;
    const readings = await res.json();
    const tbody = document.getElementById("telemetry-tbody");
    if (!tbody) return;

    if (!readings || readings.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="placeholder-row">Awaiting smart meter stream...</td></tr>';
      return;
    }

    tbody.innerHTML = readings.map(r => {
      const isAnomaly = r.ground_truth_anomaly === 1;
      const statusText = isAnomaly ? `<span style="color:#ef4444;font-weight:700;">FAULT (${r.ground_truth_type || 'point'})</span>` : `<span style="color:#10b981;">NOMINAL</span>`;
      const timeStr = r.timestamp && r.timestamp.includes("T") ? r.timestamp.split("T")[1].substring(0, 8) : r.timestamp;

      return `
        <tr>
          <td>${timeStr}</td>
          <td><strong style="color:#38bdf8;">${r.meter_id}</strong></td>
          <td>${r.voltage.toFixed(1)}</td>
          <td>${r.current.toFixed(2)}</td>
          <td>${r.power_kw.toFixed(3)}</td>
          <td>${r.frequency_hz.toFixed(2)}</td>
          <td>${statusText}</td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    console.error("Telemetry table error:", err);
  }
}

// Update Anomaly Stream Table
async function updateAnomalyTable() {
  try {
    const res = await fetch(`${API_BASE}/api/anomalies?limit=25`);
    if (!res.ok) return;
    const anomalies = await res.json();
    const tbody = document.getElementById("anomaly-tbody");
    const badge = document.getElementById("anomalies-total-badge");
    if (!tbody) return;

    if (badge) badge.textContent = `${anomalies.length} Detected`;

    if (!anomalies || anomalies.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="placeholder-row">No anomalies detected. Grid operating normally.</td></tr>';
      return;
    }

    // Play tone on fresh anomaly
    if (anomalies[0].detection_id !== lastKnownAnomalyId) {
      lastKnownAnomalyId = anomalies[0].detection_id;
      playAlertTone();
    }

    tbody.innerHTML = anomalies.map(a => {
      let tagClass = "tag-edge";
      if (a.detection_layer === "fog") tagClass = "tag-fog";
      if (a.detection_layer.includes("cloud")) tagClass = "tag-cloud";

      const timeStr = a.detected_at && a.detected_at.includes("T") ? a.detected_at.split("T")[1].substring(0, 8) : a.detected_at;

      return `
        <tr>
          <td style="color:#cbd5e1;">${timeStr}</td>
          <td><strong style="color:#f87171;">${a.meter_id}</strong></td>
          <td><span class="tag-tier ${tagClass}">${a.detection_layer}</span></td>
          <td style="color:#f59e0b;font-weight:600;">${a.anomaly_type || 'outlier'}</td>
          <td><span style="color:#00f0ff;">${a.latency_ms.toFixed(1)} ms</span></td>
          <td>${(a.confidence * 100).toFixed(0)}%</td>
        </tr>
      `;
    }).join("");
  } catch (err) {
    console.error("Anomaly table error:", err);
  }
}

// Update Comparative Benchmark Matrix
async function updateBenchmarkMatrix() {
  try {
    const res = await fetch(`${API_BASE}/api/experiments/comparison/latest`);
    if (!res.ok) return;
    const data = await res.json();
    const tbody = document.getElementById("comparison-tbody");
    if (!tbody || !data.runs || data.runs.length < 2) return;

    const cloud = data.runs[0].architecture.includes("cloud") ? data.runs[0] : data.runs[1];
    const dist = data.runs[0].architecture.includes("dist") ? data.runs[0] : data.runs[1];

    const latSpeedup = (cloud.latency_mean_ms / dist.latency_mean_ms).toFixed(1);
    const bwSavings = (((cloud.bytes_to_cloud - dist.bytes_to_cloud) / (cloud.bytes_to_cloud || 1)) * 100).toFixed(1);

    tbody.innerHTML = `
      <tr>
        <td><strong>Detection Latency (Mean)</strong></td>
        <td>${cloud.latency_mean_ms.toFixed(2)} ms (P95: ${cloud.latency_p95_ms.toFixed(2)} ms)</td>
        <td><strong>${dist.latency_mean_ms.toFixed(2)} ms</strong> (P95: ${dist.latency_p95_ms.toFixed(2)} ms)</td>
        <td class="advantage-gain">↓ ${(cloud.latency_mean_ms - dist.latency_mean_ms).toFixed(1)} ms Faster (${latSpeedup}x Speedup at Edge)</td>
      </tr>
      <tr>
        <td><strong>Data Volume Sent to Cloud (WAN Traffic)</strong></td>
        <td>${(cloud.bytes_to_cloud / 1024).toFixed(1)} KB (${cloud.messages_to_cloud} msgs)</td>
        <td><strong>${(dist.bytes_to_cloud / 1024).toFixed(1)} KB</strong> (${dist.messages_to_cloud} msgs)</td>
        <td class="advantage-gain">↓ ${bwSavings}% Bandwidth Eliminated (Edge Window Filtering)</td>
      </tr>
      <tr>
        <td><strong>Anomaly Detection Accuracy (F1-Score)</strong></td>
        <td>${cloud.f1_score.toFixed(3)} (P: ${cloud.precision.toFixed(2)}, R: ${cloud.recall.toFixed(2)})</td>
        <td><strong>${dist.f1_score.toFixed(3)}</strong> (P: ${dist.precision.toFixed(2)}, R: ${dist.recall.toFixed(2)})</td>
        <td class="advantage-gain">✓ Maintained High Precision & Recall Across Tiers</td>
      </tr>
      <tr>
        <td><strong>System Processing Throughput</strong></td>
        <td>${cloud.throughput_readings_per_sec.toFixed(1)} readings/sec</td>
        <td><strong>${dist.throughput_readings_per_sec.toFixed(1)} readings/sec</strong></td>
        <td>Parallel Processing Across 3 Edge Nodes + Fog IsolationForest</td>
      </tr>
    `;
  } catch (err) {
    console.error("Benchmark update error:", err);
  }
}

// Controller Actions Setup
function setupControls() {
  // Start/Stop Live Simulation
  const streamBtn = document.getElementById("btn-stream-toggle");
  if (streamBtn) {
    streamBtn.addEventListener("click", async () => {
      try {
        if (!isSimulationActive) {
          await fetch(`${API_BASE}/api/simulation/start`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode: "distributed", meters: 50, anomaly_rate: 0.04 }),
          });
        } else {
          await fetch(`${API_BASE}/api/simulation/stop`, { method: "POST" });
        }
        updateSummary();
      } catch (err) {
        console.error("Stream toggle error:", err);
      }
    });
  }

  // Inject Grid Fault
  const injectBtn = document.getElementById("btn-inject-fault");
  if (injectBtn) {
    injectBtn.addEventListener("click", async () => {
      const select = document.getElementById("fault-type-select");
      const faultType = select ? select.value : "voltage_spike";
      try {
        await fetch(`${API_BASE}/api/simulation/inject-fault?fault_type=${encodeURIComponent(faultType)}`, {
          method: "POST",
        });
        playAlertTone();
      } catch (err) {
        console.error("Inject fault error:", err);
      }
    });
  }

  // Reset Database
  const resetBtn = document.getElementById("btn-reset-db");
  if (resetBtn) {
    resetBtn.addEventListener("click", async () => {
      if (confirm("Reset telemetry database and clear all current readings?")) {
        try {
          await fetch(`${API_BASE}/api/database/reset`, { method: "POST" });
          refreshAll();
        } catch (err) {
          console.error("Reset db error:", err);
        }
      }
    });
  }

  // Audio Alert Toggle
  const audioBtn = document.getElementById("btn-audio-toggle");
  if (audioBtn) {
    audioBtn.addEventListener("click", () => {
      audioEnabled = !audioEnabled;
      const icon = document.getElementById("audio-icon");
      if (icon) icon.textContent = audioEnabled ? "🔔" : "🔕";
    });
  }
}

// Master Refresh
function refreshAll() {
  updateGridStatus();
  updateSummary();
  updateChartSeries();
  updateMeterMatrix();
  updateTelemetryTable();
  updateAnomalyTable();
  updateBenchmarkMatrix();
}

// Initialization on DOM Loaded
document.addEventListener("DOMContentLoaded", () => {
  initCharts();
  setupControls();
  refreshAll();
  // Poll every 1.5 seconds for real-time SCADA feel
  setInterval(refreshAll, 1500);
});
