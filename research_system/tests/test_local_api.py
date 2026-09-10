"""Local vertical-slice tests for durable API state and planner execution."""

import importlib

from fastapi.testclient import TestClient


def _reload_app(database_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DB_PATH", str(database_path))
    monkeypatch.setenv("MODEL_PROVIDER", "mock")

    from src.config import get_api_config, get_azure_config, get_model_config

    get_api_config.cache_clear()
    get_azure_config.cache_clear()
    get_model_config.cache_clear()

    import src.main as main_module

    return importlib.reload(main_module)


def test_project_run_and_mock_plan_survive_service_restart(tmp_path, monkeypatch):
    main_module = _reload_app(tmp_path / "research-system.db", monkeypatch)
    tenant_id = "TEN-LOCAL"

    with TestClient(main_module.app) as client:
        created = client.post(
            "/api/v1/projects",
            params={"tenant_id": tenant_id},
            json={"name": "Local research"},
        )
        assert created.status_code == 200
        project_id = created.json()["project"]["project_id"]

        run_response = client.post(
            f"/api/v1/projects/{project_id}/runs",
            params={"tenant_id": tenant_id},
            json={
                "title": "Evidence test",
                "primary_question": "Does intervention X improve outcome Y?",
                "scope_description": "Peer-reviewed studies",
            },
        )
        assert run_response.status_code == 200
        run_id = run_response.json()["run"]["run_id"]

        planned = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/plan",
            params={"tenant_id": tenant_id},
        )
        assert planned.status_code == 200
        assert planned.json()["provider"]["provider"] == "mock"
        assert planned.json()["plan"]["subquestions"]

    # A new lifespan creates new services, proving the data was not process memory.
    with TestClient(main_module.app) as client:
        retrieved = client.get(
            f"/api/v1/projects/{project_id}/runs/{run_id}",
            params={"tenant_id": tenant_id},
        )
        assert retrieved.status_code == 200
        assert retrieved.json()["research_plan"]["search_queries"]

        confirmed = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/confirm-scope",
            params={"tenant_id": tenant_id},
            json={"confirmed": True},
        )
        assert confirmed.status_code == 200

        queued = client.get(
            f"/api/v1/projects/{project_id}/runs/{run_id}",
            params={"tenant_id": tenant_id},
        )
        assert queued.json()["state"] == "queued"

        release = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/release",
            params={"tenant_id": tenant_id},
            json={"approval_id": "APR-NOT-REAL"},
        )
        assert release.status_code == 501
        assert "not implemented" in release.json()["error"].lower()


def test_http_exception_keeps_404_status(tmp_path, monkeypatch):
    main_module = _reload_app(tmp_path / "errors.db", monkeypatch)
    with TestClient(main_module.app) as client:
        response = client.get(
            "/api/v1/projects/PRJ-MISSING", params={"tenant_id": "TEN-LOCAL"}
        )

    assert response.status_code == 404
    assert response.json() == {"error": "Project not found", "status_code": 404}
