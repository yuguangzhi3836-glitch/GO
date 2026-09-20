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
               'migration','production','automatic_rollback','candidate_contract_sha256',
               'test_pr_task_sha256',
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
    exact(parameters,{'release_id','candidate_image_id','candidate_package_sha256',
                      'expected_current_image_id','canary_evidence_id','approval_id',
                      'candidate_contract_sha256'},
          'rollback_source_parameters')
    # The converged candidate's own content address is part of the DEPLOY contract.
    # `validate_bundle` puts it into every DEPLOY Task it derives and the Hong Kong
    # agent echoes that same value into the Evidence it signs, so this proof requires
    # it, refuses a value that is not a digest, and binds the two signed copies to each
    # other: a Task and an Evidence naming different candidates are refused here rather
    # than being read as "some deployment".  The exact set above still refuses every
    # name the derivation does not emit, so the contract is widened by exactly the one
    # field the derivation carries and by nothing else.
    contract_sha=parameters['candidate_contract_sha256']
    match(contract_sha,SHA,'contract_identity')
    if evidence.get('candidate_contract_sha256')!=contract_sha: raise Reject('proof_contract_binding')
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
    if evidence.get('deploy_record_schema_version')!='2': raise Reject('rollback_source_record_binding')
    record_id,record_sha256=evidence.get('deploy_record_id'),evidence.get('deploy_record_sha256')
    if not isinstance(record_id,str) or SHA.fullmatch(record_id) is None:
        raise Reject('rollback_source_record_binding')
    if not isinstance(record_sha256,str) or SHA.fullmatch(record_sha256) is None:
        raise Reject('rollback_source_record_binding')
    gates=evidence.get('gate_results')
    if not isinstance(gates,dict) or any(gates.get(k)!='PASS' for k in DEPLOY_GATES):
        raise Reject('rollback_source_gate_failed')
    return {'record_id':record_id,'record_sha256':record_sha256,
            'candidate_image_id':parameters['candidate_image_id'],
            'expected_current_image_id':parameters['expected_current_image_id'],
            'completed_at':completed}

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
    exact(plan,PLAN_FIELDS,'plan_fields')
    if plan['schema_version']!='1' or plan['plan_id']!=plan_id or plan['environment']!=ENVIRONMENT or plan['action_id']!=ACTION:
        raise Reject('plan_scope')
    match(plan_id,IDENT,'plan_id')
    if plan['target_services']!=SERVICES or plan['protected_non_targets']!=['redis','caddy']: raise Reject('fixed_topology_required')
    if any(plan[k] is not False for k in ['migration','production','automatic_rollback']): raise Reject('forbidden_operation')
    # The candidate this plan is about.  The gate does not recompute it -- the digest
    # has one implementation and it lives with candidate admission -- but it refuses a
    # plan whose digest is absent or malformed, so nothing downstream is ever handed a
    # binding that cannot be checked.  `candidate_fields` is the existing refusal for a
    # plan whose candidate facts do not validate.
    match(plan['candidate_contract_sha256'],SHA,'candidate_fields')
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
             'candidate_contract_sha256':plan['candidate_contract_sha256'],
             'canary_evidence_id':bundle['canary_task']['parameters']['release_id'],'approval_id':approval['approval_id']}}

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

