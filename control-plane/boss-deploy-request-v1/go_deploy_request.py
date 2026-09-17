"""Candidate deployment gate. No credentials, shell commands, or live defaults.

What this gate decides, and what it deliberately no longer decides
-----------------------------------------------------------------
Issue #103, Authority Boundary: *CC validates deployability, not product
desirability.*  The upstream side (Boss GPT / Cells / release gates) chooses which
version should ship; the Command Center establishes whether that exact version can be
put on HK-STAGING safely and accurately.

Until 2026-09-17 the plan carried a `gates` block requiring four product-release
declarations -- three_end_ux, six_vertical_closed_loop, sealed_node, final_release --
to read PASS.  None of the four is required by the live executor: the HK agent and the
bounded executor never read a release-gate name, and the only two components that do
are Command Center components reading the plan they were handed.  Three of the four are
product acceptance verdicts (UX, business closed loop, final release) that no machine
process in this repository can produce -- they are `HOLD` in every historical record --
so requiring them either blocked every deployment forever or forced a human to write
PASS by hand, which `docs/project/CC_V1_SCOPE_20260916.md` names as a V1 failure.
`final_release` in particular inverted the order of the world: it demanded that a
version be finally released before it could be deployed to a *test* environment.

`sealed_node` was the one whose name stood for a real technical fact -- that the
artifact a deployment will load is the sealed product of this exact source -- so it is
not dropped, it is replaced by the fact itself: the signed TEST_PR of this candidate,
bound into the bundle and re-verified here.  The gate now establishes deployability
from the objects it can check, and never from a string a caller or an operator typed.

There is no deploy switch either, as of 2026-09-17.  A deployment was once refused until
an operator had turned one on in the root-owned channel configuration, which asked for a
standing authorisation *before* the authorising event could exist and therefore made a
human server operation a necessary step of every deployment.  What authorises a
deployment is now the one-time authorisation the Command Center derives from the
authenticated DEPLOY Request itself -- the `approval` block below, whose id is a
function of that Request's canonical digest rather than a name anybody chose, bounded by
an approval life of at most 15 minutes and by the Task deadline of at most 5, and
consumed once: the plan store never overwrites a registered plan, and the ledger refuses
a plan or authorisation it has already recorded.  A standing authorisation is not
expressible at all, which is the point.

A rollback is the same kind of act as a deployment, so it is gated here too and derived
the same way.  The Command Center picks the deployment to undo out of its own ledger --
the newest one it signed whose Evidence reports DEPLOY_OK -- binds that exact Task and
its Evidence into an authorisation derived from the Request, and accepts no target, no
service list and no image from anyone.  Whether the host is still in the state that
deployment left is a question this side cannot answer and does not pretend to: the
executor decides it at execution time, from files and containers it re-verifies itself.
"""
import base64
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import stat
import hk_candidate_contract as candidate_contract
import execution_window
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ACTION = 'HK_STAGING_DEPLOY'
ENVIRONMENT = 'HK-STAGING-01'
STORE = pathlib.Path('/etc/go-command-center/deployment-plans-v1')
TRUSTED_UID = 0
IDENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{2,79}\Z')
EXECUTOR_IDENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
COMMIT = re.compile(r'[0-9a-f]{40}\Z')
IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
PR_NUMBER = re.compile(r'[1-9][0-9]{0,8}\Z')
SERVICES = ['api','recovery-worker','outbox-worker','mobile-push-receipt-worker',
            'reconciliation-worker','mobile-push-worker','mobile-engagement-worker','judgment-worker']
# The candidate repository, in the slug form the plan carries. The TEST_PR Task names
# the same repository by its ssh remote, so both spellings are accepted there and the
# slug is what the plan records.
REPOSITORY = 'yuguangzhi3836-glitch/GO'
# The V1 Human Approval authority: the GitHub users this project authorises.
# GitHub decides who authored the Request PR, so the identity is authenticated
# by the platform rather than asserted by the caller, and this list is what the
# gate refuses against. It replaces a dedicated approval signing key, cancelled
# by the 2026-09-16 scope reset: the Boss must not have to generate or handle a
# key in order to authorise a deployment.
APPROVAL_IDENTITIES = ('yuguangzhi3836-glitch','chenzhenxi1-sudo')
# The approval's exact field set, named once. The approver-side signing tool and
# the tests both read it from here, so a field added on one side cannot pass
# unnoticed on the other.
# No signature: the authority is the authenticated GitHub identity, so there is
# nothing for a caller to sign and nothing for the gate to verify cryptographically.
# `request_sha256` binds the approval to the immutable DEPLOY Request the identity
# wrote: that Request *is* the explicit approval intent (its action_id says "deploy
# this candidate to this environment"), and a digest of its canonical content is what
# makes the intent content-level rather than a mutable PR affordance.
APPROVAL_FIELDS = ('schema_version','approval_id','approved_by','approved_at',
                   'expires_at','scope','plan_sha256','request_sha256')
CANDIDATE_FIELDS = ('repository','source_commit','application_git_tree',
                    'source_tree_sha256','package_sha256','image_id')
