"""Transactional local publication: exact-content approval, immutable artifacts and audit."""
import uuid
from datetime import datetime, timezone

from src.config import get_research_config
from src.review_pipeline import digest, evidence_snapshot, read_entity, write_entity, release_policy


class PublicationService:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _role(db, key, user, roles):
        project = read_entity(db, 'project', key, key[1])
        if not project or not set(project.get('members', {}).get(user, [])) & set(roles):
            raise PermissionError('Current project membership does not authorize this action.')

    @staticmethod
    def _bundle(db, key):
        run = read_entity(db, 'run', key, key[2])
        draft = read_entity(db, 'draft', key, key[2])
        review = read_entity(db, 'model_review', key, key[2])
        if not run or not draft or not review or not review.get('passed') or review.get('blockers'):
            raise ValueError('All model review gates must pass before approval or release.')
        evidence = evidence_snapshot(db, key, run['report_revision'])
        if (review['report_revision'] != run['report_revision'] or review['provider'] == 'mock'
                or review['draft_digest'] != digest(draft) or review['evidence_digest'] != digest(evidence)
                or review['claims_digest'] != digest(review['claims'])
                or review.get('policy') != release_policy()):
            raise ValueError('Reviewed artifacts changed; a new review and approval are required.')
        return run, {'draft': draft, 'review': review, 'evidence': evidence,
                     'policy_epoch': run['policy_epoch'], 'configuration_snapshot_id': run['configuration_snapshot_id']}

    def approve(self, key, user, rationale):
        if not rationale or not rationale.strip():
            raise ValueError('An explicit human approval rationale is required.')
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._role(db, key, user, ['reviewer', 'admin'])
            run, bundle = self._bundle(db, key)
            if run['state'] != 'awaiting_approval':
                raise ValueError('The run is not awaiting approval.')
            approval = dict(tenant_id=key[0], project_id=key[1], run_id=key[2],
                            report_revision=run['report_revision'], approval_id='APR-'+uuid.uuid4().hex,
                            approver_id=user, approval_rationale=rationale.strip(),
                            approved_bundle_digest=digest(bundle), validity=True,
                            approved_at=datetime.now(timezone.utc).isoformat())
            write_entity(db, 'approval', key, approval['approval_id'], approval, insert=True)
            run['state'] = 'approved'
            write_entity(db, 'run', key, key[2], run)
            self._audit(db, key, user, 'approved', approval['approval_id'])
            return approval

    def release(self, key, user, approval_id):
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._role(db, key, user, ['publisher', 'admin'])
            # Retry is idempotent, but cannot bypass current publisher authorization.
            existing = read_entity(db, 'release_by_run', key, key[2])
            if existing:
                if existing['approval_reference'] != approval_id:
                    raise ValueError('This run was released with a different approval.')
                return read_entity(db, 'release', key, existing['release_id'])
            run, bundle = self._bundle(db, key)
            approval = read_entity(db, 'approval', key, approval_id)
            if (run['state'] != 'approved' or not approval or not approval['validity']
                    or approval['run_id'] != key[2] or approval['report_revision'] != run['report_revision']
                    or approval['approved_bundle_digest'] != digest(bundle)):
                raise ValueError('A current approval for these exact artifacts is required.')
            self._role(db, key, approval['approver_id'], ['reviewer', 'admin'])
            if get_research_config().require_separate_publisher and approval['approver_id'] == user:
                raise ValueError('The publisher must be different from the approver.')
            release_id = 'REL-'+uuid.uuid4().hex
            base = f'/api/v1/projects/{key[1]}/releases/{release_id}'
            release = dict(tenant_id=key[0], project_id=key[1], run_id=key[2],
                           report_revision=run['report_revision'], release_id=release_id,
                           released_at=datetime.now(timezone.utc).isoformat(), released_by=user,
                           approval_reference=approval_id, report_blob_url=base+'/report',
                           manifest_blob_url=base+'/manifest', is_withdrawn=False,
                           bundle_digest=digest(bundle), storage='sqlite-local')
            artifact = {'bundle': bundle, 'bundle_digest': digest(bundle), 'approval': approval}
            write_entity(db, 'release_artifact', key, release_id, artifact, insert=True)
            write_entity(db, 'release', key, release_id, release, insert=True)
            write_entity(db, 'release_by_run', key, key[2], release, insert=True)
            run['state'] = 'released'
            write_entity(db, 'run', key, key[2], run)
            self._audit(db, key, user, 'released', release_id)
            write_entity(db, 'outbox', key, release_id,
                         {'event': 'report.released', 'release_id': release_id, 'dispatched': False}, insert=True)
            return release

    @staticmethod
    def _audit(db, key, user, action, reference):
        write_entity(db, 'audit', key, uuid.uuid4().hex,
                     {'user_id': user, 'action': action, 'reference': reference,
                      'at': datetime.now(timezone.utc).isoformat()}, insert=True)
