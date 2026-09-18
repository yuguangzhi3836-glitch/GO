"""Immutable candidate/migration facts; never an approval or a caller command.

Installed on CC and HK with the same bytes. Only a content-addressed root-owned
record may extend the legacy image-only path. A Task binds its exact digest.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

SCHEMA = 'go.hk-candidate-contract.v1'
SAME_SCHEMA = 'go.hk-candidate-contract.v2'
ENVIRONMENT = 'HK-STAGING-01'
REPOSITORY = 'yuguangzhi3836-glitch/GO'
PROFILE = 'go-application-python-v2'
WORKDIR = '/workspace'
SHA = re.compile(r'[0-9a-f]{64}\Z')
COMMIT = re.compile(r'[0-9a-f]{40}\Z')
REVISION = re.compile(r'[0-9][0-9a-z_]{1,79}\Z')
IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
CC_STORE = Path('/etc/go-command-center/candidate-contracts-v1')
HK_STORE = Path('/etc/go-hk-deployctl/candidate-contracts-v1')
CANDIDATE_FIELDS = {'repository','source_commit','application_git_tree',
                    'source_tree_sha256','package_sha256','image_id'}
FIELDS = {'schema','environment','profile','candidate','expected_current_image_id',
          'baseline_revision','target_revision','rehearsal','rehearsal_sha256'}

SAME_FIELDS = (FIELDS - {'rehearsal','rehearsal_sha256'}) | {'migration_required', 'migration_source_digest', 'baseline_migration_source_digest', 'test_pr_evidence_sha256'}

class Reject(ValueError):
    pass

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def parse(raw):
    def unique(items):
        result={}
        for k,v in items:
            if k in result: raise Reject('candidate_contract_duplicate_key')
            result[k]=v
        return result
    try:
        return json.loads(raw,object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError,UnicodeError) as exc:
        raise Reject('candidate_contract_json') from exc

def match(value,pattern):
    if not isinstance(value,str) or not pattern.fullmatch(value):
        raise Reject('candidate_contract_identity')

def validate(value,identity=None):
    same = isinstance(value,dict) and value.get('schema') == SAME_SCHEMA
    if not isinstance(value,dict) or set(value)!=(SAME_FIELDS if same else FIELDS):
        raise Reject('candidate_contract_fields')
    if value['schema'] not in (SCHEMA,SAME_SCHEMA) or value['environment']!=ENVIRONMENT or value['profile']!=PROFILE:
        raise Reject('candidate_contract_scope')
    if identity is not None:
        match(identity,SHA)
        if digest(value)!=identity: raise Reject('candidate_contract_hash')
    candidate=value['candidate']
    if not isinstance(candidate,dict) or set(candidate)!=CANDIDATE_FIELDS:
        raise Reject('candidate_contract_candidate_fields')
    if candidate['repository']!=REPOSITORY: raise Reject('candidate_contract_repository')
    for key in ('source_commit','application_git_tree'): match(candidate[key],COMMIT)
    for key in ('source_tree_sha256','package_sha256'): match(candidate[key],SHA)
    match(candidate['image_id'],IMAGE); match(value['expected_current_image_id'],IMAGE)
    for key in ('baseline_revision','target_revision'): match(value[key],REVISION)
    if same:
        if value['migration_required'] is not False: raise Reject('candidate_contract_no_migration_mode')
        if value['baseline_revision'] != value['target_revision']: raise Reject('candidate_contract_same_revision_required')
        for key in ('migration_source_digest','baseline_migration_source_digest','test_pr_evidence_sha256'): match(value[key],SHA)
        if value['migration_source_digest'] != value['baseline_migration_source_digest']: raise Reject('candidate_contract_graph_mismatch')
        return value
    if value['baseline_revision']==value['target_revision']:
        raise Reject('candidate_contract_forward_required')
    evidence=value['rehearsal']
    if not isinstance(evidence,dict): raise Reject('migration_rehearsal_missing')
    # This is the original writer's byte representation, not a digest of a
    # reworded conclusion. The installer verifies the Actions run independently.
    original=(json.dumps(evidence,sort_keys=True,indent=2)+'\n').encode()
    if hashlib.sha256(original).hexdigest()!=value['rehearsal_sha256']:
        raise Reject('migration_rehearsal_hash')
    if evidence.get('schema')!='go.hk-migration-rehearsal.v1' or evidence.get('status')!='PASS_SCOPED':
        raise Reject('migration_rehearsal_not_pass')
    for key in ('source_binding','migration_lineage','historical_migration_retention',
                'forward_upgrade','existing_data_retention','target_noop'):
        if evidence.get(key)!='PASS': raise Reject('migration_rehearsal_gate:'+key)
    if (evidence.get('database_scope')!='DISPOSABLE_GITHUB_ACTIONS_POSTGRES_ONLY'
        or evidence.get('live_database_touched') is not False
        or evidence.get('migration_required') is not True):
        raise Reject('migration_rehearsal_scope')
    binding=evidence.get('binding',{})
    for ours,theirs in (('source_commit','candidate_sha'),('application_git_tree','candidate_application_tree'),
                        ('source_tree_sha256','candidate_fingerprint_sha256'),
                        ('image_id','artifact_image_id'),('package_sha256','artifact_package_sha256')):
        if candidate[ours]!=binding.get(theirs): raise Reject('migration_candidate_binding')
    if (value['baseline_revision']!=binding.get('baseline_revision')
        or value['target_revision']!=binding.get('target_revision')
        or value['baseline_revision']!=evidence.get('prestate_revision')
        or value['target_revision']!=evidence.get('poststate_revision')):
        raise Reject('migration_revision_binding')
    match(evidence.get('migration_source_digest'),SHA)
    match(binding.get('test_pr_evidence_sha256'),SHA)
    match(evidence.get('tooling_sha'),COMMIT)
    if not re.fullmatch(r'[1-9][0-9]*',str(evidence.get('ci_run_id',''))):
        raise Reject('migration_ci_identity')
    return value

def migration_required(value):
    validate(value)
    return value['schema'] == SCHEMA

def test_pr_digest(value):
    validate(value)
    return value['rehearsal']['binding']['test_pr_evidence_sha256'] if migration_required(value) else value['test_pr_evidence_sha256']

def secure_read(path):
    path=Path(path)
    try:
        # Verify every directory component, not only the immediate parent.
        for parent in (path.parent,*path.parent.parents):
            info=parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
                raise Reject('candidate_contract_directory')
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as handle:
            info=os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
                raise Reject('candidate_contract_owner')
            raw=handle.read(262145)
            if len(raw)>262144: raise Reject('candidate_contract_size')
            return raw
    except OSError as exc:
        raise Reject('candidate_contract_unavailable') from exc

def load(identity,store):
    match(identity,SHA)
    return validate(parse(secure_read(Path(store)/(identity+'.json'))),identity)

def bind(value,candidate,expected,package=None):
    validate(value)
    if value['candidate']['image_id']!=candidate or value['expected_current_image_id']!=expected:
        raise Reject('candidate_contract_image_binding')
    if package is not None and value['candidate']['package_sha256']!=package:
        raise Reject('candidate_contract_package_binding')
    return value

def verify_profile(value,image):
    validate(value)
    if image!=value['candidate']['image_id']: raise Reject('candidate_contract_verify_image')
    return WORKDIR,value['target_revision']

CC_ACTIVE=Path('/etc/go-command-center/active-candidate-v1.json')

def active():
    # Missing means the legacy path. An existing invalid authority never falls
    # back to a previous candidate, including a dangling symlink.
    if not CC_ACTIVE.exists() and not CC_ACTIVE.is_symlink(): return None
    record=parse(secure_read(CC_ACTIVE))
    if not isinstance(record,dict) or set(record)!={'schema','candidate_contract_sha256','admission'} or record['schema']!='go.hk-active-candidate.v1':
        raise Reject('active_candidate_schema')
    identity=record['candidate_contract_sha256'];contract=load(identity,CC_STORE)
    pointer=record['admission'];block=pointer.get('release_candidate_v1',{}) if isinstance(pointer,dict) else {}
    c=contract['candidate']
    pairs={'source_commit':'source_commit','application_tree':'application_git_tree',
           'source_fingerprint':'source_tree_sha256','artifact_digest':'image_id','source_repository':'repository'}
    if any(block.get(k)!=c[v] for k,v in pairs.items()): raise Reject('active_candidate_binding')
    if block.get('artifact_package',{}).get('package_sha256')!=c['package_sha256']:
        raise Reject('active_candidate_package')
    if (block.get('migration_required') is not migration_required(contract) or block.get('migration_head')!=contract['target_revision']
        or block.get('rollback_relation',{}).get('previous_known_good_image_id')!=contract['expected_current_image_id']
        or block.get('candidate_contract_sha256')!=identity):
        raise Reject('active_candidate_migration')
    return record,contract