# --------------------------------------------------------------------------- #
# The environment's one mutation slot
# --------------------------------------------------------------------------- #
# The Request, the plan and the Task identities are all per-deployment, so two
# different authorised Requests for the same environment derived two plans, the
# ledger published two Tasks, and the only thing that noticed was the executor's
# own drift check -- after the first deployment had already moved the host. The
# environment itself had no identity in the design, and so nothing to hold.
#
# It has one now.  The slot is keyed by the Task's own `environment` -- the field
# the channel validates and the executor refuses to act outside -- so a second
# environment is a second slot and the two may run in parallel.
#
# What the slot holds about the candidate is deliberately an opaque string: the
# converged candidate's own content address, `candidate_contract_sha256`, carried
# through from the plan.  This module never opens that fact, never resolves it and
# never reads anything it describes -- the identity is recorded so an operator can
# name who holds the environment, not so the guard can reason about the candidate.
# A guard that understood candidates would be a second admission path, and it would
# have to be kept in step with the first.
#
# Three rules this module follows on purpose
# ------------------------------------------
# * The check and the reservation happen inside the caller's existing ledger
#   lock, and the reservation is written before anything is published.  A "check
#   now, mark it later" shape would let two ticks both see an idle environment,
#   which is the time-of-check/time-of-use gap this exists to remove.
# * UNKNOWN is not IDLE.  An action has ended only when its own Evidence says so:
#   `SUCCESS` or `FAILED`, the two statuses the Hong Kong agent's evidence builder
#   writes.  Missing or unreadable Evidence keeps the environment occupied, and an
#   action unresolved for longer than IN_FLIGHT_WINDOW does not become idle -- it
#   becomes a question for an operator, and it still blocks.  No timeout releases
#   the slot by itself.
# * The guard never scans history looking for something to block on.  On first
#   activation it adopts only an action still inside IN_FLIGHT_WINDOW and not yet
#   terminal, because only those can still be running, and it records the rest as
#   ignored.  A months-old `published` record therefore cannot lock an environment
#   forever, and the decision is auditable in the same document.
#
# The refusal statuses are named here rather than in the store, so one place
# decides what "in flight" and "abandoned" mean to a caller.
#
# The document lives in the channel's own state directory, beside `ledger.json` and
# `post-action-verifies.json` -- the same place, for the same reason: it is channel
# state, it is written under the ledger lock, and the unit already allows that one
# directory.  The path is therefore taken from the caller's ledger root rather than
# from a constant here, so a test (or a second channel) cannot accidentally address
# the live one.
ENVIRONMENT_SLOT_NAME = 'environment-slots.json'
SLOT_SCHEMA = 'go.cc-environment-mutation-slots.v1'
SLOT_FIELDS = {'environment','state','action','request_key','request_id','release_id',
               'candidate_identity','candidate_image_id','approval_id','plan_id',
               'triggered_by','reserved_at','stage','task_id','issued_at','released_at',
               'released_reason','adopted'}
SLOT_STATES = ('reserved','abandoned','released')
# The two actions that replace the same business containers.  ROLLBACK is named even
# though this channel publishes no rollback Task today: it is the action the Hong Kong
# launcher runs under the same lock, and a slot table that did not name it would say
# the environment is free while a rollback was in flight.
ROLLBACK_ACTION = 'HK_STAGING_ROLLBACK'
MUTATING_ACTIONS = (ACTION, ROLLBACK_ACTION)
IN_FLIGHT_WINDOW = dt.timedelta(minutes=30)
# A reservation that never reached the ledger means the process died between the
# two writes; nothing was published, so the slot is released rather than left to
# block.  The grace is what keeps a crash inside one tick from looking like a
# completed refusal.
RESERVATION_GRACE = dt.timedelta(minutes=5)
# The terminal statuses of the Hong Kong agent's own evidence builder: `SUCCESS`
# for an executed action, `FAILED` for one its failure closure reported.  A status
# this list does not name is unresolved, never an ending.
TERMINAL_EVIDENCE_STATUSES = ('SUCCESS','FAILED')
ENVIRONMENT_IDENT = re.compile(r'[A-Z0-9][A-Z0-9-]{0,31}\Z')


def slot_iso(value): return value.isoformat().replace('+00:00','Z')


def _elapsed_seconds(at, value):
    try: return (at-timestamp(value)).total_seconds()
    except Reject: return None


