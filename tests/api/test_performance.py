from __future__ import annotations

from fastapi.testclient import TestClient

from local_meeting_ai.api import routes


def test_performance_endpoint_returns_only_compact_read_only_metrics(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        routes,
        "_sidebar_memory_status",
        lambda: {
            "total_bytes": 16_000,
            "available_bytes": 7_000,
            "used_bytes": 9_000,
            "percent": 56.25,
            "process_bytes": 1_200,
        },
    )

    response = client.get("/api/system/performance")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "total_bytes": 16_000,
        "available_bytes": 7_000,
        "used_bytes": 9_000,
        "percent": 56.25,
        "process_bytes": 1_200,
        "logical_cpu_count": routes.os.cpu_count(),
        "cpu_usage_percent": None,
        "cpu_usage_available": False,
    }
    assert not any("path" in key.lower() for key in payload)


def test_performance_endpoint_handles_unavailable_memory_metrics(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        routes,
        "_sidebar_memory_status",
        lambda: {
            "total_bytes": None,
            "available_bytes": None,
            "used_bytes": None,
            "percent": None,
            "process_bytes": None,
        },
    )

    response = client.get("/api/system/performance")

    assert response.status_code == 200
    assert response.json()["process_bytes"] is None
    assert response.json()["available_bytes"] is None