PLAN_FIELDS = ('schema_version','plan_id','environment','action_id','candidate',
               'expected_current_image_id','target_services','protected_non_targets',
               'migration','production','automatic_rollback','test_pr_task_sha256',
               'test_pr_evidence_sha256','canary_task_sha256','canary_evidence_sha256',
               'preflight_task_sha256','preflight_evidence_sha256')
BUNDLE_FIELDS = ('plan','approval','test_pr_task','test_pr_evidence',
                 'canary_task','canary_evidence','preflight_task','preflight_evidence')
TASK_FIELDS = ('schema_version','task_id','nonce','issued_at','expires_at','authority',
               'environment','action_id','parameters','signature')
# The sealed TEST_PR of the exact candidate. `artifact_sealed` is the gate B4-B1 added
# to the test-pr-v3 builder: it is the producer's own statement that the image it built
# was sealed into the fixed store, which is what makes the package content address
# something the executor can later resolve rather than a number that merely looks right.
TEST_PR_ACTION = 'HK_STAGING_TEST_PR'
TEST_PR_PARAMETERS = ('builder_profile','source')
TEST_PR_SOURCE = ('repository','pr_number','commit_sha')
TEST_PR_GATES = ('offline_build','isolated_runtime_checks','source_commit','artifact_sealed')
CANARY_ACTION = 'HK_STAGING_CANARY'
VERIFY_ACTION = 'HK_STAGING_VERIFY'
CANARY_GATES = ('compose_baseline','env_baseline','expected_current_image','candidate_image',
                'python_compile','alembic_head','container_isolation','container_cleanup')
VERIFY_GATES = ('alembic_current','alembic_head','api_health','candidate_image',
                'compose_baseline','env_baseline','expected_current_image','worker_process_liveness')
# A rollback undoes one already-executed deployment.  It is the same kind of act as a
# deployment -- it mutates the same eight business services -- so it takes the same kind
# of authority: an authenticated GitHub identity opening an exact Request.  What it may
# *name* is narrower.  A deployment's Request names an environment and lets the Command
# Center derive the candidate; a rollback's names an environment and lets the Command
# Center derive which deployment to undo.  Neither names a target: the eight services
# come from `SERVICES` above, and the images come from the source deployment's own
# deploy record, which the executor re-verifies on the host, byte by byte, before it
# touches anything.
ROLLBACK_ACTION = 'HK_STAGING_ROLLBACK'
ROLLBACK_SCOPE = 'HK_STAGING_ROLLBACK_FIXED_EIGHT'
# The rollback Task's parameter block, exactly as the HK agent's own validator states
# it: hk_agent/deployment_actions.py refuses any other name and any missing one.
ROLLBACK_PARAMETERS = ('release_id','source_deploy_task_id','approval_id')
# The authorisation's exact field set.  A deployment's approval binds the plan derived
# for a candidate; a rollback's binds the pair of signed objects it undoes.
ROLLBACK_AUTHORIZATION_FIELDS = ('schema_version','approval_id','approved_by','approved_at',
                                 'expires_at','scope','source_deploy_task_sha256',
                                 'source_deploy_evidence_sha256','request_sha256')
# The gates a deployment's own Evidence must carry for that deployment to be a rollback
# source.  `record_path` is deliberately not among them: the deploy runtime writes it
# beside the gates as an annotation -- the path of the immutable record it just wrote --
# and not as a gate.  That is also why the generic "every value in gate_results must be
# PASS or False" rule the canary and TEST_PR proofs apply cannot be reused for a DEPLOY
# Evidence: applying it would refuse every real deployment.
DEPLOY_GATES = ('candidate_binding','current_state','durable_previous_state','fixed_scope',
                'no_migration','post_deploy_verify')
# A rollback Task never outlives either its authorisation or this window.
ROLLBACK_TASK_WINDOW = dt.timedelta(seconds=300)
# How long a probe of live state may be cited for. A candidate's identity is
# content-bound and never expires, but "the host is what we think it is" is a
# statement about the present, so the canary and the preflight do expire.
CANARY_EVIDENCE_MAX_AGE = 1800
VERIFY_EVIDENCE_MAX_AGE = 300
APPROVAL_MAX_LIFE = dt.timedelta(minutes=15)
PREFLIGHT_TASK_WINDOW = dt.timedelta(seconds=300)

class Reject(ValueError): pass

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()

def digest(value): return hashlib.sha256(canonical(value)).hexdigest()

def request_digest(request): return digest(request)

def parse_json(raw):
    def pairs(items):
        out={}
        for k,v in items:
            if k in out: raise Reject('duplicate_json_key')
            out[k]=v
        return out
    def constant(_): raise Reject('invalid_json_constant')
    try: return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)
    except (ValueError,UnicodeError,RecursionError) as exc: raise Reject('invalid_json') from exc

def exact(value, fields, reason):
    if not isinstance(value,dict) or set(value)!=set(fields): raise Reject(reason)

def match(value, pattern, reason):
    if not isinstance(value,str) or pattern.fullmatch(value) is None: raise Reject(reason)
    return value