def load_environment_slots(path):
    """The slot document, or None when the guard has never been activated.

    A missing file is "not activated yet", which the caller acts on by activating.
    A present but unusable file is a refusal: starting a fresh guard over an
    unreadable one would silently forget an environment that may still be busy.
    """
    target=pathlib.Path(path)
    if not target.exists() and not target.is_symlink(): return None
    value=parse_json(read_secure(target,65536))
    exact(value,{'version','schema','guard_since','environments','legacy'},'environment_slot_store_invalid')
    if value['version']!=1 or value['schema']!=SLOT_SCHEMA: raise Reject('environment_slot_store_invalid')
    timestamp(value['guard_since'])
    if not isinstance(value['environments'],dict) or not isinstance(value['legacy'],dict):
        raise Reject('environment_slot_store_invalid')
    for environment,slot in value['environments'].items():
        match(environment,ENVIRONMENT_IDENT,'environment_slot_store_invalid')
        exact(slot,SLOT_FIELDS,'environment_slot_store_invalid')
        if slot['state'] not in SLOT_STATES or slot['environment']!=environment:
            raise Reject('environment_slot_store_invalid')
        timestamp(slot['reserved_at'])
    return value


def save_environment_slots(slots, path):
    """Write the slot document the way the ledger is written: 0600, fsync, rename.

    The temporary name carries the writer's pid, and that is the one place this differs
    from the ledger.  The ledger can use a single fixed name because every writer of it
    holds the ledger lock; this document is the thing that *states* one environment
    admits one mutation, so a writer that reached it another way must not be able to
    consume another writer's temporary file and then be refused with a reason
    ('environment_slot_store_unwritable') that is not true.
    """
    target=pathlib.Path(path)
    directory=target.parent
    try:
        if not directory.is_dir() or directory.is_symlink(): raise Reject('environment_slot_store_unwritable')
        temporary=directory/('.'+target.name+'.'+str(os.getpid())+'.tmp')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(canonical(slots)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary,target)
        handle=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(handle)
        finally: os.close(handle)
    except OSError as exc:
        raise Reject('environment_slot_store_unwritable') from exc
    return target


def environment_slot(slots, environment):
    """This environment's slot, released ones included, or None."""
    if not isinstance(slots,dict): return None
    entry=(slots.get('environments') or {}).get(environment)
    return entry if isinstance(entry,dict) else None


def environment_blocker(slots, environment):
    """The reason this environment cannot start a mutating action, or None.

    `released` is the only state that does not block: a slot that is reserved,
    or that has been escalated, still holds the environment.
    """
    slot=environment_slot(slots,environment)
    if slot is None or slot.get('state')=='released': return None
    if slot.get('state')=='abandoned':
        return 'abandoned_mutating_action_requires_operator_review',slot
    return 'environment_deployment_in_flight',slot


def environment_slot_payload(environment, slot, token):
    """What is actually known about the holder, and nothing that is not.

    A field whose fact has not been reached yet is reported as null rather than
    invented; `stage` says where in the lifecycle the holder is (`reserved` before
    publication, `published` once the ledger holds its Task, `abandoned` once it
    outlived the window with no terminal Evidence).  `candidate_identity` is the
    content address of the converged candidate this deployment is about; it is
    passed through, never interpreted.
    """
    return {'error':token,'environment':environment,'action':slot.get('action'),
            'release_id':slot.get('release_id'),
            'candidate_identity':slot.get('candidate_identity'),
            'candidate_version':slot.get('candidate_image_id'),
            'triggered_by':slot.get('triggered_by'),'started_at':slot.get('issued_at'),
            'reserved_at':slot.get('reserved_at'),'task_id':slot.get('task_id'),
            'plan_id':slot.get('plan_id'),'request_id':slot.get('request_id'),
            'request_key':slot.get('request_key'),'stage':slot.get('stage'),
            'adopted':bool(slot.get('adopted'))}


