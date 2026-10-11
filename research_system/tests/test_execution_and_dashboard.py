"""Tests for ExecutionQueue, LocalResearchWorker, and Dashboard endpoints."""

import importlib
import time
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from src.execution import ExecutionQueue
from src.local_store import LocalStateStore
from src.models import (
    ResearchRequest,
    RunRecord,
    RunState,
)


def _now():
    return datetime.now(timezone.utc)


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


def test_execution_queue_enqueue_and_claim(tmp_path):
    db_path = tmp_path / "queue-test.db"
    store = LocalStateStore(db_path)
    queue = ExecutionQueue(store)

    tenant_id = "TEN-TEST"
    project_id = "PRJ-001"
    run_id = "RUN-001"

    # 1. Attempt to enqueue a run that doesn't exist -> ValueError
    with pytest.raises(ValueError, match="Create a plan and confirm its scope"):
        queue.enqueue(tenant_id, project_id, run_id, full_text=False)

    # 2. Insert run that is in awaiting_scope_confirmation state -> ValueError
    req = ResearchRequest(
        title="Test Run",
        primary_question="What is the impact of X on Y?",
        scope_description="Testing scope",
        approved_source_domains=[],
        excluded_domains=[],
        max_sources=10,
    )
    run = RunRecord(
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=run_id,
        research_request=req,
        state=RunState.AWAITING_SCOPE_CONFIRMATION,
        configuration_snapshot_id="CFG-1",
        policy_epoch=0,
        start_time=_now(),
        updated_time=_now(),
    )
    store.put("run", tenant_id, project_id, run_id, run.model_dump(mode="json"))

    with pytest.raises(ValueError, match="Create a plan and confirm its scope"):
        queue.enqueue(tenant_id, project_id, run_id, full_text=False)

    # 3. Add plan and set state to queued
    run.state = RunState.QUEUED
    run.research_plan = {"subquestions": ["Q1"], "search_queries": ["query 1"]}
    store.put("run", tenant_id, project_id, run_id, run.model_dump(mode="json"))

    # Attempt full text when approved domains are empty -> ValueError
    with pytest.raises(ValueError, match="approved source domains"):
        queue.enqueue(tenant_id, project_id, run_id, full_text=True)

    # Normal enqueue -> returns job
    job = queue.enqueue(tenant_id, project_id, run_id, full_text=False)
    assert job["status"] == "queued"
    assert job["run_id"] == run_id

    # Run state is transitioned to collecting
    stored_run = store.get("run", tenant_id, project_id, run_id)
    assert stored_run["state"] == "collecting"

    # Enqueue again with same options returns existing job
    job2 = queue.enqueue(tenant_id, project_id, run_id, full_text=False)
    assert job2["run_id"] == run_id

    # Enqueue again with different options raises ValueError
    with pytest.raises(ValueError, match="different execution options"):
        queue.enqueue(tenant_id, project_id, run_id, full_text=True)

    # Claim job by worker
    owner_id = "worker-abc"
    claimed = queue.claim(owner_id)
    assert claimed is not None
    assert claimed["run_id"] == run_id
    assert claimed["status"] == "running"

    # No more queued jobs
    assert queue.claim(owner_id) is None

    # Save job update
    claimed["stage"] = "ingestion"
    claimed["evidence_count"] = 5
    saved = queue.save(claimed, owner_id)
    assert saved is True

    retrieved = queue.get(tenant_id, project_id, run_id)
    assert retrieved["stage"] == "ingestion"
    assert retrieved["evidence_count"] == 5


def test_execution_queue_expired_lease_cleanup(tmp_path):
    db_path = tmp_path / "queue-expired.db"
    store = LocalStateStore(db_path)
    queue = ExecutionQueue(store)

    tenant_id = "TEN-TEST"
    project_id = "PRJ-001"
    run_id = "RUN-EXPIRED"

    req = ResearchRequest(
        title="Expired test",
        primary_question="Test expired leases?",
        scope_description="Testing scope",
    )
    run = RunRecord(
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=run_id,
        research_request=req,
        state=RunState.QUEUED,
        research_plan={"subquestions": ["Q1"], "search_queries": ["query 1"]},
        configuration_snapshot_id="CFG-1",
        policy_epoch=0,
        start_time=_now(),
        updated_time=_now(),
    )
    store.put("run", tenant_id, project_id, run_id, run.model_dump(mode="json"))

    queue.enqueue(tenant_id, project_id, run_id, full_text=False)
    claimed = queue.claim("worker-1")
    assert claimed is not None

    # Simulate expired lease by updating lease_until into the past
    with store._connect() as db:
        db.execute(
            "UPDATE execution_jobs SET lease_until = ? WHERE run_id = ?",
            (time.time() - 10, run_id),
        )

    # Next claim attempt should clean up expired job and fail it
    queue.claim("worker-2")

    job = queue.get(tenant_id, project_id, run_id)
    assert job["status"] == "failed"
    assert job["stage"] == "interrupted"

    updated_run = store.get("run", tenant_id, project_id, run_id)
    assert updated_run["state"] == "failed"