def timestamp(value):
    if not isinstance(value,str): raise Reject('invalid_time')
    try: result=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError as exc: raise Reject('invalid_time') from exc
    if result.tzinfo is None: raise Reject('naive_time')
    return result

def read_secure(path, max_bytes=131072):
    path=pathlib.Path(path)
    # The production location is fixed and root-owned; symlinked parents and
    # group/world-writable plan directories cannot supply authority records.
    parent=path.parent
    if parent.resolve()!=parent.absolute(): raise Reject('trusted_directory_symlink')
    try: info=parent.stat()
    except OSError as exc: raise Reject('trusted_directory_unavailable') from exc
    if info.st_uid!=TRUSTED_UID or info.st_mode & 0o022: raise Reject('untrusted_directory')
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=TRUSTED_UID or info.st_mode & 0o022:
                raise Reject('untrusted_file')
            data=stream.read(max_bytes+1)
            if len(data)>max_bytes: raise Reject('trusted_file_oversized')
            return data
    except OSError as exc: raise Reject('trusted_file_unavailable') from exc

def public_key(raw):
    try:
        key=serialization.load_ssh_public_key(raw) if raw.startswith(b'ssh-') else serialization.load_pem_public_key(raw)
        if not isinstance(key,Ed25519PublicKey): raise ValueError('key type')
        return key
    except ValueError as exc: raise Reject('invalid_trust_key') from exc

def load_keys(store=None):
    """The two published verification keys, read the secure way, or a refusal."""
    store=pathlib.Path(store if store is not None else STORE)
    return (public_key(read_secure(store/'authority.pub',4096)),
            public_key(read_secure(store/'hk-evidence.pub',4096)))

def verify_signed(value,key,encoding):
    if not isinstance(value,dict) or not isinstance(value.get('signature'),str): raise Reject('missing_signature')
    unsigned={k:v for k,v in value.items() if k!='signature'}
    try:
        signature=bytes.fromhex(value['signature']) if encoding=='hex' else base64.b64decode(value['signature'],validate=True)
        key.verify(signature,canonical(unsigned))
    except Exception as exc: raise Reject('invalid_signature') from exc
    return unsigned

