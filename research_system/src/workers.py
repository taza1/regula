"""In-process background worker that drives a confirmed run through the pipeline.

Single asyncio task, one run at a time, with job status persisted in the local
store. It is the local stand-in for a Service Bus consumer: the queue is lost on
restart, so ``recover`` re-enqueues queued jobs and fails interrupted ones.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from src.audit import AuditService
from src.local_store import LocalStateStore
from src.models import RunState
from src.review_service import ReviewService
from src.services import EvidenceService, ResearchRunService, SynthesisService

logger = logging.getLogger(__name__)

JOB_KIND = "job"


class RunWorker:
    def __init__(
        self,
        store: LocalStateStore,
        evidence_service: EvidenceService,
        synthesis_service: SynthesisService,
        review_service: ReviewService,
    ):
        self.store = store
        self.evidence = evidence_service
        self.synthesis = synthesis_service
        self.review = review_service
        self.runs = ResearchRunService(store)
        self.audit = AuditService(store)
        self._queue: Optional[asyncio.Queue] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._queue = asyncio.Queue()
        self.recover()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def join(self) -> None:
        """Wait until every enqueued job has finished (used by tests)."""
        if self._queue:
            await self._queue.join()

    def get_job(self, tenant_id: str, project_id: str, run_id: str) -> Optional[dict[str, Any]]:
        return self.store.get(JOB_KIND, tenant_id, project_id, run_id)

    async def enqueue(
        self, tenant_id: str, project_id: str, run_id: str, actor: str
    ) -> Optional[dict[str, Any]]:
        """Queue a QUEUED run for background execution; None if not eligible."""

        run = await self.runs.get_run(tenant_id, project_id, run_id)
        if not run or run.state != RunState.QUEUED or not run.research_plan:
            return None
        existing = self.get_job(tenant_id, project_id, run_id)
        if existing and existing["status"] in ("queued", "running"):
            return None
        job = self._save_job(tenant_id, project_id, run_id, "queued", actor=actor)
        self.audit.record(tenant_id, project_id, run_id, actor, "job.queued")
        self._queue.put_nowait((tenant_id, project_id, run_id))
        return job

    def recover(self) -> None:
        """Re-enqueue jobs that never started; fail jobs that were mid-flight."""

        for job in self.store.list_all_tenants(JOB_KIND):
            key = (job["tenant_id"], job["project_id"], job["run_id"])
            if job["status"] == "queued":
                self._queue.put_nowait(key)
            elif job["status"] == "running":
                self._save_job(*key, "failed", error="Interrupted by service restart")

    # ---------------------------------------------------------------- internals

    def _save_job(self, tenant_id, project_id, run_id, status, actor=None, error=None, state=None):
        previous = self.store.get(JOB_KIND, tenant_id, project_id, run_id) or {}
        job = {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "run_id": run_id,
            "status": status,
            "actor": actor or previous.get("actor", "system"),
            "error": error,
            "final_state": state,
            "queued_at": previous.get("queued_at", datetime.utcnow().isoformat()),
            "updated_at": datetime.utcnow().isoformat(),
        }
        self.store.put(JOB_KIND, tenant_id, project_id, run_id, job)
        return job

    async def _loop(self) -> None:
        while True:
            tenant_id, project_id, run_id = await self._queue.get()
            try:
                await self._process(tenant_id, project_id, run_id)
            except Exception as error:  # noqa: BLE001 - a job must never kill the loop
                logger.exception("Background run %s failed", run_id)
                await self._fail(tenant_id, project_id, run_id, str(error))
            finally:
                self._queue.task_done()

    async def _process(self, tenant_id: str, project_id: str, run_id: str) -> None:
        job = self.get_job(tenant_id, project_id, run_id) or {}
        actor = job.get("actor", "system")
        run = await self.runs.get_run(tenant_id, project_id, run_id)
        if not run or run.state != RunState.QUEUED:
            self._save_job(tenant_id, project_id, run_id, "cancelled",
                           error="Run is no longer queued")
            return
        self._save_job(tenant_id, project_id, run_id, "running")

        async def advance(new_state, expected):
            return await self.runs.update_run_state(
                tenant_id, project_id, run_id, new_state, expected_state=expected
            )

        if not await advance(RunState.COLLECTING, RunState.QUEUED):
            self._save_job(tenant_id, project_id, run_id, "cancelled",
                           error="Run could not start collecting")
            return
        await self.evidence.discover_and_ingest_plan(
            tenant_id, project_id, run_id, run.research_plan
        )
        if not await advance(RunState.SYNTHESIZING, RunState.COLLECTING):
            return self._stopped(tenant_id, project_id, run_id)  # cancelled mid-run
        result = await self.synthesis.synthesize_local(tenant_id, project_id, run_id)
        if not result:
            await advance(RunState.INSUFFICIENT_EVIDENCE, RunState.SYNTHESIZING)
            self._save_job(tenant_id, project_id, run_id, "completed",
                           state=RunState.INSUFFICIENT_EVIDENCE.value)
            return
        if not await advance(RunState.REVIEWING, RunState.SYNTHESIZING):
            return self._stopped(tenant_id, project_id, run_id)
        outcome = await self.review.run_review(tenant_id, project_id, run_id, actor)
        final = outcome["state"].value if outcome else RunState.REVIEWING.value
        self._save_job(tenant_id, project_id, run_id, "completed", state=final)
        self.audit.record(tenant_id, project_id, run_id, actor, "job.completed",
                          {"final_state": final})

    def _stopped(self, tenant_id, project_id, run_id) -> None:
        self._save_job(tenant_id, project_id, run_id, "cancelled",
                       error="Run left the pipeline (cancelled)")

    async def _fail(self, tenant_id, project_id, run_id, message: str) -> None:
        run = await self.runs.get_run(tenant_id, project_id, run_id)
        if run:
            await self.runs.update_run_state(
                tenant_id, project_id, run_id, RunState.FAILED, revision=run.report_revision
            )
        self._save_job(tenant_id, project_id, run_id, "failed", error=message)
        self.audit.record(tenant_id, project_id, run_id, "system", "job.failed",
                          {"error": message})
