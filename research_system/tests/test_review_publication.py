import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from src.local_store import LocalStateStore
from src.model_client import ModelConnectionError
from src.publication import PublicationService
from src.review_pipeline import ReviewPipeline


KEY = ('tenant', 'project', 'run')


class Model:
    provider = 'azure'
    model = 'test-model'

    def __init__(self, verdict='supported', blockers=None, mutate=None, bad_citation=False):
        self.verdict, self.blockers = verdict, blockers or []
        self.mutate, self.bad_citation = mutate, bad_citation
        self.calls = []

    async def complete_json(self, role, instructions, payload):
        self.calls.append(role)
        if role == 'synthesizer':
            return {'claims': [{'text': 'Treatment improved the measured outcome in these studies.',
                                'evidence_ids': ['foreign'] if self.bad_citation else ['E1','E2']}],
                    'limitations': ['Small sample.']}
        if role == 'fact_checker':
            return {'verdicts': [{'claim_id': c['claim_id'], 'verdict': self.verdict,
                                  'explanation': 'Compared with the reported study results.'} for c in payload['claims']]}
        if self.mutate:
            self.mutate()
        return {'blocking_issues': self.blockers, 'limitations': ['Limited follow-up.'],
                'rationale': 'Assessed study quality and scope.'}


@pytest.fixture
def store(tmp_path):
    s = LocalStateStore(tmp_path/'state.db')
    s.put('project', *KEY[:2], KEY[1], {'tenant_id':KEY[0], 'project_id':KEY[1], 'name':'Test', 'data_policy_version':'1', 'max_budget_usd':1, 'created_at':'2026-09-19T10:00:00','updated_at':'2026-09-19T10:00:00', 'members': {'reviewer':['reviewer'], 'publisher':['publisher']}})
    s.put('run', *KEY, {'run_id':'run', 'state':'synthesizing', 'report_revision':1,
                        'policy_epoch':0, 'configuration_snapshot_id':'cfg',
                        'start_time':'2026-09-19T10:00:00', 'updated_time':'2026-09-19T10:00:00',
                        'tenant_id':KEY[0], 'project_id':KEY[1],
                        'research_request':{'title':'Research', 'primary_question':'Does treatment help?', 'scope_description':'Studies'}})
    for i in (1,2):
        s.put('evidence', *KEY[:2], f'E{i}', dict(tenant_id=KEY[0],project_id=KEY[1],run_id=KEY[2],
              report_revision=1,evidence_id=f'E{i}',source_use_decision='allowed',eligibility_status='eligible',
              passage='The treatment improved the measured outcome.',title=f'Study {i}',url='https://example.org',
              independence_group_ids=[f'G{i}'],independence_status='assessed',peer_review_status='peer-reviewed',
              published_at='2025-01-01',content_hash='sha256:'+hashlib.sha256(b'The treatment improved the measured outcome.').hexdigest()))
    return s


def run_review(store, model=None):
    return asyncio.run(ReviewPipeline(store, model or Model()).execute(*KEY))


def test_review_and_exact_content_release(store):
    model = Model()
    assert run_review(store, model)['passed']
    assert model.calls == ['synthesizer','fact_checker','critical_reviewer']
    service = PublicationService(store)
    approval = service.approve(KEY, 'reviewer', 'I checked the evidence and limitations.')
    release = service.release(KEY, 'publisher', approval['approval_id'])
    assert release['storage'] == 'sqlite-local'
    assert service.release(KEY, 'publisher', approval['approval_id']) == release
    assert store.get('run', *KEY)['state'] == 'released'
    assert store.get('release_artifact', *KEY[:2], release['release_id'])['bundle']['draft']['conclusions']
    assert len(store.list('audit', *KEY[:2])) == 2
    assert len(store.list('outbox', *KEY[:2])) == 1


@pytest.mark.parametrize('model', [Model(verdict='contradicted'), Model(blockers=['Uncontrolled confounding.'])])
def test_review_blockers_cannot_be_approved(store, model):
    assert not run_review(store, model)['passed']
    assert store.get('run', *KEY)['state'] == 'adjudication_required'
    with pytest.raises(ValueError):
        PublicationService(store).approve(KEY, 'reviewer', 'Approve')


def test_foreign_citations_rejected_without_persisting(store):
    with pytest.raises(ValueError, match='invalid citations'):
        run_review(store, Model(bad_citation=True))
    assert not store.get('draft', *KEY)


