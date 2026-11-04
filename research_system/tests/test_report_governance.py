"""FUT-080: adversarial and fault-injection tests for the local release path."""
import asyncio
import hashlib
import importlib
import json

import pytest
from fastapi.testclient import TestClient

from src.adjudication import AdjudicationService
from src.audit import read_audit
from src.config import get_api_config, get_azure_config, get_model_config, get_research_config
from src.governance import GovernanceService, release_readiness
from src.local_store import LocalStateStore
from src.publication import PublicationService
from src.review_pipeline import ReviewPipeline
from src.verification import ModelVerifier

KEY = ('tenant', 'project', 'run')
PASSAGE = 'The treatment improved the measured outcome in adults.'
MEMBERS = {'reviewer': ['reviewer'], 'reviewer2': ['reviewer'], 'publisher': ['publisher'],
           'both': ['reviewer', 'publisher'], 'admin': ['admin'], 'outsider': []}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def fresh_config(monkeypatch):
    for name in ('RELEASE_REQUIRE_LICENCE', 'REQUIRE_SEPARATE_ADJUDICATOR', 'INDEPENDENT_VERIFICATION',
                 'REQUIRE_PEER_REVIEW'):
        monkeypatch.delenv(name, raising=False)
    get_research_config.cache_clear()
    yield
    get_research_config.cache_clear()


