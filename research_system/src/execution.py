"""Durable local queue with atomic claims, leases, and bounded execution.

Queued jobs survive restarts. Interrupted jobs fail explicitly, preserving partial
evidence; retry with a new run rather than silently replaying a confirmed search.
"""
import asyncio
import json
import time
import uuid
from contextlib import suppress

from src.config import get_research_config
from src.models import RunState
from src.services import ResearchRunService, SynthesisService, CitationValidationService


class ExecutionQueue:
    def __init__(self, store):
        self.store = store
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS execution_jobs (
                tenant_id TEXT, project_id TEXT, run_id TEXT,
                status TEXT NOT NULL, owner TEXT, lease_until REAL DEFAULT 0,
                payload TEXT NOT NULL, created_at REAL NOT NULL,
                PRIMARY KEY (tenant_id, project_id, run_id))""")

    def get(self, tenant, project, run):
        with self.store._connect() as db:
            row = db.execute("SELECT payload FROM execution_jobs WHERE tenant_id=? "
                             "AND project_id=? AND run_id=?", (tenant, project, run)).fetchone()
        return json.loads(row['payload']) if row else None

    def enqueue(self, tenant, project, run, full_text):
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT payload FROM execution_jobs WHERE tenant_id=? "
                                  "AND project_id=? AND run_id=?", (tenant, project, run)).fetchone()
            if existing:
                result = json.loads(existing['payload'])
                if result['full_text'] != full_text:
                    raise ValueError("This run already has different execution options.")
                return result
            row = db.execute("SELECT payload FROM entities WHERE kind='run' AND tenant_id=? "
                             "AND project_id=? AND entity_id=?", (tenant, project, run)).fetchone()
            record = json.loads(row['payload']) if row else None
            if not record or record['state'] != 'queued' or not record.get('research_plan'):
                raise ValueError("Create a plan and confirm its scope before starting research.")
            if full_text and not record['research_request']['approved_source_domains']:
                raise ValueError("Full documents require approved source domains in the research scope.")
            job = dict(tenant_id=tenant, project_id=project, run_id=run, full_text=full_text,
                       status='queued', stage='queued', source_count=0, evidence_count=0,
                       provider_outcomes=[], documents=[], message='Waiting for the local worker.')
            db.execute("INSERT INTO execution_jobs VALUES (?, ?, ?, 'queued', NULL, 0, ?, ?)",
                       (tenant, project, run, json.dumps(job), time.time()))
            # Reserve the run in the same transaction, excluding manual execution.
            record['state'] = 'collecting'
            db.execute("UPDATE entities SET payload=?, updated_at=CURRENT_TIMESTAMP WHERE kind='run' "
                       "AND tenant_id=? AND project_id=? AND entity_id=?",
                       (json.dumps(record), tenant, project, run))
        return job

    def claim(self, owner):
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # Lost processes cannot leave apparently running jobs forever.
            expired = db.execute("SELECT * FROM execution_jobs WHERE status='running' AND lease_until<?",
                                 (time.time(),)).fetchall()
            for row in expired:
                job = json.loads(row['payload'])
                job.update(status='failed', stage='interrupted',
                           message='Worker interrupted. Partial evidence is saved; start a new run to retry.')
                key = (row['tenant_id'], row['project_id'], row['run_id'])
                db.execute("UPDATE execution_jobs SET status='failed', payload=? WHERE tenant_id=? "
                           "AND project_id=? AND run_id=?", (json.dumps(job), *key))
                db.execute("UPDATE entities SET payload=json_set(payload, '$.state', 'failed') "
                           "WHERE kind='run' AND tenant_id=? AND project_id=? AND entity_id=? "
                           "AND json_extract(payload, '$.state') IN ('collecting','synthesizing','reviewing')", key)
            row = db.execute("SELECT * FROM execution_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            job = json.loads(row['payload'])
            job.update(status='running', stage='discovery', message='Discovering sources.')
            db.execute("UPDATE execution_jobs SET status='running', owner=?, lease_until=?, payload=? "
                       "WHERE tenant_id=? AND project_id=? AND run_id=?",
                       (owner, time.time() + 30, json.dumps(job), job['tenant_id'], job['project_id'], job['run_id']))
            return job

    def save(self, job, owner):
        with self.store._connect() as db:
            changed = db.execute("UPDATE execution_jobs SET status=?, payload=?, lease_until=? "
                                 "WHERE tenant_id=? AND project_id=? AND run_id=? AND owner=? AND status='running'",
                                 (job['status'], json.dumps(job), time.time() + 30,
                                  job['tenant_id'], job['project_id'], job['run_id'], owner)).rowcount
        return bool(changed)


class LocalResearchWorker:
    def __init__(self, queue, evidence_service):
        self.queue = queue
        self.store = queue.store
        self.evidence = evidence_service
        self.runs = ResearchRunService(self.store)
        self.owner = uuid.uuid4().hex

    async def serve(self):
        while True:
            job = self.queue.claim(self.owner)
            if not job:
                await asyncio.sleep(0.25)
                continue
            task = asyncio.create_task(self.execute(job))
            heartbeat = asyncio.create_task(self.heartbeat(job, task))
            try:
                await asyncio.wait_for(task, timeout=get_research_config().max_run_duration_seconds)
            except asyncio.CancelledError:
                current = await self.runs.get_run(job['tenant_id'], job['project_id'], job['run_id'])
                cancelled = current and current.state == RunState.CANCELLED
                await self.finish(job, 'cancelled' if cancelled else 'failed',
                                  'Cancelled.' if cancelled else 'Worker stopped. Start a new run to retry.')
                if asyncio.current_task().cancelling():
                    raise
            except TimeoutError:
                await self.finish(job, 'failed', 'Research exceeded its time limit. Start a new run to retry.')
            except Exception:
                # Do not leak downloaded content, credentials, or raw network errors.
                await self.finish(job, 'failed', 'Research could not finish. Partial evidence is saved; start a new run to retry.')
            finally:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat

    async def heartbeat(self, job, task):
        while True:
            await asyncio.sleep(0.5)
            run = await self.runs.get_run(job['tenant_id'], job['project_id'], job['run_id'])
            if not run or run.state == RunState.CANCELLED or not self.queue.save(job, self.owner):
                task.cancel()
                return

    async def finish(self, job, status, message):
        job.update(status=status, stage=status, message=message)
        self.queue.save(job, self.owner)
        if status == 'failed':
            await self.runs.update_run_state(job['tenant_id'], job['project_id'], job['run_id'], RunState.FAILED)

    async def checkpoint(self, job, stage, message):
        run = await self.runs.get_run(job['tenant_id'], job['project_id'], job['run_id'])
        if not run or run.state == RunState.CANCELLED:
            raise asyncio.CancelledError()
        job.update(stage=stage, message=message)
        if not self.queue.save(job, self.owner):
            raise asyncio.CancelledError()
        await asyncio.sleep(0)
        return run

    async def execute(self, job):
        key = (job['tenant_id'], job['project_id'], job['run_id'])
        run = await self.checkpoint(job, 'discovery', 'Discovering sources.')
        sources = await self.evidence.discover_sources(*key, run.research_plan['search_queries'])
        job.update(source_count=len(sources), provider_outcomes=getattr(sources, 'outcomes', []))
        await self.checkpoint(job, 'ingestion', 'Saving source passages.')
        evidence = await self.evidence.ingest_sources(*key, [source for source in sources if source.passage.strip()])
        job['evidence_count'] = len(evidence)
        if job['full_text']:
            for source in sources:
                await self.checkpoint(job, 'documents', f"Collecting document {len(job['documents']) + 1} of {len(sources)}.")
                try:
                    passages = await self.evidence.ingest_full_sources(*key, [source])
                    status = 'collected' if passages else 'skipped'
                    job['evidence_count'] += len(passages)
                except Exception:
                    status = 'unavailable'
                job['documents'].append(dict(source_id=source.source_id, title=source.title, status=status))
        await self.checkpoint(job, 'synthesis', 'Preparing the cited draft.')
        if not await self.runs.update_run_state(*key, RunState.SYNTHESIZING, expected_state=RunState.COLLECTING):
            raise asyncio.CancelledError()
        result = await SynthesisService(self.store).synthesize_local(*key)
        if not result:
            await self.runs.update_run_state(*key, RunState.INSUFFICIENT_EVIDENCE, expected_state=RunState.SYNTHESIZING)
            await self.finish(job, 'insufficient_evidence', 'No eligible passages were found. Adjust the scope and start a new run.')
            return
        await self.checkpoint(job, 'citations', 'Checking citation integrity.')
        validation = await CitationValidationService(self.store).validate_local(*key)
        job['citation_check'] = dict(validated_claims=len(validation['validated_claim_ids']),
                                     findings=len(validation['findings']))
        if not await self.runs.update_run_state(*key, RunState.REVIEWING, expected_state=RunState.SYNTHESIZING):
            raise asyncio.CancelledError()
        await self.finish(job, 'completed', 'Draft ready. Independent review is still required.')
