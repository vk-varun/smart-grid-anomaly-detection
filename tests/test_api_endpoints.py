import pytest
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_api_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"


def test_api_summary(client):
    res = client.get("/api/summary")
    assert res.status_code == 200
    data = res.json()
    assert "total_readings" in data
    assert "bandwidth_reduction_percent" in data


def test_api_grid_status(client):
    res = client.get("/api/grid-status")
    assert res.status_code == 200
    data = res.json()
    assert "stability_status" in data
    assert "avg_frequency" in data
    assert "avg_voltage" in data
    assert "total_load_kw" in data


def test_api_meters_matrix(client):
    res = client.get("/api/meters/matrix")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "meter_id" in data[0]


def test_api_chart_data(client):
    res = client.get("/api/telemetry/chart-data?points=15")
    assert res.status_code == 200
    data = res.json()
    assert "power_kw" in data
    assert "voltage" in data
    assert "frequency" in data


def test_simulation_lifecycle(client):
    start_res = client.post("/api/simulation/start", json={"mode": "distributed", "meters": 10, "anomaly_rate": 0.05})
    assert start_res.status_code == 200

    fault_res = client.post("/api/simulation/inject-fault?fault_type=voltage_spike")
    assert fault_res.status_code == 200

    stabilize_res = client.post("/api/simulation/stabilize")
    assert stabilize_res.status_code == 200
    assert stabilize_res.json()["status"] == "stabilized"

    mode_res = client.post("/api/simulation/set-mode", json={"mode": "cloud_baseline"})
    assert mode_res.status_code == 200
    assert mode_res.json()["current_mode"] == "cloud_baseline"

    speed_res = client.post("/api/simulation/set-speed", json={"speed": 2.0})
    assert speed_res.status_code == 200

    export_res = client.get("/api/simulation/export-csv")
    assert export_res.status_code == 200
    assert "text/csv" in export_res.headers.get("content-type", "")

    stop_res = client.post("/api/simulation/stop")
    assert stop_res.status_code == 200
