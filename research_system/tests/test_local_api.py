"""Local vertical-slice tests for durable API state and planner execution."""

import importlib

from fastapi.testclient import TestClient


def _headers(tenant_id="TEN-LOCAL", user_id="user-123"):
    return {"X-Tenant-Id": tenant_id, "X-User-Id": user_id}


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
    headers = _headers(tenant_id)

    with TestClient(main_module.app) as client:
        created = client.post(
            "/api/v1/projects",
            headers=headers,
            json={"name": "Local research"},
        )
        assert created.status_code == 200
        project_id = created.json()["project"]["project_id"]

        run_response = client.post(
            f"/api/v1/projects/{project_id}/runs",
            headers=headers,
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
            headers=headers,
        )
        assert planned.status_code == 200
        assert planned.json()["provider"]["provider"] == "mock"
        assert planned.json()["plan"]["subquestions"]

    # A new lifespan creates new services, proving the data was not process memory.
    with TestClient(main_module.app) as client:
        retrieved = client.get(
            f"/api/v1/projects/{project_id}/runs/{run_id}",
            headers=headers,
        )
        assert retrieved.status_code == 200
        assert retrieved.json()["research_plan"]["search_queries"]

        confirmed = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/confirm-scope",
            headers=headers,
            json={"confirmed": True},
        )
        assert confirmed.status_code == 200

        queued = client.get(
            f"/api/v1/projects/{project_id}/runs/{run_id}",
            headers=headers,
        )
        assert queued.json()["state"] == "queued"

        executed = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/execute-local",
            headers=headers,
        )
        assert executed.status_code == 200
        assert executed.json()["source_count"] >= 1
        assert executed.json()["evidence_count"] >= 1

        synthesized = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/synthesize-local",
            headers=headers,
        )
        assert synthesized.status_code == 200
        assert synthesized.json()["state"] == "reviewing"
        assert synthesized.json()["draft"]["references"]
        assert synthesized.json()["claims"]

        validated = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/validate-citations-local",
            headers=headers,
        )
        assert validated.status_code == 200
        assert validated.json()["passed"] is True
        assert validated.json()["validated_claim_ids"]
        assert validated.json()["findings"] == []

        claim_id = synthesized.json()["claims"][0]["claim_id"]
        claim = main_module.citation_validation_service.store.get(
            "claim", tenant_id, project_id, claim_id
        )
        claim["text"] = "A statement absent from the cited evidence."
        main_module.citation_validation_service.store.put(
            "claim", tenant_id, project_id, claim_id, claim
        )
        invalid = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/validate-citations-local",
            headers=headers,
        )
        assert invalid.status_code == 200
        assert invalid.json()["passed"] is False
        assert invalid.json()["findings"][0]["verdict"] == "insufficient_evidence"

        searched = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/search",
            headers=headers,
            json={"query": "evidence", "limit": 10},
        )
        assert searched.status_code == 200
        assert searched.json()["count"] >= 1

        release = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/release",
            headers=headers,
            json={"approval_id": "APR-NOT-REAL"},
        )
        assert release.status_code == 501
        assert "not implemented" in release.json()["error"].lower()


def test_http_exception_keeps_404_status(tmp_path, monkeypatch):
    main_module = _reload_app(tmp_path / "errors.db", monkeypatch)
    with TestClient(main_module.app) as client:
        response = client.get(
            "/api/v1/projects/PRJ-MISSING", headers=_headers("TEN-LOCAL")
        )

    assert response.status_code == 404
    assert response.json() == {"error": "Project not found", "status_code": 404}


def test_local_auth_rejects_cross_tenant_query_mismatch(tmp_path, monkeypatch):
    main_module = _reload_app(tmp_path / "auth.db", monkeypatch)
    with TestClient(main_module.app) as client:
        response = client.post(
            "/api/v1/projects",
            params={"tenant_id": "TEN-B"},
            headers=_headers("TEN-A"),
            json={"name": "Wrong tenant"},
        )

    assert response.status_code == 403
    assert response.json()["error"] == "Tenant header/query mismatch"


def test_project_membership_is_required_for_run_access(tmp_path, monkeypatch):
    main_module = _reload_app(tmp_path / "membership.db", monkeypatch)
    with TestClient(main_module.app) as client:
        created = client.post(
            "/api/v1/projects",
            headers=_headers("TEN-LOCAL", "owner"),
            json={"name": "Private project"},
        )
        assert created.status_code == 200
        project_id = created.json()["project"]["project_id"]

        response = client.post(
            f"/api/v1/projects/{project_id}/runs",
            headers=_headers("TEN-LOCAL", "outsider"),
            json={
                "title": "Denied",
                "primary_question": "Can outsiders create runs?",
                "scope_description": "Security regression",
            },
        )

    assert response.status_code == 403
    assert response.json()["error"] == "Project role required"


def test_cancelled_run_cannot_be_confirmed_or_executed(tmp_path, monkeypatch):
    main_module = _reload_app(tmp_path / "state.db", monkeypatch)
    headers = _headers("TEN-LOCAL", "owner")
    with TestClient(main_module.app) as client:
        created = client.post(
            "/api/v1/projects",
            headers=headers,
            json={"name": "State project"},
        )
        project_id = created.json()["project"]["project_id"]
        run_response = client.post(
            f"/api/v1/projects/{project_id}/runs",
            headers=headers,
            json={
                "title": "State test",
                "primary_question": "Can cancelled runs revive?",
                "scope_description": "State regression",
            },
        )
        run_id = run_response.json()["run"]["run_id"]
        planned = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/plan",
            headers=headers,
        )
        assert planned.status_code == 200
        cancelled = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/confirm-scope",
            headers=headers,
            json={"confirmed": False, "reason": "no thanks"},
        )
        assert cancelled.status_code == 200

        revived = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/confirm-scope",
            headers=headers,
            json={"confirmed": True},
        )
        executed = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/execute-local",
            headers=headers,
        )

    assert revived.status_code == 409
    assert executed.status_code == 409