def ensure_environment_idle(slots, environment):
    """Refuse when the environment already has a mutating action, naming it.

    Both tokens are raised as literals on purpose: the channel's vocabulary
    contract is derived by scanning this module for the tokens it can emit, so a
    reason assembled from a variable would be a token the contract never had to
    classify.  The detail rides on the exception rather than inside the string, for
    the same reason.
    """
    match(environment,ENVIRONMENT_IDENT,'environment')
    slot=environment_slot(slots,environment)
    if slot is None or slot.get('state')=='released': return None
    if slot.get('state')=='abandoned':
        # An action that outlived the window with no terminal Evidence is not idle:
        # it is a question for an operator, and it keeps holding the environment
        # until one answers.  Nothing here releases it on a timer.
        refusal=Reject('abandoned_mutating_action_requires_operator_review')
    else:
        refusal=Reject('environment_deployment_in_flight')
    refusal.payload=environment_slot_payload(environment,slot,str(refusal))
    raise refusal


def reserve_environment(slots, environment, at, action, request_key, request_id,
                        release_id=None, approval_id=None, plan_id=None,
                        candidate_identity=None, candidate_image_id=None,
                        triggered_by=None, adopted=False):
    """Occupy the environment for one mutating action.

    Called in the same critical section as `ensure_environment_idle`, before the
    Task is published, so the reservation is what a concurrent tick sees.  The
    Task identity is deliberately NOT remembered here: it is read back from the
    ledger during reconciliation, so this document cannot disagree with the record
    of what was actually published.
    """
    match(environment,ENVIRONMENT_IDENT,'environment')
    if action not in MUTATING_ACTIONS: raise Reject('environment_slot_action_not_mutating')
    slots['environments'][environment]={
        'environment':environment,'state':'reserved','action':action,
        'request_key':request_key,'request_id':request_id,'release_id':release_id,
        'candidate_identity':candidate_identity,'candidate_image_id':candidate_image_id,
        'approval_id':approval_id,'plan_id':plan_id,
        'triggered_by':triggered_by,'reserved_at':slot_iso(at),'stage':'reserved',
        'task_id':None,'issued_at':None,'released_at':None,'released_reason':None,
        'adopted':bool(adopted)}
    return slots['environments'][environment]


def release_environment_slot(slots, environment, reason, at):
    """Hand the environment back.  `released` is the one state that does not block."""
    slot=environment_slot(slots,environment)
    if slot is None: return None
    slot['state']='released'
    slot['stage']='released'
    slot['released_at']=slot_iso(at)
    slot['released_reason']=str(reason)[:120]
    return slot


def terminal_evidence_status(read_evidence, task):
    """This Task's own terminal status, or None while the answer is unknown.

    Unreadable or absent Evidence is "not finished", never "finished": the only
    thing that ends an action is the action's own signed result.
    """
    if read_evidence is None: return None
    try: evidence=read_evidence(task)
    except Exception: return None
    if not isinstance(evidence,dict): return None
    status=evidence.get('status')
    return status if status in TERMINAL_EVIDENCE_STATUSES else None