def configure(monkeypatch, **env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_research_config.cache_clear()


class Reviewer:
    provider, model = 'azure', 'test-model'

    def __init__(self, verdict='supported', blockers=None):
        self.verdict, self.blockers = verdict, blockers or []

    async def complete_json(self, role, instructions, payload):
        if role == 'synthesizer':
            return {'claims': [{'text': 'Treatment improved the measured outcome in adults.',
                                'evidence_ids': ['E1', 'E2']}], 'limitations': ['Small.']}
        if role == 'fact_checker':
            return {'verdicts': [{'claim_id': c['claim_id'], 'verdict': self.verdict,
                                  'explanation': 'Compared with the study results.'} for c in payload['claims']]}
        return {'blocking_issues': self.blockers, 'limitations': ['Short.'], 'rationale': 'Assessed.'}


def make_store(path, licence='CC-BY-4.0'):
    store = LocalStateStore(path)
    store.put('project', *KEY[:2], KEY[1], {
        'tenant_id': KEY[0], 'project_id': KEY[1], 'name': 'T', 'data_policy_version': '1',
        'max_budget_usd': 1, 'created_at': '2026-09-19T10:00:00', 'updated_at': '2026-09-19T10:00:00',
        'members': MEMBERS})
    store.put('run', *KEY, {
        'run_id': 'run', 'state': 'synthesizing', 'report_revision': 1, 'policy_epoch': 0,
        'configuration_snapshot_id': 'cfg', 'start_time': '2026-09-19T10:00:00',
        'updated_time': '2026-09-19T10:00:00', 'tenant_id': KEY[0], 'project_id': KEY[1],
        'research_request': {'title': 'R', 'primary_question': 'Does it help?', 'scope_description': 'S'}})
    for i in (1, 2):
        record = dict(
            tenant_id=KEY[0], project_id=KEY[1], run_id=KEY[2], report_revision=1, evidence_id=f'E{i}',
            source_id=f'S{i}', source_use_decision='allowed', eligibility_status='eligible', passage=PASSAGE,
            title=f'Study {i}', url=f'https://example.org/{i}', independence_group_ids=[f'G{i}'],
            independence_status='assessed', peer_review_status='peer-reviewed', published_at='2025-01-01',
            content_hash='sha256:' + hashlib.sha256(PASSAGE.encode()).hexdigest())
        if licence:
            record['license'] = licence
        store.put('evidence', *KEY[:2], f'E{i}', record)
    return store


def reviewed(store, reviewer=None, verifiers=None):
    return run(ReviewPipeline(store, reviewer or Reviewer(), verifiers).execute(*KEY))


def approved(tmp_path, **kwargs):
    store = make_store(tmp_path / 's.db', **kwargs)
    reviewed(store)
    approval = PublicationService(store).approve(KEY, 'reviewer', 'Checked sources and limitations.')
    return store, approval


def released(tmp_path):
    store, approval = approved(tmp_path)
    release = PublicationService(store).release(KEY, 'publisher', approval['approval_id'])
    return store, approval, release


# ------------------------------------------------------------------ approval cannot be bypassed

def test_edit_after_approval_blocks_release(tmp_path):
    store, approval = approved(tmp_path)
    draft = store.get('draft', *KEY)
    draft['conclusions'] += '\n- An unreviewed addition.'
    store.put('draft', *KEY, draft)
    with pytest.raises(ValueError, match='changed'):
        PublicationService(store).release(KEY, 'publisher', approval['approval_id'])
    assert store.get('run', *KEY)['state'] == 'approved'


def test_policy_change_makes_an_approval_stale(tmp_path, monkeypatch):
    store, approval = approved(tmp_path)
    configure(monkeypatch, REQUIRE_PEER_REVIEW='false')
    with pytest.raises(ValueError, match='changed'):
        PublicationService(store).release(KEY, 'publisher', approval['approval_id'])


def test_unsupported_material_claim_cannot_be_approved(tmp_path):
    store = make_store(tmp_path / 's.db')
    reviewed(store, Reviewer(verdict='insufficient_evidence'))
    with pytest.raises(ValueError, match='gates must pass'):
        PublicationService(store).approve(KEY, 'reviewer', 'Approve anyway.')


def test_verifier_failure_cannot_be_approved(tmp_path, monkeypatch):
    configure(monkeypatch, INDEPENDENT_VERIFICATION='model')

    class Down:
        provider, model = 'local_proxy', 'verifier'

        async def complete_json(self, *args):
            raise RuntimeError('down')

    store = make_store(tmp_path / 's.db')
    reviewed(store, verifiers=[ModelVerifier(Down())])
    with pytest.raises(ValueError, match='gates must pass'):
        PublicationService(store).approve(KEY, 'reviewer', 'Approve anyway.')


# ------------------------------------------------------------------ roles and separation of duties

def test_unauthorized_users_cannot_approve_release_or_withdraw(tmp_path):
    store = make_store(tmp_path / 's.db')
    reviewed(store)
    service = PublicationService(store)
    for user in ('publisher', 'outsider', 'nobody'):
        with pytest.raises(PermissionError):
            service.approve(KEY, user, 'Not a reviewer.')
    approval = service.approve(KEY, 'reviewer', 'Checked.')
    for user in ('reviewer', 'outsider', 'nobody'):
        with pytest.raises(PermissionError):
            service.release(KEY, user, approval['approval_id'])
    release = service.release(KEY, 'publisher', approval['approval_id'])
    for user in ('reviewer', 'outsider'):
        with pytest.raises(PermissionError):
            GovernanceService(store).withdraw(KEY[0], KEY[1], user, release['release_id'], 'No.')


def test_approver_and_publisher_must_differ_by_default(tmp_path):
    store = make_store(tmp_path / 's.db')
    reviewed(store)
    approval = PublicationService(store).approve(KEY, 'both', 'Checked.')
    with pytest.raises(ValueError, match='different from the approver'):
        PublicationService(store).release(KEY, 'both', approval['approval_id'])


def test_adjudicator_may_not_approve_when_separation_is_required(tmp_path, monkeypatch):
    configure(monkeypatch, REQUIRE_SEPARATE_ADJUDICATOR='true')
    store = make_store(tmp_path / 's.db')
    (item,) = reviewed(store, Reviewer(blockers=['Concern.']))['blocker_items']
    AdjudicationService(store).decide(KEY, 'reviewer', item['id'], 'accepted_limitation', 'Disclosed.')
    with pytest.raises(ValueError, match='adjudicated'):
        PublicationService(store).approve(KEY, 'reviewer', 'Self-approval.')
    assert PublicationService(store).approve(KEY, 'reviewer2', 'Independent approval.')


def test_adjudicator_can_approve_when_separation_is_not_required(tmp_path):
    store = make_store(tmp_path / 's.db')
    (item,) = reviewed(store, Reviewer(blockers=['Concern.']))['blocker_items']
    AdjudicationService(store).decide(KEY, 'reviewer', item['id'], 'accepted_limitation', 'Disclosed.')
    assert PublicationService(store).approve(KEY, 'reviewer', 'Approved.')


# ------------------------------------------------------------------ licences and revocation

def test_missing_licence_blocks_only_when_required(tmp_path, monkeypatch):
    store = make_store(tmp_path / 'a.db', licence=None)
    reviewed(store)
    assert PublicationService(store).approve(KEY, 'reviewer', 'No licence policy yet.')

    configure(monkeypatch, RELEASE_REQUIRE_LICENCE='true')
    other = tmp_path / 'b'
    other.mkdir()
    store = make_store(other / 's.db', licence=None)
    reviewed(store)
    with pytest.raises(ValueError, match='licence'):
        PublicationService(store).approve(KEY, 'reviewer', 'Approve.')
    licensed = tmp_path / 'c'
    licensed.mkdir()
    store = make_store(licensed / 's.db')
    reviewed(store)
    assert PublicationService(store).approve(KEY, 'reviewer', 'Licensed.')


def test_revoked_evidence_blocks_release_of_an_approved_report(tmp_path):
    store, approval = approved(tmp_path)
    result = GovernanceService(store).revoke_evidence(KEY[0], KEY[1], 'reviewer', 'E1', 'Paper retracted.')
    assert result['affected_releases'] == []  # nothing released yet
    with pytest.raises(ValueError, match='changed'):
        PublicationService(store).release(KEY, 'publisher', approval['approval_id'])
    assert store.get('evidence', *KEY[:2], 'E1')['revocation']['reason'] == 'Paper retracted.'


def test_revocation_after_release_reports_affected_releases_without_auto_withdrawing(tmp_path):
    store, approval, release = released(tmp_path)
    result = GovernanceService(store).revoke_evidence(KEY[0], KEY[1], 'admin', 'E2', 'Licence withdrawn.')
    assert result['affected_releases'] == [release['release_id']]
    assert not store.get('release', *KEY[:2], release['release_id']).get('is_withdrawn')  # human decides
    actions = [e['action'] for e in read_audit(store, *KEY[:2], KEY[2])['events']]
    assert 'evidence.revoked' in actions


def test_revocation_requires_reviewer_or_admin_reason_and_existing_evidence(tmp_path):
    store, _ = approved(tmp_path)
    service = GovernanceService(store)
    with pytest.raises(PermissionError):
        service.revoke_evidence(KEY[0], KEY[1], 'publisher', 'E1', 'No role.')
    with pytest.raises(ValueError, match='reason'):
        service.revoke_evidence(KEY[0], KEY[1], 'reviewer', 'E1', '  ')
    with pytest.raises(ValueError, match='not found'):
        service.revoke_evidence(KEY[0], KEY[1], 'reviewer', 'E-NOPE', 'Reason.')


# ------------------------------------------------------------------ withdrawal and tombstone

def test_withdrawal_is_a_transactional_tombstone(tmp_path):
    store, approval, release = released(tmp_path)
    GovernanceService(store).withdraw(KEY[0], KEY[1], 'publisher', release['release_id'], 'Error found.')

    withdrawn = store.get('release', *KEY[:2], release['release_id'])
    assert withdrawn['is_withdrawn'] and withdrawn['withdrawal_reason'] == 'Error found.'
    assert withdrawn['withdrawn_by'] == 'publisher'
    assert store.get('release_by_run', *KEY)['is_withdrawn']
    assert store.get('run', *KEY)['state'] == 'withdrawn'
    assert store.get('release_artifact', *KEY[:2], release['release_id'])  # retained, not deleted
    assert {e['entity_id'] if 'entity_id' in e else e.get('event') for e in store.list('outbox', *KEY[:2])} \
        >= {'report.released', 'report.withdrawn'}
    audit = read_audit(store, *KEY[:2], KEY[2])
    assert audit['chain_valid'] and audit['events'][-1]['action'] == 'release.withdrawn'


def test_withdrawn_release_cannot_be_re_released_or_withdrawn_twice(tmp_path):
    store, approval, release = released(tmp_path)
    service = GovernanceService(store)
    with pytest.raises(ValueError, match='reason'):
        service.withdraw(KEY[0], KEY[1], 'publisher', release['release_id'], ' ')
    service.withdraw(KEY[0], KEY[1], 'publisher', release['release_id'], 'Error found.')
    with pytest.raises(ValueError, match='already withdrawn'):
        service.withdraw(KEY[0], KEY[1], 'publisher', release['release_id'], 'Again.')
    with pytest.raises(ValueError, match='withdrawn'):
        PublicationService(store).release(KEY, 'publisher', approval['approval_id'])
    with pytest.raises(ValueError, match='not found'):
        service.withdraw(KEY[0], KEY[1], 'publisher', 'REL-NOPE', 'Reason.')


# ------------------------------------------------------------------ provenance and manifest

def test_provenance_reproduces_the_claim_to_approval_chain(tmp_path):
    store, approval, release = released(tmp_path)
    chain = GovernanceService(store).provenance(KEY[0], KEY[1], release['release_id'])
    assert chain['approval']['approval_id'] == approval['approval_id']
    assert chain['approval']['approver_id'] == 'reviewer'
    (claim,) = chain['claims']
    assert claim['verdict'] == 'supported'
    assert {p['evidence_id'] for p in claim['passages']} == {'E1', 'E2'}
    assert all(p['license'] == 'CC-BY-4.0' and p['content_hash'].startswith('sha256:')
               for p in claim['passages'])
    assert chain['review']['provider'] == 'azure' and chain['audit']['chain_valid']


def test_bundle_manifest_records_licences_provenance_and_retrieval_config(tmp_path):
    store, _, release = released(tmp_path)
    manifest = store.get('release_artifact', *KEY[:2], release['release_id'])['bundle']['manifest']
    assert {s['license'] for s in manifest['sources']} == {'CC-BY-4.0'}
    assert manifest['review']['model'] == 'test-model' and manifest['verification_mode'] == 'off'
    assert manifest['retrieval'] == {'mode': 'keyword', 'embedding_provider': 'none'}


def test_tampered_release_artifact_fails_provenance_integrity(tmp_path):
    store, _, release = released(tmp_path)
    artifact = store.get('release_artifact', *KEY[:2], release['release_id'])
    artifact['bundle']['draft']['conclusions'] = 'Rewritten after release.'
    with store._connect() as db:
        db.execute("UPDATE entities SET payload=? WHERE kind='release_artifact' AND entity_id=?",
                   (json.dumps(artifact), release['release_id']))
    with pytest.raises(ValueError, match='integrity'):
        GovernanceService(store).provenance(KEY[0], KEY[1], release['release_id'])


# ------------------------------------------------------------------ readiness checklist

def test_release_readiness_is_not_ready_today_and_names_what_is_missing():
    report = release_readiness(get_research_config(), get_api_config())
    assert report['ready'] is False
    unmet = {i['id'] for i in report['items'] if not i['met']}
    assert {'production_persistence', 'browser_sso', 'observability_recovery',
            'authenticated_identity'} <= unmet


def test_readiness_cannot_be_satisfied_by_configuration_alone(monkeypatch):
    configure(monkeypatch, REQUIRE_SEPARATE_ADJUDICATOR='true', RELEASE_REQUIRE_LICENCE='true',
              INDEPENDENT_VERIFICATION='both')
    report = release_readiness(get_research_config(), get_api_config())
    met = {i['id'] for i in report['items'] if i['met']}
    assert {'separate_adjudicator', 'licence_required', 'independent_verification'} <= met
    assert report['ready'] is False  # platform items (FUT-040/050/070) still unmet


# ------------------------------------------------------------------ API

def test_api_withdrawal_provenance_revocation_and_readiness(tmp_path, monkeypatch):
    store, approval, release = released(tmp_path)
    db = tmp_path / 's.db'
    monkeypatch.setenv('LOCAL_DB_PATH', str(db))
    monkeypatch.setenv('MODEL_PROVIDER', 'mock')
    for fn in (get_api_config, get_azure_config, get_model_config, get_research_config):
        fn.cache_clear()
    import src.main as main_module
    main_module = importlib.reload(main_module)

    def h(user):
        return {'X-Tenant-Id': KEY[0], 'X-User-Id': user}

    rid = release['release_id']
    base = f'/api/v1/projects/{KEY[1]}'
    with TestClient(main_module.app) as client:
        assert client.get(f'{base}/releases/{rid}/report', headers=h('reviewer')).status_code == 200
        provenance = client.get(f'{base}/releases/{rid}/provenance', headers=h('reviewer'))
        assert provenance.status_code == 200 and provenance.json()['claims'][0]['passages']
        assert client.get(f'{base}/releases/{rid}/provenance', headers=h('outsider')).status_code == 403

        assert client.get(f'{base}/release-readiness', headers=h('reviewer')).status_code == 403
        readiness = client.get(f'{base}/release-readiness', headers=h('admin')).json()
        assert readiness['ready'] is False and readiness['release_enabled'] is False

        revoke = {'reason': 'Retracted.'}
        assert client.post(f'{base}/evidence/E1/revoke', headers=h('publisher'), json=revoke).status_code == 403
        revoked = client.post(f'{base}/evidence/E1/revoke', headers=h('reviewer'), json=revoke)
        assert revoked.status_code == 200 and revoked.json()['affected_releases'] == [rid]

        body = {'reason': 'Source retracted.'}
        assert client.post(f'/api/v1/releases/{rid}/withdraw?project_id={KEY[1]}',
                           headers=h('reviewer'), json=body).status_code == 403
        assert client.post(f'/api/v1/releases/{rid}/withdraw?project_id={KEY[1]}',
                           headers=h('publisher'), json={'reason': ' '}).status_code == 409
        done = client.post(f'/api/v1/releases/{rid}/withdraw?project_id={KEY[1]}',
                           headers=h('publisher'), json=body)
        assert done.status_code == 200
        assert client.get(f'{base}/releases/{rid}/report', headers=h('reviewer')).status_code == 410
        assert client.get(f'{base}/releases/{rid}/manifest', headers=h('reviewer')).status_code == 410
        again = client.post(f'/api/v1/releases/{rid}/withdraw?project_id={KEY[1]}',
                            headers=h('publisher'), json=body)
        assert again.status_code == 409
        audit = client.get(f'{base}/runs/{KEY[2]}/audit', headers=h('reviewer')).json()
        assert audit['chain_valid']
        assert [e['action'] for e in audit['events']][-2:] == ['evidence.revoked', 'release.withdrawn']