def test_cancellation_discards_model_output(store):
    def cancel():
        run = store.get('run', *KEY)
        run['state'] = 'cancelled'
        store.put('run', *KEY, run)
    with pytest.raises(ValueError, match='changed'):
        run_review(store, Model(mutate=cancel))
    assert not store.get('draft', *KEY)
    assert store.get('run', *KEY)['state'] == 'cancelled'


@pytest.mark.parametrize('kind,entity', [('draft','run'),('evidence','E1'),('model_review','run')])
def test_modified_artifacts_invalidate_approval(store, kind, entity):
    run_review(store)
    service = PublicationService(store)
    approval = service.approve(KEY, 'reviewer', 'Reviewed')
    data = store.get(kind, *KEY[:2], entity)
    data['tampered'] = True
    store.put(kind, *KEY[:2], entity, data)
    with pytest.raises(ValueError):
        service.release(KEY, 'publisher', approval['approval_id'])
    assert not store.list('release', *KEY[:2])


def test_revoked_approval_and_membership_block_release(store):
    run_review(store)
    service = PublicationService(store)
    approval = service.approve(KEY, 'reviewer', 'Reviewed')
    project = store.get('project', *KEY[:2], KEY[1])
    project['members']['reviewer'] = []
    store.put('project', *KEY[:2], KEY[1], project)
    with pytest.raises(PermissionError):
        service.release(KEY, 'publisher', approval['approval_id'])
    approval['validity'] = False
    store.put('approval', *KEY[:2], approval['approval_id'], approval)
    with pytest.raises(ValueError):
        service.release(KEY, 'publisher', approval['approval_id'])


def test_separate_publisher_and_scope(store):
    run_review(store)
    project = store.get('project', *KEY[:2], KEY[1])
    project['members']['reviewer'].append('publisher')
    store.put('project', *KEY[:2], KEY[1], project)
    service = PublicationService(store)
    approval = service.approve(KEY, 'reviewer', 'Reviewed')
    with pytest.raises(ValueError, match='different'):
        service.release(KEY, 'reviewer', approval['approval_id'])
    with pytest.raises(PermissionError):
        service.release(('other', *KEY[1:]), 'publisher', approval['approval_id'])


def test_mock_never_passes_semantic_gate(store):
    model = Model()
    model.provider = 'mock'
    with pytest.raises(ModelConnectionError):
        run_review(store, model)


def test_malformed_or_missing_verdict_rejected(store):
    class Broken(Model):
        async def complete_json(self, role, instructions, payload):
            if role == 'fact_checker':
                return {'verdicts': []}
            return await super().complete_json(role, instructions, payload)
    with pytest.raises(ModelConnectionError):
        run_review(store, Broken())
    assert not store.get('draft', *KEY)


def test_approval_release_and_artifact_api(store, monkeypatch):
    from tests.test_execution_and_dashboard import _reload_app
    from fastapi.testclient import TestClient
    monkeypatch.setenv('ENABLE_REPORT_RELEASE', 'true')
    module = _reload_app(store.database_path, monkeypatch)
    with TestClient(module.app) as client:
        module.model_client = Model()
        reviewer = {'X-Tenant-Id': KEY[0], 'X-User-Id': 'reviewer'}
        publisher = {'X-Tenant-Id': KEY[0], 'X-User-Id': 'publisher'}
        base = f'/api/v1/projects/{KEY[1]}/runs/{KEY[2]}'
        assert client.post(base+'/review', headers=reviewer).status_code == 200
        approved = client.post(base+'/request-approval', headers=reviewer,
                               json={'approval_rationale':'Verified the cited studies.'})
        assert approved.status_code == 200, approved.text
        approval_id = approved.json()['approval']['approval_id']
        denied = client.post(base+'/release', headers=reviewer, json={'approval_id':approval_id})
        assert denied.status_code == 403
        released = client.post(base+'/release', headers=publisher, json={'approval_id':approval_id})
        assert released.status_code == 200, released.text
        report = client.get(released.json()['report_blob_url'], headers=reviewer)
        assert report.status_code == 200
        assert 'Treatment improved' in report.json()['conclusions']
        denied = client.get(released.json()['report_blob_url'],
                            headers={'X-Tenant-Id':'other','X-User-Id':'reviewer'})
        assert denied.status_code == 403