def reconcile_environment_slots(slots, at, records=None, read_evidence=None):
    """Release what has ended, escalate what never did.  Mutates `slots` in place.

    Runs under the same ledger lock as the reservation, so the environment that is
    released here cannot be reserved by a tick that read an older document.
    """
    changes=[]
    environments=slots.get('environments') or {}
    for environment in sorted(environments):
        slot=environments[environment]
        if slot.get('state')!='reserved': continue
        record=(records or {}).get(slot.get('request_key'))
        if not isinstance(record,dict):
            age=_elapsed_seconds(at,slot.get('reserved_at'))
            if age is not None and age>=RESERVATION_GRACE.total_seconds():
                release_environment_slot(slots,environment,'reservation_never_reached_the_bus',at)
                changes.append(environment+':reservation_never_reached_the_bus')
            continue
        task=record.get('task')
        if not isinstance(task,dict) or task.get('action_id') not in MUTATING_ACTIONS:
            release_environment_slot(slots,environment,'reserved_action_is_not_mutating',at)
            changes.append(environment+':reserved_action_is_not_mutating')
            continue
        parameters=task.get('parameters')
        slot['task_id']=task.get('task_id')
        slot['issued_at']=task.get('issued_at')
        slot['stage']='published'
        if isinstance(parameters,dict):
            slot['candidate_image_id']=parameters.get('candidate_image_id')
            if slot.get('candidate_identity') is None:
                slot['candidate_identity']=parameters.get('candidate_contract_sha256')
            if slot.get('release_id') is None: slot['release_id']=parameters.get('release_id')
        status=terminal_evidence_status(read_evidence,task)
        if status is not None:
            release_environment_slot(slots,environment,'terminal_evidence:'+status,at)
            changes.append(environment+':released:'+status)
            continue
        age=_elapsed_seconds(at,slot.get('issued_at') or slot.get('reserved_at'))
        if age is not None and age>=IN_FLIGHT_WINDOW.total_seconds():
            slot['state']='abandoned'
            slot['stage']='abandoned'
            changes.append(environment+':abandoned')
    return changes


def activate_environment_guard(records, at, read_evidence=None):
    """The first slot document, and what it does with the Requests that came before.

    Only an action still inside IN_FLIGHT_WINDOW and not yet terminal can still be
    running, so those are adopted -- newest first, one per environment.  Every
    other historical record is listed as ignored, with the reason, so the decision
    is visible instead of implied.  Nothing older than the window can block.
    """
    slots={'version':1,'schema':SLOT_SCHEMA,'guard_since':slot_iso(at),'environments':{},
           'legacy':{'ignored':[]}}
    ignored=[]
    candidates={}
    for key,record in sorted((records or {}).items()):
        if not isinstance(record,dict) or record.get('status')!='published': continue
        task=record.get('task')
        if not isinstance(task,dict) or task.get('action_id') not in MUTATING_ACTIONS: continue
        environment=task.get('environment')
        if not isinstance(environment,str) or not ENVIRONMENT_IDENT.fullmatch(environment): continue
        entry={'environment':environment,'task_id':task.get('task_id'),
               'issued_at':task.get('issued_at'),'request_key':key}
        age=_elapsed_seconds(at,task.get('issued_at'))
        if age is None or age>=IN_FLIGHT_WINDOW.total_seconds():
            entry['reason']='outside_the_in_flight_window'
            ignored.append(entry)
            continue
        status=terminal_evidence_status(read_evidence,task)
        if status is not None:
            entry['reason']='terminal_evidence:'+status
            ignored.append(entry)
            continue
        previous=candidates.get(environment)
        if previous is not None:
            # Two unresolved actions in one environment is already a finding; the
            # newest is the one that can still be running, and the older one is
            # recorded rather than silently dropped.
            if str(previous['entry']['issued_at']) >= str(entry['issued_at']):
                previous['entry']['reason']='superseded_by_a_newer_unresolved_action'
                ignored.append(previous['entry'])
            else:
                entry['reason']='superseded_by_a_newer_unresolved_action'
                ignored.append(entry)
                continue
        candidates[environment]={'entry':entry,'record':record,'task':task}
    for environment,found in sorted(candidates.items()):
        record,task=found['record'],found['task']
        parameters=task.get('parameters') if isinstance(task.get('parameters'),dict) else {}
        reserve_environment(slots,environment,at,action=task['action_id'],
                            request_key=found['entry']['request_key'],
                            request_id=record.get('request_id'),
                            release_id=parameters.get('release_id'),
                            approval_id=record.get('approval_id') or parameters.get('approval_id'),
                            plan_id=record.get('plan_id'),
                            candidate_identity=parameters.get('candidate_contract_sha256'),
                            candidate_image_id=parameters.get('candidate_image_id'),
                            triggered_by=record.get('approval_identity'),adopted=True)
    slots['legacy']={'ignored':ignored,'adopted':sorted(candidates)}
    return slots

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
