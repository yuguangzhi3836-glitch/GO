"""Candidate deployment gate. No credentials, shell commands, or live defaults."""
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
DIGEST = re.compile(r'[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}\Z')
SERVICES = ['api','recovery-worker','outbox-worker','mobile-push-receipt-worker',
            'reconciliation-worker','mobile-push-worker','mobile-engagement-worker','judgment-worker']
RELEASE_GATES = {'three_end_ux','six_vertical_closed_loop','sealed_node','final_release'}
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
APPROVAL_FIELDS = ('schema_version','approval_id','approved_by','approved_at',
                   'expires_at','scope','plan_sha256')
CANARY_GATES = {'compose_baseline','env_baseline','expected_current_image','candidate_image',
                'python_compile','alembic_head','container_isolation','container_cleanup'}
VERIFY_GATES = {'alembic_current','alembic_head','api_health','candidate_image',
                'compose_baseline','env_baseline','expected_current_image','worker_process_liveness'}

class Reject(ValueError): pass

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()

def digest(value): return hashlib.sha256(canonical(value)).hexdigest()

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
    exact(task,{'schema_version','task_id','nonce','issued_at','expires_at','authority','environment','action_id','parameters','signature'},'task_fields')
    if task['schema_version']!='1' or task['authority']!='GO-COMMAND-CENTER': raise Reject('task_authority')
    if task['action_id']!=action or task['environment']!=ENVIRONMENT: raise Reject('proof_scope')
    for k in ['task_id','nonce','action_id','environment']:
        if evidence.get(k)!=task[k]: raise Reject('proof_binding')
    match(task['task_id'],re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z'),'task_id')
    match(task['nonce'],re.compile(r'[A-Za-z0-9_-]{1,128}\Z'),'task_nonce')
    parameters=task['parameters']
    expected={'release_id','candidate_image_id','expected_current_image_id'}
    if action=='HK_STAGING_CANARY': expected.add('candidate_repo_digest')
    exact(parameters,expected,'proof_parameters')
    for k in ['release_id','candidate_image_id','expected_current_image_id']:
        if evidence.get(k)!=parameters[k]: raise Reject('proof_image_or_release')
    match(parameters['release_id'],EXECUTOR_IDENT,'proof_release_id')
    if evidence.get('schema_version')!='1' or evidence.get('status')!='SUCCESS': raise Reject('proof_not_success')
    if evidence.get('executor_result')!=('CANARY_OK' if action=='HK_STAGING_CANARY' else 'VERIFY_OK'):
        raise Reject('proof_result')
    issued,expires=timestamp(task['issued_at']),timestamp(task['expires_at'])
    started,completed=timestamp(evidence.get('started_at')),timestamp(evidence.get('completed_at'))
    if not issued<=started<=completed<=expires or completed>at+dt.timedelta(seconds=30) or at-completed>dt.timedelta(seconds=max_age):
        raise Reject('proof_stale_or_unbound_time')
    gates=evidence.get('gate_results')
    required=CANARY_GATES if action=='HK_STAGING_CANARY' else VERIFY_GATES
    if not isinstance(gates,dict) or any(gates.get(k)!='PASS' for k in required): raise Reject('proof_gate_failed')
    if any(v != 'PASS' and v is not False for v in gates.values()): raise Reject('proof_contains_failed_gate')
    return completed

def validate_bundle(bundle,plan_id,authority_key,hk_key,at,approval_identity=None):
    # Fail closed on the approval authority before anything else is read. The
    # authority is an authenticated GitHub identity: `approval_identity` is the
    # login GitHub reports for the Request PR's author, and it is supplied by the
    # Bridge from the platform's own answer rather than from anything the caller
    # wrote into the Request.
    if approval_identity is None: raise Reject('approval_identity_missing')
    if approval_identity not in APPROVAL_IDENTITIES: raise Reject('approval_identity_not_authorised')
    exact(bundle,{'plan','approval','canary_task','canary_evidence','preflight_task','preflight_evidence'},'bundle_fields')
    plan=bundle['plan']; approval=bundle['approval']
    exact(plan,{'schema_version','plan_id','environment','action_id','candidate','expected_current_image_id',
                'target_services','protected_non_targets','migration','production','automatic_rollback','gates',
                'canary_task_sha256','canary_evidence_sha256','preflight_task_sha256','preflight_evidence_sha256'},'plan_fields')
    if plan['schema_version']!='1' or plan['plan_id']!=plan_id or plan['environment']!=ENVIRONMENT or plan['action_id']!=ACTION:
        raise Reject('plan_scope')
    match(plan_id,IDENT,'plan_id')
    if plan['target_services']!=SERVICES or plan['protected_non_targets']!=['redis','caddy']: raise Reject('fixed_topology_required')
    if any(plan[k] is not False for k in ['migration','production','automatic_rollback']): raise Reject('forbidden_operation')
    exact(plan['gates'],RELEASE_GATES,'release_gate_fields')
    if any(v!='PASS' for v in plan['gates'].values()): raise Reject('release_gates_not_pass')
    candidate=plan['candidate']
    exact(candidate,{'repository','source_commit','application_git_tree','source_tree_sha256','package_sha256','image_id','repo_digest'},'candidate_fields')
    if candidate['repository']!='yuguangzhi3836-glitch/GO': raise Reject('candidate_repository')
    for k in ['source_commit','application_git_tree']: match(candidate[k],COMMIT,k)
    for k in ['source_tree_sha256','package_sha256']: match(candidate[k],SHA,k)
    match(candidate['image_id'],IMAGE,'candidate_image');match(candidate['repo_digest'],DIGEST,'candidate_digest')
    if not candidate['repo_digest'].endswith(candidate['image_id'][7:]): raise Reject('executor_digest_contract')
    match(plan['expected_current_image_id'],IMAGE,'current_image')
    exact(approval,APPROVAL_FIELDS,'approval_fields')
    if approval['schema_version']!='1' or approval['scope']!='HK_STAGING_DEPLOY_FIXED_EIGHT' or approval['plan_sha256']!=digest(plan):
        raise Reject('approval_binding')
    match(approval['approval_id'],EXECUTOR_IDENT,'approval_id')
    match(approval['approved_by'],IDENT,'human_reviewer_id')
    # The approval is the authenticated identity's own statement, so the name it
    # carries must be that identity and nothing else.
    if approval['approved_by']!=approval_identity: raise Reject('approval_identity_mismatch')
    approved,expires=timestamp(approval['approved_at']),timestamp(approval['expires_at'])
    if approved>at or expires<=at+dt.timedelta(seconds=60) or expires-approved>dt.timedelta(minutes=15): raise Reject('approval_expired_or_invalid')
    for k in ['canary_task','canary_evidence','preflight_task','preflight_evidence']:
        if plan[k+'_sha256']!=digest(bundle[k]): raise Reject('proof_hash_binding')
    canary_checked=proof(bundle['canary_task'],bundle['canary_evidence'],'HK_STAGING_CANARY',authority_key,hk_key,at,1800)
    checked=proof(bundle['preflight_task'],bundle['preflight_evidence'],'HK_STAGING_VERIFY',authority_key,hk_key,at,300)
    if approved < max(canary_checked,checked): raise Reject('approval_predates_evidence')
    cp=bundle['canary_task']['parameters'];vp=bundle['preflight_task']['parameters']
    if (cp['candidate_image_id'],cp['candidate_repo_digest'],cp['expected_current_image_id'])!=(candidate['image_id'],candidate['repo_digest'],plan['expected_current_image_id']): raise Reject('canary_candidate_binding')
    if vp['candidate_image_id']!=plan['expected_current_image_id'] or vp['expected_current_image_id']!=plan['expected_current_image_id']:
        raise Reject('preflight_current_image_binding')
    # A task never outlives either the approval or its fresh preflight window.
    deadline=min(expires,checked+dt.timedelta(seconds=300),at+dt.timedelta(minutes=5))
    if deadline<=at+dt.timedelta(seconds=60): raise Reject('preflight_near_expiry')
    return {'plan_id':plan_id,'plan_sha256':digest(plan),'bundle_sha256':digest(bundle),
            # Who authorised this, so the reconciliation path re-reads the plan under
            # the same authenticated identity rather than needing a new one.
            'approval_identity':approval_identity,
            'approval_id':approval['approval_id'],'source_commit':candidate['source_commit'],
            'package_sha256':candidate['package_sha256'],'deadline':deadline,
            'parameters':{'candidate_image_id':candidate['image_id'],'candidate_repo_digest':candidate['repo_digest'],
             'expected_current_image_id':plan['expected_current_image_id'],
             'canary_evidence_id':bundle['canary_task']['parameters']['release_id'],'approval_id':approval['approval_id']}}

def load_context(plan_id,at,approval_identity=None):
    match(plan_id,IDENT,'plan_id')
    try:
        bundle=parse_json(read_secure(STORE/(plan_id+'.json')))
        authority=public_key(read_secure(STORE/'authority.pub',4096))
        hk=public_key(read_secure(STORE/'hk-evidence.pub',4096))
        return validate_bundle(bundle,plan_id,authority,hk,at,approval_identity)
    except (OSError,TypeError,KeyError) as exc: raise Reject('deployment_plan_unavailable_or_invalid') from exc

def ensure_unused(context,records):
    if any(r.get('plan_id')==context['plan_id'] or r.get('approval_id')==context['approval_id'] for r in records.values()):
        raise Reject('deployment_plan_or_approval_already_consumed')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Read-only validation of an operator-registered signed deployment plan')
    parser.add_argument('--check-plan',required=True)
    args=parser.parse_args()
    try:
        context=load_context(args.check_plan,dt.datetime.now(dt.timezone.utc))
        print(json.dumps({k:v for k,v in context.items() if k not in {'parameters','deadline'}},sort_keys=True))
    except Reject as exc: parser.exit(2,str(exc)+'\n')
