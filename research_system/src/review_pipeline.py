"""Evidence-bound synthesis and independent model review, with atomic acceptance."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.config import get_research_config
from src.model_client import ModelConnectionError


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProposedClaim(Contract):
    text: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)


class Synthesis(Contract):
    claims: list[ProposedClaim] = Field(min_length=1, max_length=25)
    limitations: list[str] = Field(max_length=30)


class Verdict(Contract):
    claim_id: str
    verdict: Literal["supported", "contradicted", "insufficient_evidence"]
    explanation: str = Field(min_length=1, max_length=4000)


class FactCheck(Contract):
    verdicts: list[Verdict] = Field(min_length=1, max_length=25)


class CriticalReview(Contract):
    blocking_issues: list[str] = Field(max_length=30)
    limitations: list[str] = Field(max_length=30)
    rationale: str = Field(min_length=1, max_length=6000)


def release_policy():
    config = get_research_config()
    return {name: getattr(config, name) for name in ('min_independence_groups', 'require_peer_review',
            'require_publication_date', 'require_separate_publisher', 'source_policy_version')}


def read_entity(db, kind, key, entity_id):
    row = db.execute("SELECT payload FROM entities WHERE kind=? AND tenant_id=? AND project_id=? AND entity_id=?",
                     (kind, *key[:2], entity_id)).fetchone()
    return json.loads(row[0]) if row else None


def write_entity(db, kind, key, entity_id, payload, *, insert=False):
    query = "INSERT INTO entities(kind,tenant_id,project_id,entity_id,payload) VALUES(?,?,?,?,?)"
    if not insert:
        query += " ON CONFLICT(kind,tenant_id,project_id,entity_id) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP"
    db.execute(query, (kind, *key[:2], entity_id, json.dumps(payload)))


def evidence_snapshot(db, key, revision):
    rows = db.execute("SELECT payload FROM entities WHERE kind='evidence' AND tenant_id=? AND project_id=? "
                      "AND json_extract(payload,'$.run_id')=? ORDER BY entity_id", key).fetchall()
    return [e for row in rows if (e := json.loads(row[0])).get('report_revision') == revision
            and e.get('eligibility_status') == 'eligible' and e.get('source_use_decision') == 'allowed']


class ReviewPipeline:
    def __init__(self, store, model):
        self.store, self.model = store, model

    async def execute(self, tenant, project, run_id):
        key = (tenant, project, run_id)
        if self.model.provider == 'mock':
            raise ModelConnectionError("Semantic review requires an explicitly selected model provider.")
        with self.store._connect() as db:
            run = read_entity(db, 'run', key, run_id)
            if not run or run['state'] not in {'synthesizing', 'reviewing'}:
                raise ValueError("Model review requires a synthesizing or reviewing run.")
            evidence = evidence_snapshot(db, key, run['report_revision'])
        if not evidence:
            raise ValueError("No eligible evidence is available.")
        # Deterministic bounded selection; never silently truncate an individual passage.
        selected = []
        size = 0
        for e in evidence:
            if len(selected) >= 25 or size + len(e['passage']) > 65000:
                continue
            selected.append(e)
            size += len(e['passage'])
        if not selected:
            raise ValueError("Eligible passages exceed the model context bound.")
        context = {'question': run['research_request'], 'evidence': selected}
        try:
            synthesis = Synthesis.model_validate(await self.model.complete_json(
                'synthesizer', 'Return {claims:[{text,evidence_ids:[id]}],limitations:[string]}. '
                'Each claim must be a bounded factual conclusion grounded in the supplied passages. '
                'Include conflicting evidence and avoid causal claims from correlations.', context))
            allowed = {e['evidence_id'] for e in selected}
            claims = []
            for index, c in enumerate(synthesis.claims):
                if not set(c.evidence_ids) <= allowed or len(set(c.evidence_ids)) != len(c.evidence_ids):
                    raise ValueError("Synthesis contains invalid citations.")
                claims.append({'claim_id': f'CLM-{run_id}-{run["report_revision"]}-{index+1}',
                               'text': c.text, 'evidence_ids': c.evidence_ids})
            check = FactCheck.model_validate(await self.model.complete_json(
                'fact_checker', 'Return {verdicts:[{claim_id,verdict,explanation}]}. '
                'Return exactly one verdict for every claim: supported, contradicted, or insufficient_evidence. '
                'Check entailment against cited passages, quantities, scope, causality and contradictory evidence. '
                'Use insufficient_evidence when uncertain. Independently assess every claim.',
                {**context, 'claims': claims}))
            if sorted(v.claim_id for v in check.verdicts) != sorted(c['claim_id'] for c in claims):
                raise ValueError("Fact checking must cover every claim exactly once.")
            critical = CriticalReview.model_validate(await self.model.complete_json(
                'critical_reviewer', 'Return {blocking_issues:[string],limitations:[string],rationale:string}. '
                'Independently assess methodological weaknesses, source independence, bias, contradictory '
                'evidence, privacy/safety issues, and whether the conclusions answer the scoped question. '
                'Blocking issues must list any reason the report should not be approved.',
                {**context, 'claims': claims, 'limitations': synthesis.limitations}))
        except ValidationError as error:
            raise ModelConnectionError("Model review output failed its schema contract.") from error

        blockers = list(critical.blocking_issues)
        blockers.extend(v.explanation for v in check.verdicts if v.verdict != 'supported')
        config = get_research_config()
        for claim in claims:
            cited = [e for e in selected if e['evidence_id'] in claim['evidence_ids']]
            origins = {g for e in cited for g in e.get('independence_group_ids', [])}
            if len(origins) < config.min_independence_groups:
                blockers.append(f"Claim {claim['claim_id']} has too few independent source groups.")
        for e in selected:
            if e.get('content_hash') != 'sha256:' + hashlib.sha256(e['passage'].encode()).hexdigest():
                blockers.append(f"Evidence {e['evidence_id']} failed content integrity validation.")
        groups = {g for e in selected for g in e.get('independence_group_ids', [])}
        if len(groups) < config.min_independence_groups:
            blockers.append('Too few independent source groups for release.')
        if any(e.get('independence_status') != 'assessed' for e in selected):
            blockers.append('Source independence remains unassessed.')
        if config.require_peer_review and any(e['peer_review_status'] != 'peer-reviewed' for e in selected):
            blockers.append('The release policy requires peer-reviewed evidence.')
        if config.require_publication_date and any(not e.get('published_at') for e in selected):
            blockers.append('The release policy requires publication dates.')

        draft = dict(tenant_id=tenant, project_id=project, run_id=run_id,
                     report_revision=run['report_revision'], title=run['research_request']['title'],
                     abstract='Evidence-grounded conclusions, independently reviewed by model calls.',
                     conclusions='\n'.join(f"- {c['text']} [evidence: {', '.join(c['evidence_ids'])}]" for c in claims),
                     limitations=synthesis.limitations + critical.limitations,
                     references=[{k: e.get(k) for k in ('evidence_id','title','url','doi','passage_id','source_snapshot_id')} for e in selected])
        review = dict(run_id=run_id, report_revision=run['report_revision'],
                      provider=self.model.provider, model=self.model.model, prompt_version='research-review-v1',
                      policy=release_policy(),
                      fact_check=check.model_dump(), critical_review=critical.model_dump(),
                      blockers=blockers, passed=not blockers, evidence_digest=digest(evidence),
                      draft_digest=digest(draft), claims_digest=digest(claims), claims=claims)
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = read_entity(db, 'run', key, run_id)
            if current != run or digest(evidence_snapshot(db, key, run['report_revision'])) != digest(evidence):
                raise ValueError("Run or evidence changed while reviewing; output was discarded.")
            for claim in claims:
                record = dict(tenant_id=tenant, project_id=project, run_id=run_id,
                              report_revision=run['report_revision'], claim_id=claim['claim_id'], text=claim['text'],
                              material=True, evidence_links=[{'evidence_id':eid, 'relation':'supports'} for eid in claim['evidence_ids']],
                              assertion_scope='multiple-origin', confidence=0.0, limitations=synthesis.limitations,
                              status=next(v.verdict for v in check.verdicts if v.claim_id == claim['claim_id']))
                write_entity(db, 'claim', key, claim['claim_id'], record)
            current['claims'] = [c['claim_id'] for c in claims]
            current['updated_time'] = datetime.now(timezone.utc).isoformat()
            write_entity(db, 'draft', key, run_id, draft)
            write_entity(db, 'model_review', key, run_id, review)
            current['state'] = 'awaiting_approval' if not blockers else 'adjudication_required'
            write_entity(db, 'run', key, run_id, current)
        return review