def proof(task,evidence,action,authority_key,hk_key,at,max_age):
    verify_signed(task,authority_key,'hex'); verify_signed(evidence,hk_key,'base64')
    exact(task,TASK_FIELDS,'task_fields')
    if task['schema_version']!='1' or task['authority']!='GO-COMMAND-CENTER': raise Reject('task_authority')
    if task['action_id']!=action or task['environment']!=ENVIRONMENT: raise Reject('proof_scope')
    for k in ['task_id','nonce','action_id','environment']:
        if evidence.get(k)!=task[k]: raise Reject('proof_binding')
    match(task['task_id'],re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z'),'task_id')
    match(task['nonce'],re.compile(r'[A-Za-z0-9_-]{1,128}\Z'),'task_nonce')
    parameters=task['parameters']
    expected={'release_id','candidate_image_id','expected_current_image_id'}
    if action==CANARY_ACTION: expected.add('candidate_package_sha256')
    if 'candidate_contract_sha256' in parameters:
        expected.add('candidate_contract_sha256')
        identity=match(parameters['candidate_contract_sha256'],SHA,'contract_identity')
        if evidence.get('candidate_contract_sha256')!=identity: raise Reject('proof_contract_binding')
    exact(parameters,expected,'proof_parameters')
    for k in ['release_id','candidate_image_id','expected_current_image_id']:
        if evidence.get(k)!=parameters[k]: raise Reject('proof_image_or_release')
    match(parameters['release_id'],EXECUTOR_IDENT,'proof_release_id')
    if evidence.get('schema_version')!='1' or evidence.get('status')!='SUCCESS': raise Reject('proof_not_success')
    if evidence.get('executor_result')!=('CANARY_OK' if action==CANARY_ACTION else 'VERIFY_OK'):
        raise Reject('proof_result')
    issued,expires=timestamp(task['issued_at']),timestamp(task['expires_at'])
    started,completed=timestamp(evidence.get('started_at')),timestamp(evidence.get('completed_at'))
    if not issued<=started<=completed<=expires or completed>at+dt.timedelta(seconds=30) or at-completed>dt.timedelta(seconds=max_age):
        raise Reject('proof_stale_or_unbound_time')
    gates=evidence.get('gate_results')
    required=CANARY_GATES if action==CANARY_ACTION else VERIFY_GATES
    if not isinstance(gates,dict) or any(gates.get(k)!='PASS' for k in required): raise Reject('proof_gate_failed')
    if any(v != 'PASS' and v is not False for v in gates.values()): raise Reject('proof_contains_failed_gate')
    return completed

def candidate_repository(value):
    """The plan's repository, in its slug form or as a remote that names it.

    The TEST_PR Task names the repository by its ssh remote
    (`git@github.com:<slug>.git`) while the plan records the slug, so the two spellings
    have to be recognised -- and nothing else: a fork, another repository or a bare
    hostname is refused rather than normalised into an acceptance.
    """
    if not isinstance(value,str) or not value: raise Reject('test_pr_repository')
    trimmed=value[:-4] if value.endswith('.git') else value
    parts=trimmed.replace(':','/').split('/')
    if len(parts)<2 or '%s/%s' % (parts[-2],parts[-1])!=REPOSITORY: raise Reject('test_pr_repository')
    return value

def test_pr_proof(task,evidence,authority_key,hk_key):
    """The signed TEST_PR this candidate was admitted by.

    This is what replaces `sealed_node = PASS`. sealed_node's name stood for one
    technical fact -- the artifact a deployment loads is the sealed product of this
    exact source -- and this function establishes that fact from signed objects
    instead of from a declared string: the Task was built for a named pull request of
    the candidate repository, and the Evidence reports the commit it built from, the
    artifact it produced, the sealed package that artifact was written into, and that
    the sealing was proven.

    Unlike the canary and the preflight, this proof carries no freshness window. It is
    a statement about an immutable candidate, and its binding is by content: a TEST_PR
    of a different commit, a different artifact or a different package is refused here
    whatever its timestamp, and re-running it for the same candidate is pointless
    rather than required.
    """
    verify_signed(task,authority_key,'hex'); verify_signed(evidence,hk_key,'base64')
    exact(task,TASK_FIELDS,'task_fields')
    if task['schema_version']!='1' or task['authority']!='GO-COMMAND-CENTER': raise Reject('task_authority')
    if task['action_id']!=TEST_PR_ACTION or task['environment']!=ENVIRONMENT: raise Reject('test_pr_scope')
    for k in ['task_id','nonce','action_id','environment']:
        if evidence.get(k)!=task[k]: raise Reject('test_pr_binding')
    match(task['task_id'],re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z'),'task_id')
    match(task['nonce'],re.compile(r'[A-Za-z0-9_-]{1,128}\Z'),'task_nonce')
    parameters=task['parameters']
    exact(parameters,TEST_PR_PARAMETERS,'test_pr_parameters')
    source=parameters['source']
    exact(source,TEST_PR_SOURCE,'test_pr_source_fields')
    candidate_repository(source['repository'])
    match(source['pr_number'],PR_NUMBER,'test_pr_pr_number')
    match(source['commit_sha'],COMMIT,'test_pr_commit')
    if not isinstance(parameters['builder_profile'],str) or not parameters['builder_profile']:
        raise Reject('test_pr_builder_profile')
    # The Evidence names the exact Task bytes it executed; recomputing that digest is
    # what stops an Evidence about some other Task from standing in for this one.
    if evidence.get('task_canonical_sha256')!=digest({k:v for k,v in task.items() if k!='signature'}):
        raise Reject('test_pr_task_digest_binding')
    issued,expires=timestamp(task['issued_at']),timestamp(task['expires_at'])
    started,completed=timestamp(evidence.get('started_at')),timestamp(evidence.get('completed_at'))
    if not issued<=started<=completed<=expires: raise Reject('test_pr_stale_or_unbound_time')
    if evidence.get('schema_version')!='1' or evidence.get('status')!='SUCCESS': raise Reject('test_pr_not_success')
    if evidence.get('executor_result')!='TEST_PR_OK': raise Reject('test_pr_result')
    # A build step must never be able to become a deployment.
    if evidence.get('deployment_performed') is not False: raise Reject('test_pr_deployment_performed')
    if evidence.get('source_commit_sha')!=source['commit_sha']: raise Reject('test_pr_commit_binding')
    if str(evidence.get('source_pr_number'))!=source['pr_number']: raise Reject('test_pr_pr_binding')
    if evidence.get('artifact_durability')!='PROVEN': raise Reject('test_pr_artifact_not_durable')
    # The Evidence's product field is `built_image_id`, not `artifact_digest`.  The HK
    # agent's own contract names it: hk_agent/transport.py:315 lists built_image_id in
    # the required TEST_PR field set and :337 writes exactly that name.  Reading
    # `artifact_digest` therefore matched nothing on a real signed Evidence, and this
    # gate refused every DEPLOY with test_pr_artifact.
    match(evidence.get('built_image_id'),IMAGE,'test_pr_artifact')
    package=evidence.get('artifact_package')
    if not isinstance(package,dict): raise Reject('test_pr_package')
    match(package.get('package_sha256'),SHA,'test_pr_package_sha256')
    if package.get('schema')!='go.sealed-artifact.v1': raise Reject('test_pr_package_schema')
    if package.get('image_id')!=evidence.get('built_image_id'): raise Reject('test_pr_package_image')
    gates=evidence.get('gate_results')
    if not isinstance(gates,dict) or any(gates.get(k)!='PASS' for k in TEST_PR_GATES): raise Reject('test_pr_gate_failed')
    if any(v != 'PASS' and v is not False for v in gates.values()): raise Reject('test_pr_contains_failed_gate')
    return evidence

def rollback_source_proof(task,evidence,authority_key,hk_key):
    """The signed DEPLOY a rollback would undo, and the record it produced.

    A rollback has no candidate of its own.  Everything it will do is a function of this
    one pair of objects: the Task the Command Center signed and the Evidence the Hong
    Kong agent signed for it.  The record those two name is what the executor opens --
    under a fixed path whose digest it re-hashes itself -- to learn which eight images to
    restore, and the executor refuses if that record has moved or if the host no longer
    looks like the state that deployment left.

    Like `test_pr_proof`, and unlike the canary and the preflight, this carries no
    freshness window.  A deployment's Task and its Evidence are immutable and their
    binding is by content: the same pair describes the same deployment forever, and a
    rollback of it is the same act whenever it is authorised.  Whether the *host* is
    still in the state that deployment left is a different question, asked by the
    executor at execution time against files and containers it can see -- which is
    strictly stronger than a window this side could compute from a published timestamp,
    and needs no step from a human.
    """
    verify_signed(task,authority_key,'hex'); verify_signed(evidence,hk_key,'base64')
    exact(task,TASK_FIELDS,'task_fields')
    if task['schema_version']!='1' or task['authority']!='GO-COMMAND-CENTER': raise Reject('task_authority')
    if task['action_id']!=ACTION or task['environment']!=ENVIRONMENT: raise Reject('rollback_source_scope')
    for k in ['task_id','nonce','action_id','environment']:
        if evidence.get(k)!=task[k]: raise Reject('proof_binding')
    match(task['task_id'],re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z'),'task_id')
    match(task['nonce'],re.compile(r'[A-Za-z0-9_-]{1,128}\Z'),'task_nonce')
    parameters=task['parameters']
    fields={'release_id','candidate_image_id','candidate_package_sha256','expected_current_image_id','canary_evidence_id','approval_id'}
    contract_sha=parameters.get('candidate_contract_sha256') if isinstance(parameters,dict) else None
    if contract_sha is not None:
        fields.add('candidate_contract_sha256');match(contract_sha,SHA,'contract_identity')
        if evidence.get('candidate_contract_sha256')!=contract_sha: raise Reject('proof_contract_binding')
    exact(parameters,fields,'rollback_source_parameters')
    for k in ['release_id','candidate_image_id','expected_current_image_id']:
        if evidence.get(k)!=parameters[k]: raise Reject('proof_image_or_release')
    match(parameters['release_id'],EXECUTOR_IDENT,'proof_release_id')
    if evidence.get('schema_version')!='1' or evidence.get('status')!='SUCCESS':
        raise Reject('rollback_source_not_success')
    if evidence.get('executor_result')!='DEPLOY_OK': raise Reject('rollback_source_result')
    issued=timestamp(task['issued_at'])
    started,completed=timestamp(evidence.get('started_at')),timestamp(evidence.get('completed_at'))
    # The source's own timeline has to be coherent: an executor cannot start before the Task
    # that told it to start was issued, and cannot finish before it started.  What is
    # deliberately NOT asserted here is `completed <= expires` -- the bound the canary and
    # the TEST_PR proofs use -- because a deployment Task's expiry is the expiry of the
    # *authorisation that produced it*, not a promise that the work fits inside it.  The one
    # live source this contract exists for breaks that bound: issued 06:03:28Z, expires
    # 06:06:29Z, started and completed 06:07:06Z, status SUCCESS, DEPLOY_OK.  A bound no real
    # source can satisfy is not fail-closed, it is fail-forever, and the freshness a rollback
    # needs is carried by the authorisation instead: it must postdate this `completed_at`.
    if not issued<=started<=completed: raise Reject('rollback_source_unbound_time')
    if contract_sha:
        try: execution_window.validate(task,evidence)
        except execution_window.Invalid as exc: raise Reject(str(exc)) from exc
    if evidence.get('deploy_record_schema_version')!='2': raise Reject('rollback_source_record_binding')
    record_id,record_sha256=evidence.get('deploy_record_id'),evidence.get('deploy_record_sha256')
    if not isinstance(record_id,str) or SHA.fullmatch(record_id) is None:
        raise Reject('rollback_source_record_binding')
    if not isinstance(record_sha256,str) or SHA.fullmatch(record_sha256) is None:
        raise Reject('rollback_source_record_binding')
    gates=evidence.get('gate_results')
    required=tuple(k for k in DEPLOY_GATES if k!='no_migration')+('migration_source_bound','rds_prestate_match','alembic_forward_migration','rds_poststate_match','migration_evidence') if contract_sha else DEPLOY_GATES
    if contract_sha and (not isinstance(gates,dict) or not SHA.fullmatch(str(gates.get('migration_record_sha256','')))): raise Reject('migration_receipt_missing')
    if not isinstance(gates,dict) or any(gates.get(k)!='PASS' for k in required):
        raise Reject('rollback_source_gate_failed')
    return {'record_id':record_id,'record_sha256':record_sha256,
            'candidate_image_id':parameters['candidate_image_id'],
            'expected_current_image_id':parameters['expected_current_image_id'],
            'completed_at':completed,'migration_required':contract_sha is not None}

def plan_id_for(candidate,canary_task):
    """The one plan name this gate will accept, derived rather than chosen.

    It is a function of the candidate and of the canary run that witnessed the live
    host, so it cannot be picked by a caller (a caller-chosen plan name was the last
    thing a Request could still steer) and a fresh canary -- which a retry needs, since
    a consumed plan may not be reused -- legitimately yields a fresh name.
    """
    try: release=canary_task['parameters']['release_id']
    except (TypeError,KeyError) as exc: raise Reject('plan_id_not_derived') from exc
    if not isinstance(release,str) or not release: raise Reject('plan_id_not_derived')
    return 'hkstg-%s-%s-%s' % (candidate['source_commit'][:12],candidate['image_id'][7:19],
                               hashlib.sha256(release.encode()).hexdigest()[:12])

def approval_id_for(request_sha256):
    match(request_sha256,SHA,'invalid_request_digest')
    return 'approval-'+request_sha256[:16]

def rollback_approval_id_for(request_sha256):
    """The one approval id a rollback authorisation may carry.

    Derived from the Request's canonical digest, exactly as a deployment's is, and given
    its own prefix so a rollback authorisation and a deployment authorisation of the same
    Request can never be confused for one another.
    """
    match(request_sha256,SHA,'invalid_request_digest')
    return 'approval-rollback-'+request_sha256[:16]

def validate_bundle(bundle,plan_id,authority_key,hk_key,at,approval_identity=None,request_sha256=None):
    # Fail closed on the approval authority before anything else is read. The
    # authority is an authenticated GitHub identity: `approval_identity` is the
    # login GitHub reports for the Request PR's author, and it is supplied by the
    # Bridge from the platform's own answer rather than from anything the caller
    # wrote into the Request.
    if approval_identity is None: raise Reject('approval_identity_missing')
    if approval_identity not in APPROVAL_IDENTITIES: raise Reject('approval_identity_not_authorised')
    # The approval is the Request, so the gate has to be told which Request. The
    # Bridge passes the digest of the canonical Request it just validated; without it
    # there is nothing to bind the approval to and the gate refuses rather than
    # accepting an approval that could name any Request.
    if request_sha256 is None: raise Reject('approval_request_digest_missing')
    match(request_sha256,SHA,'invalid_request_digest')
    exact(bundle,BUNDLE_FIELDS,'bundle_fields')
    plan=bundle['plan']; approval=bundle['approval']
    contract_sha=plan.get('candidate_contract_sha256') if isinstance(plan,dict) else None
    exact(plan,(*PLAN_FIELDS,'candidate_contract_sha256') if contract_sha is not None else PLAN_FIELDS,'plan_fields')
    if plan['schema_version']!='1' or plan['plan_id']!=plan_id or plan['environment']!=ENVIRONMENT or plan['action_id']!=ACTION:
        raise Reject('plan_scope')
    match(plan_id,IDENT,'plan_id')
    if plan['target_services']!=SERVICES or plan['protected_non_targets']!=['redis','caddy']: raise Reject('fixed_topology_required')
    if any(plan[k] is not False for k in ['production','automatic_rollback']): raise Reject('forbidden_operation')
    if plan['migration'] is not (contract_sha is not None): raise Reject('forbidden_operation')
    candidate=plan['candidate']
    exact(candidate,CANDIDATE_FIELDS,'candidate_fields')
    if candidate['repository']!=REPOSITORY: raise Reject('candidate_repository')
    for k in ['source_commit','application_git_tree']: match(candidate[k],COMMIT,k)
    for k in ['source_tree_sha256','package_sha256']: match(candidate[k],SHA,k)
    match(candidate['image_id'],IMAGE,'candidate_image')
    # No repo digest is required, and none may be invented: a registry manifest
    # digest is not an image config ID, and a host-built candidate has no digest
    # at all. image_id is the artifact identity; package_sha256 is the sealed
    # package the executor resolves that same image from.
    match(plan['expected_current_image_id'],IMAGE,'current_image')
    contract=None
    if contract_sha is not None:
        try: contract=candidate_contract.load(contract_sha,candidate_contract.CC_STORE)
        except candidate_contract.Reject as exc: raise Reject(str(exc)) from exc
        if contract['candidate']!=candidate or contract['expected_current_image_id']!=plan['expected_current_image_id']: raise Reject('migration_plan_binding')
    exact(approval,APPROVAL_FIELDS,'approval_fields')
    if approval['schema_version']!='1' or approval['scope']!='HK_STAGING_DEPLOY_FIXED_EIGHT' or approval['plan_sha256']!=digest(plan):
        raise Reject('approval_binding')
    # The approval is the Request's own content, so the digest it carries must be that
    # Request and nothing else.
    if approval['request_sha256']!=request_sha256: raise Reject('approval_request_mismatch')
    match(approval['approval_id'],EXECUTOR_IDENT,'approval_id')
    match(approval['approved_by'],IDENT,'human_reviewer_id')
    # The approval is the authenticated identity's own statement, so the name it
    # carries must be that identity and nothing else.
    if approval['approved_by']!=approval_identity: raise Reject('approval_identity_mismatch')
    approved,expires=timestamp(approval['approved_at']),timestamp(approval['expires_at'])
    if approved>at or expires<=at+dt.timedelta(seconds=60) or expires-approved>APPROVAL_MAX_LIFE: raise Reject('approval_expired_or_invalid')
    for k in ['test_pr_task','test_pr_evidence','canary_task','canary_evidence','preflight_task','preflight_evidence']:
        if plan[k+'_sha256']!=digest(bundle[k]): raise Reject('proof_hash_binding')
    test_pr=test_pr_proof(bundle['test_pr_task'],bundle['test_pr_evidence'],authority_key,hk_key)
    # The candidate block is not taken on trust: the signed TEST_PR has to name the
    # same source and the same artifact, and the artifact has to be the sealed package
    # the executor will resolve. This is the bind that sealed_node used to stand for.
    if test_pr['source_commit_sha']!=candidate['source_commit']: raise Reject('test_pr_candidate_source_binding')
    if test_pr['built_image_id']!=candidate['image_id']: raise Reject('test_pr_candidate_artifact_binding')
    if test_pr['artifact_package']['package_sha256']!=candidate['package_sha256']: raise Reject('test_pr_candidate_package_binding')
    canary_checked=proof(bundle['canary_task'],bundle['canary_evidence'],CANARY_ACTION,authority_key,hk_key,at,CANARY_EVIDENCE_MAX_AGE)
    checked=proof(bundle['preflight_task'],bundle['preflight_evidence'],VERIFY_ACTION,authority_key,hk_key,at,VERIFY_EVIDENCE_MAX_AGE)
    cp=bundle['canary_task']['parameters'];vp=bundle['preflight_task']['parameters']
    if cp.get('candidate_contract_sha256')!=contract_sha: raise Reject('canary_contract_binding')
    if contract is not None and digest(bundle['test_pr_evidence'])!=contract['rehearsal']['binding']['test_pr_evidence_sha256']:
        raise Reject('migration_test_pr_evidence_binding')
    if (cp['candidate_image_id'],cp['candidate_package_sha256'],cp['expected_current_image_id'])!=(candidate['image_id'],candidate['package_sha256'],plan['expected_current_image_id']): raise Reject('canary_candidate_binding')
    if vp['candidate_image_id']!=plan['expected_current_image_id'] or vp['expected_current_image_id']!=plan['expected_current_image_id']:
        raise Reject('preflight_current_image_binding')
    # The name is a function of the candidate and of the canary run, never a choice.
    # Checked last because it reads the canary Task, which is only proven well-formed
    # by the proof above.
    if plan_id!=plan_id_for(candidate,bundle['canary_task']): raise Reject('plan_id_not_derived')
    if approval['approval_id']!=approval_id_for(request_sha256): raise Reject('approval_id_not_derived')
    if approved < max(canary_checked,checked): raise Reject('approval_predates_evidence')
    # A task never outlives either the approval or its fresh preflight window.
    deadline=min(expires,checked+PREFLIGHT_TASK_WINDOW,at+dt.timedelta(minutes=5))
    if deadline<=at+dt.timedelta(seconds=60): raise Reject('preflight_near_expiry')
    return {'plan_id':plan_id,'plan_sha256':digest(plan),'bundle_sha256':digest(bundle),
            # Who authorised this, so the reconciliation path re-reads the plan under
            # the same authenticated identity rather than needing a new one.
            'approval_identity':approval_identity,'request_sha256':request_sha256,
            'approval_id':approval['approval_id'],'source_commit':candidate['source_commit'],
            'package_sha256':candidate['package_sha256'],'deadline':deadline,
            'parameters':{'candidate_image_id':candidate['image_id'],'candidate_package_sha256':candidate['package_sha256'],
             'expected_current_image_id':plan['expected_current_image_id'],
             'canary_evidence_id':bundle['canary_task']['parameters']['release_id'],'approval_id':approval['approval_id'],
             **({'candidate_contract_sha256':contract_sha} if contract_sha else {})}}

def validate_rollback(release_id,authorization,source_task,source_evidence,
                      authority_key,hk_key,at,approval_identity=None,request_sha256=None):
    """Whether this exact rollback Request may become a Task, and what that Task may carry.

    The authority has the same shape as a deployment's -- an authenticated GitHub
    identity opened an exact Request, and that Request *is* the one-time authorisation --
    because the act has the same weight.  What differs is what is being authorised.  A
    deployment's approval binds the plan derived for a candidate; a rollback's binds the
    pair of signed objects it undoes, because those two objects are the whole of what a
    rollback is.  Neither names a target, and `release_id` here is only the label this run
    and its Evidence are addressed by: which eight images to restore is read by the
    executor out of the source Evidence's deploy record, re-hashed on the host.
    """
    if approval_identity is None: raise Reject('approval_identity_missing')
    if approval_identity not in APPROVAL_IDENTITIES: raise Reject('approval_identity_not_authorised')
    if request_sha256 is None: raise Reject('approval_request_digest_missing')
    match(request_sha256,SHA,'invalid_request_digest')
    match(release_id,EXECUTOR_IDENT,'rollback_release_id')
    exact(authorization,ROLLBACK_AUTHORIZATION_FIELDS,'rollback_authorization_fields')
    if authorization['schema_version']!='1' or authorization['scope']!=ROLLBACK_SCOPE:
        raise Reject('rollback_scope')
    if authorization['request_sha256']!=request_sha256: raise Reject('approval_request_mismatch')
    match(authorization['approval_id'],EXECUTOR_IDENT,'approval_id')
    match(authorization['approved_by'],IDENT,'human_reviewer_id')
    if authorization['approved_by']!=approval_identity: raise Reject('approval_identity_mismatch')
    approved,expires=timestamp(authorization['approved_at']),timestamp(authorization['expires_at'])
    if approved>at or expires<=at+dt.timedelta(seconds=60) or expires-approved>APPROVAL_MAX_LIFE:
        raise Reject('approval_expired_or_invalid')
    source=rollback_source_proof(source_task,source_evidence,authority_key,hk_key)
    if source.get('migration_required'): raise Reject('migration_rollback_compatibility_unproven')
    # Recomputed from the objects themselves rather than taken from the authorisation's
    # own word: an authorisation naming a different deployment, or one whose Evidence was
    # replaced, is refused here instead of being read as "some deployment".
    if authorization['source_deploy_task_sha256']!=digest(source_task):
        raise Reject('rollback_authorization_binding')
    if authorization['source_deploy_evidence_sha256']!=digest(source_evidence):
        raise Reject('rollback_authorization_binding')
    if authorization['approval_id']!=rollback_approval_id_for(request_sha256):
        raise Reject('rollback_approval_id_not_derived')
    # A rollback can only be authorised once the deployment it undoes has finished: an
    # authorisation older than the source Evidence would be an authorisation to undo
    # something that had not happened yet.
    if approved<source['completed_at']: raise Reject('approval_predates_evidence')
    deadline=min(expires,at+ROLLBACK_TASK_WINDOW)
    if deadline<=at+dt.timedelta(seconds=60): raise Reject('approval_expired_or_invalid')
    return {'action_id':ROLLBACK_ACTION,'approval_identity':approval_identity,
            'request_sha256':request_sha256,'approval_id':authorization['approval_id'],
            'release_id':release_id,'source_deploy_task_id':source_task['task_id'],
            'source_deploy_task_sha256':digest(source_task),
            'source_deploy_evidence_sha256':digest(source_evidence),
            'source_deploy_record_id':source['record_id'],
            'source_deploy_record_sha256':source['record_sha256'],
            'source_candidate_image_id':source['candidate_image_id'],
            'expected_current_image_id':source['expected_current_image_id'],
            'deadline':deadline,
            'parameters':{'release_id':release_id,
                          'source_deploy_task_id':source_task['task_id'],
                          'approval_id':authorization['approval_id']}}

def load_context(plan_id,at,approval_identity=None,request_sha256=None):
    match(plan_id,IDENT,'plan_id')
    try:
        bundle=parse_json(read_secure(STORE/(plan_id+'.json')))
        authority,hk=load_keys()
        return validate_bundle(bundle,plan_id,authority,hk,at,approval_identity,request_sha256)
    except (OSError,TypeError,KeyError) as exc: raise Reject('deployment_plan_unavailable_or_invalid') from exc

def ensure_unused(context,records):
    if any(r.get('plan_id')==context['plan_id'] or r.get('approval_id')==context['approval_id'] for r in records.values()):
        raise Reject('deployment_plan_or_approval_already_consumed')

def ensure_rollback_unused(records,source_deploy_task_id):
    """A deployment is spent by the first rollback Request that reaches it.

    Refused on any *published* ROLLBACK Task that cites this source -- not only on a
    successful one.  The executor writes its rollback record before it mutates anything,
    so a source whose rollback Task was published but whose Evidence never arrived has
    already been consumed on the host; treating "no Evidence" as "not consumed" would
    offer a second rollback of the same deployment, which the host would refuse anyway.
    A rollback is never automatically retried, by anything.
    """
    for record in (records or {}).values():
        if not isinstance(record,dict) or record.get('status')!='published': continue
        task=record.get('task')
        if not isinstance(task,dict) or task.get('action_id')!=ROLLBACK_ACTION: continue
        parameters=task.get('parameters')
        if isinstance(parameters,dict) and parameters.get('source_deploy_task_id')==source_deploy_task_id:
            raise Reject('rollback_source_already_rolled_back')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Read-only validation of a derived deployment plan. The plan is written by the Command Center, so the two facts the gate cannot re-derive from the file alone -- the authenticated author and the digest of the Request they wrote -- are supplied here from the ledger.')
    parser.add_argument('--check-plan',required=True)
    parser.add_argument('--approval-identity',required=True)
    parser.add_argument('--request-sha256',required=True)
    args=parser.parse_args()
    try:
        context=load_context(args.check_plan,dt.datetime.now(dt.timezone.utc),args.approval_identity,args.request_sha256)
        print(json.dumps({k:v for k,v in context.items() if k not in {'parameters','deadline'}},sort_keys=True))
    except Reject as exc: parser.exit(2,str(exc)+'\n')