def test_scoped_list_and_compare_run(tmp_path):
    store = LocalStateStore(tmp_path / "scoped.db")

    tenant_id = "TEN-1"
    project_id = "PRJ-1"
    run_1 = "RUN-1"
    run_2 = "RUN-2"

    for r_id in [run_1, run_2]:
        for i in range(3):
            store.put(
                "evidence",
                tenant_id,
                project_id,
                f"EVD-{r_id}-{i}",
                {
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "run_id": r_id,
                    "evidence_id": f"EVD-{r_id}-{i}",
                    "title": f"Study {i}",
                    "passage": f"Passage {i} text for research.",
                    "index": i,
                },
            )

    # Scoped list by run_id
    run1_items = store.scoped_list("evidence", tenant_id, project_id, run_1)
    assert len(run1_items) == 3
    assert all(item["run_id"] == run_1 for item in run1_items)

    run2_items = store.scoped_list("evidence", tenant_id, project_id, run_2)
    assert len(run2_items) == 3
    assert all(item["run_id"] == run_2 for item in run2_items)

    # Pagination
    paged = store.scoped_list("evidence", tenant_id, project_id, run_1, limit=2, offset=1)
    assert len(paged) == 2

    # compare_run optimistic concurrency
    run_payload = {
        "run_id": run_1,
        "state": "collecting",
        "report_revision": 1,
    }
    store.put("run", tenant_id, project_id, run_1, run_payload)

    # Update with matching old_state and revision succeeds
    run_payload["state"] = "synthesizing"
    assert store.compare_run(tenant_id, project_id, run_1, "collecting", run_payload) is True

    # Update with non-matching old_state fails
    run_payload["state"] = "reviewing"
    assert store.compare_run(tenant_id, project_id, run_1, "collecting", run_payload) is False


def test_dashboard_routes_and_execution_endpoints(tmp_path, monkeypatch):
    main_module = _reload_app(tmp_path / "dashboard-test.db", monkeypatch)
    headers = _headers("TEN-DASH", "user-dash")

    with TestClient(main_module.app) as client:
        # Dashboard UI & Static Assets
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "Regula" in resp.text
        assert "/dashboard-assets/app.js" in resp.text

        style_resp = client.get("/dashboard-assets/style.css")
        assert style_resp.status_code == 200
        assert "--accent" in style_resp.text

        js_resp = client.get("/dashboard-assets/app.js")
        assert js_resp.status_code == 200
        assert "regula-identity" in js_resp.text

        # Create Project
        proj_resp = client.post(
            "/api/v1/projects",
            headers=headers,
            json={"name": "Dashboard Project", "description": "Testing UI flows"},
        )
        assert proj_resp.status_code == 200
        project_id = proj_resp.json()["project"]["project_id"]

        # List Projects endpoint (filtered to member user)
        list_resp = client.get("/api/v1/projects", headers=headers)
        assert list_resp.status_code == 200
        projects = list_resp.json()["projects"]
        assert len(projects) == 1
        assert projects[0]["project_id"] == project_id

        # Different user with no membership should not see it
        diff_headers = _headers("TEN-DASH", "other-user")
        diff_list = client.get("/api/v1/projects", headers=diff_headers)
        assert diff_list.status_code == 200
        assert len(diff_list.json()["projects"]) == 0

        # Create Run
        run_resp = client.post(
            f"/api/v1/projects/{project_id}/runs",
            headers=headers,
            json={
                "title": "Async Execution Run",
                "primary_question": "Does async execution work correctly?",
                "scope_description": "Local test scope",
            },
        )
        assert run_resp.status_code == 200
        run_id = run_resp.json()["run"]["run_id"]

        # List Runs endpoint
        runs_list = client.get(f"/api/v1/projects/{project_id}/runs", headers=headers)
        assert runs_list.status_code == 200
        assert len(runs_list.json()["runs"]) == 1
        assert runs_list.json()["runs"][0]["run_id"] == run_id

        # Plan
        plan_resp = client.post(f"/api/v1/projects/{project_id}/runs/{run_id}/plan", headers=headers)
        assert plan_resp.status_code == 200

        # Confirm scope
        confirm_resp = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/confirm-scope",
            headers=headers,
            json={"confirmed": True},
        )
        assert confirm_resp.status_code == 200

        # Execute endpoint (starts background queue processing)
        exec_resp = client.post(
            f"/api/v1/projects/{project_id}/runs/{run_id}/execute",
            headers=headers,
            json={"full_text": False},
        )
        assert exec_resp.status_code == 202
        assert exec_resp.json()["status"] in ["queued", "running", "completed"]

        # Results endpoint
        results_resp = client.get(
            f"/api/v1/projects/{project_id}/runs/{run_id}/results",
            headers=headers,
        )
        assert results_resp.status_code == 200
        res_data = results_resp.json()
        assert "run" in res_data
        assert "execution" in res_data
        assert "draft" in res_data
        assert "evidence" in res_data
        assert "findings" in res_data
