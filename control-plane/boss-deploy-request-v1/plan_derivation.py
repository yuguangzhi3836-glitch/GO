"""Derive the deployment plan bundle from facts the Command Center already holds.

Why this module exists
----------------------
`docs/project/CC_V1_SCOPE_20260916.md` lists, among the things the Boss must never
need, "手工维护 deployment plan", and says that anything on that list becoming a
necessary step of a deployment means V1 is not delivered rather than being an
operating rule.  Until this revision the plan was written by an operator -- the old
`PLAN_CONTRACT.md` said so in as many words -- which made a human-maintained plan a
required step of every deployment, and made the Boss depend on Eason or on the
WorkBudge tooling to get one.  That is the gap this module closes.

Everything it reads is produced by something else, already, without a human:

    the candidate           docs/canonical-baseline/CURRENT_CANDIDATE.json, written by
                            candidate admission from a signed TEST_PR
    the live image          the root-owned VERIFY baseline, i.e. what the host was last
                            verified to be running
    the TEST_PR             the executed TEST_PR Evidence, signed by the HK agent, of
                            the candidate admission named
    the canary              a Task the Bridge signed itself, and its signed Evidence
    the preflight VERIFY    likewise
    the approval            the DEPLOY Request: who GitHub says wrote it, when, and the
                            digest of its canonical content
    the rollback source     the newest DEPLOY Task the Bridge itself published, and that
                            Task's signed Evidence -- the only thing a rollback undoes

The approval *is* the deployment's one-time authorisation.  There is no deploy switch to
consult and nothing standing to reuse: the authorisation exists only because an
authorised GitHub identity opened an exact Request, it is bound to that Request's digest,
it cannot outlive the deployment it authorises, and a second deployment of the same
candidate needs a fresh canary (a fresh plan name) and a fresh Request, because the
ledger refuses a plan or an authorisation it has already recorded.

There is deliberately nothing here for a caller or an operator to fill in.  A DEPLOY
Request therefore carries only the five common fields, exactly like a CANARY Request:
it names an action and an environment, and it steers nothing.

The same holds one level up, for undoing a deployment.  A ROLLBACK Request is the five
common fields; the deployment it undoes is the newest one in the ledger, and the
authority to undo it is the Request itself.  A caller cannot name a deployment, a
service, an image or a target, because there is no field for one -- which is the same
property the deployment side has, applied to the act that reverses it.

Two rules this module follows on purpose
----------------------------------------
* It extracts and joins; it does not decide substance.  Durability, gate results,
  signature validity and every policy question are decided by `go_deploy_request.py`,
  which is the one gate.  What it does check is that the authorities it joins agree --
  a disagreement is refused here with a clear reason instead of being discovered later
  as a confusing proof failure.
* The most recent probe wins.  For the canary and the preflight it takes the newest
  published Task for this candidate and *that* Task's verdict decides -- it never
  quietly falls back to an older successful run, because a failed canary is a finding
  about the candidate and not an inconvenience to route around.
"""
import datetime as dt
import hashlib
import os
import pathlib

import go_deploy_request as deploy_gate
from go_deploy_request import Reject

ADMISSION_POINTER = 'docs/canonical-baseline/CURRENT_CANDIDATE.json'
ADMISSION_SCHEMA = 'go.depth48.current-candidate.v1'
CANDIDATE_SCHEMA = 'go.release-candidate.v1'
SEALED_ARTIFACT_SCHEMA = 'go.sealed-artifact.v1'

def canonical(value): return deploy_gate.canonical(value)

def iso(value): return value.isoformat().replace('+00:00','Z')

def admission_block(pointer):
    """The RELEASE_CANDIDATE_V1 block out of the canonical candidate pointer."""
    if not isinstance(pointer,dict) or pointer.get('schema')!=ADMISSION_SCHEMA:
        raise Reject('candidate_pointer_schema')
    block=pointer.get('release_candidate_v1')
    if not isinstance(block,dict) or block.get('schema')!=CANDIDATE_SCHEMA:
        raise Reject('release_candidate_missing')
    return block

def candidate_from_admission(block):
    """The plan's candidate block, read out of the admission record.

    Every field is an existing admission fact rather than a new one: the source
    binding, the source fingerprint, the immutable artifact identity and the sealed
    package's content address.  What the values mean -- whether that artifact really is
    the sealed product of that source -- is decided by the signed TEST_PR the gate
    verifies, not by this extraction.
    """
    required=('source_repository','source_commit','application_tree','source_fingerprint',
              'artifact_digest','migration_required')
    for name in required:
        if name not in block: raise Reject('candidate_admission_incomplete')
    package=block.get('artifact_package')
    if not isinstance(package,dict) or not isinstance(package.get('package_sha256'),str):
        raise Reject('candidate_admission_incomplete')
    candidate={'repository':block['source_repository'],'source_commit':block['source_commit'],
               'application_git_tree':block['application_tree'],
               'source_tree_sha256':block['source_fingerprint'],
               'package_sha256':package['package_sha256'],
               'image_id':block['artifact_digest']}
    for name in ('repository','source_commit','application_git_tree','source_tree_sha256',
                 'package_sha256','image_id'):
        if not isinstance(candidate[name],str) or not candidate[name]:
            raise Reject('candidate_admission_incomplete')
    return candidate

def expected_current_from(block,verify_baseline):
    """The image a deployment is allowed to replace, joined from two authorities.

    The admission record says which release this candidate succeeds; the root-owned
    VERIFY baseline says which image the host was last verified to be running.  If they
    disagree the derivation has no honest answer, so it refuses here rather than
    deriving a plan around a stale host.  The gate then binds the preflight VERIFY
    Evidence to the same value, so this join is a clear early refusal and not the
    enforcement.
    """
    relation=block.get('rollback_relation')
    previous=relation.get('previous_known_good_image_id') if isinstance(relation,dict) else None
    live=verify_baseline.get('image_id') if isinstance(verify_baseline,dict) else None
    if not isinstance(previous,str) or deploy_gate.IMAGE.fullmatch(previous) is None:
        raise Reject('candidate_known_good_missing')
    if previous!=live: raise Reject('candidate_and_live_current_disagree')
    return previous

def test_pr_task_id(block):
    identity=block.get('test_result_identity')
    if not isinstance(identity,dict): raise Reject('candidate_test_result_missing')
    if identity.get('action_id')!=deploy_gate.TEST_PR_ACTION: raise Reject('candidate_test_result_not_a_test_pr')
    task_id=identity.get('task_id')
    if not isinstance(task_id,str) or not task_id: raise Reject('candidate_test_result_missing')
    return task_id

def published_pairs(records,action):
    """Every published Task of one action in the ledger, newest first."""
    found=[]
    for key,record in (records or {}).items():
        if not isinstance(record,dict) or record.get('status')!='published': continue
        task=record.get('task')
        if not isinstance(task,dict) or task.get('action_id')!=action: continue
        found.append((str(task.get('issued_at') or ''),str(task.get('task_id') or ''),task,record))
    found.sort(key=lambda item:(item[0],item[1]),reverse=True)
    return [(task,record) for _issued,_task_id,task,record in found]

def pair_by_task_id(records,action,task_id,reason):
    for task,record in published_pairs(records,action):
        if task.get('task_id')==task_id: return task,record
    raise Reject(reason)

def bound_to(task,binding):
    parameters=task.get('parameters')
    if not isinstance(parameters,dict): return False
    return all(parameters.get(name)==value for name,value in binding.items())

def latest_pair(records,action,read_evidence,at,max_age,binding,reason):
    """The newest Task for this candidate, and the verdict of its own Evidence.

    The newest Task decides.  If it was refused, or its Evidence never arrived, or it
    is too old to cite a live host, the derivation stops -- an older successful run
    would describe a host state that has already been superseded, and citing it would
    be the same mistake as citing a stale VERIFY.
    """
    matching=[pair for pair in published_pairs(records,action) if bound_to(pair[0],binding)]
    if not matching: raise Reject(reason+':no_task_for_this_candidate')
    task,record=matching[0]
    try: evidence=read_evidence(task)
    except Exception as exc: raise Reject(reason+':evidence_unreadable') from exc
    if not isinstance(evidence,dict): raise Reject(reason+':evidence_unreadable')
    if evidence.get('status')!='SUCCESS':
        raise Reject('%s:%s' % (reason,evidence.get('executor_result') or 'not_success'))
    try:
        completed=deploy_gate.timestamp(evidence.get('completed_at'))
    except Reject as exc:
        raise Reject(reason+':evidence_unreadable') from exc
    if at-completed>dt.timedelta(seconds=max_age): raise Reject(reason+':stale')
    return task,evidence

def derive_bundle(plan_id,request_sha256,approval_identity,approved_at,expires_at,
                  candidate,expected_current_image_id,test_pr,canary,preflight):
    """The eight-object bundle, assembled from the joined facts. Pure function."""
    plan={'schema_version':'1','plan_id':plan_id,'environment':deploy_gate.ENVIRONMENT,
          'action_id':deploy_gate.ACTION,'candidate':dict(candidate),
          'expected_current_image_id':expected_current_image_id,
          'target_services':list(deploy_gate.SERVICES),
          'protected_non_targets':['redis','caddy'],
          # A candidate that needs a schema migration is not deployable through this
          # contract yet: the controlled forward migration Issue #103 scopes needs
          # executor work this revision does not do, so the derivation refuses it up
          # front rather than deriving a plan the gate would then reject as a
          # forbidden operation.
          'migration':False,'production':False,'automatic_rollback':False,
          'test_pr_task_sha256':deploy_gate.digest(test_pr[0]),
          'test_pr_evidence_sha256':deploy_gate.digest(test_pr[1]),
          'canary_task_sha256':deploy_gate.digest(canary[0]),
          'canary_evidence_sha256':deploy_gate.digest(canary[1]),
          'preflight_task_sha256':deploy_gate.digest(preflight[0]),
          'preflight_evidence_sha256':deploy_gate.digest(preflight[1])}
    approval={'schema_version':'1',
              'approval_id':deploy_gate.approval_id_for(request_sha256),
              'approved_by':approval_identity,'approved_at':iso(approved_at),
              'expires_at':iso(expires_at),'scope':'HK_STAGING_DEPLOY_FIXED_EIGHT',
              'plan_sha256':deploy_gate.digest(plan),'request_sha256':request_sha256}
    return {'plan':plan,'approval':approval,
            'test_pr_task':test_pr[0],'test_pr_evidence':test_pr[1],
            'canary_task':canary[0],'canary_evidence':canary[1],
            'preflight_task':preflight[0],'preflight_evidence':preflight[1]}

def derive(*,at,approval_identity,approved_at,request_sha256,admission,verify_baseline,
           ledger_records,read_evidence,approval_life=deploy_gate.APPROVAL_MAX_LIFE):
    """Derive the plan name and the bundle. Writes nothing."""
    block=admission_block(admission)
    if block.get('migration_required') is True: raise Reject('migration_required_not_supported')
    candidate=candidate_from_admission(block)
    expected=expected_current_from(block,verify_baseline)
    test_pr_task,_record=pair_by_task_id(ledger_records,deploy_gate.TEST_PR_ACTION,
                                         test_pr_task_id(block),'test_pr_task_not_in_ledger')
    test_pr=(test_pr_task,read_evidence(test_pr_task))
    canary=latest_pair(ledger_records,deploy_gate.CANARY_ACTION,read_evidence,at,
                       deploy_gate.CANARY_EVIDENCE_MAX_AGE,
                       {'candidate_image_id':candidate['image_id'],
                        'candidate_package_sha256':candidate['package_sha256'],
                        'expected_current_image_id':expected},'canary_evidence_unusable')
    preflight=latest_pair(ledger_records,deploy_gate.VERIFY_ACTION,read_evidence,at,
                          deploy_gate.VERIFY_EVIDENCE_MAX_AGE,
                          {'candidate_image_id':expected,'expected_current_image_id':expected},
                          'preflight_evidence_unusable')
    plan_id=deploy_gate.plan_id_for(candidate,canary[0])
    # A plan is spent once.  Two DEPLOY Requests against the same candidate and the same
    # canary derive the same name but carry different approvals -- the approval is the
    # Request -- so the second one is refused here, by the thing that names the plan,
    # rather than later by a file that cannot hold both.  A retry therefore needs a fresh
    # canary: that is what gives it a name, and a fresh canary is what a retry should
    # require anyway.
    if any(record.get('plan_id')==plan_id for record in (ledger_records or {}).values() if isinstance(record,dict)):
        raise Reject('deployment_plan_already_consumed')
    expires_at=approved_at+approval_life
    bundle=derive_bundle(plan_id,request_sha256,approval_identity,approved_at,expires_at,
                         candidate,expected,test_pr,canary,preflight)
    return plan_id,bundle

def rollback_source(records,read_evidence):
    """The one deployment a rollback may undo: the newest one this Bridge published.

    Newest, not "the last successful one".  If the most recent deployment's Evidence is
    missing or refused, the derivation stops and the gate refuses -- it never quietly
    falls back to an older deployment, because the older one describes a host state the
    newer deployment has already replaced, and undoing it would not be the act anyone
    asked for.  This is the same discipline the canary and the preflight follow, and the
    same one the Hong Kong executor enforces from the other side, where a newer DEPLOY in
    the task history refuses a rollback outright.
    """
    pairs=published_pairs(records,deploy_gate.ACTION)
    if not pairs: raise Reject('rollback_source_missing')
    task,_record=pairs[0]
    try: evidence=read_evidence(task)
    except Exception as exc: raise Reject('rollback_source_evidence_unreadable') from exc
    if not isinstance(evidence,dict): raise Reject('rollback_source_evidence_unreadable')
    return task,evidence

def derive_rollback_authorization(request_sha256,approval_identity,approved_at,expires_at,
                                  source_task,source_evidence):
    """The rollback's one-time authorisation, bound to the pair it undoes. Pure function."""
    return {'schema_version':'1','approval_id':deploy_gate.rollback_approval_id_for(request_sha256),
            'approved_by':approval_identity,'approved_at':iso(approved_at),
            'expires_at':iso(expires_at),'scope':deploy_gate.ROLLBACK_SCOPE,
            'source_deploy_task_sha256':deploy_gate.digest(source_task),
            'source_deploy_evidence_sha256':deploy_gate.digest(source_evidence),
            'request_sha256':request_sha256}

def derive_rollback(release_id,request_sha256,approval_identity,approved_at,ledger_records,
                    read_evidence,authority_key,hk_key,at,
                    approval_life=deploy_gate.APPROVAL_MAX_LIFE):
    """The rollback context: the newest deployment, and the authorisation that undoes it.

    Nothing is registered on disk.  A deployment writes a plan because the plan is the
    object a human used to have to maintain and the object the executor is handed
    separately; a rollback's whole content is the source pair, which the ledger already
    holds as a signed Task and the evidence repository already holds as a signed Evidence.
    So there is no new file, no new store and no new writable path for the unit to allow
    -- and the publish-time recheck re-derives from the ledger rather than reading back
    bytes this process wrote.
    """
    source_task,source_evidence=rollback_source(ledger_records,read_evidence)
    authorization=derive_rollback_authorization(request_sha256,approval_identity,approved_at,
                                                approved_at+approval_life,source_task,source_evidence)
    return deploy_gate.validate_rollback(release_id,authorization,source_task,source_evidence,
                                         authority_key,hk_key,at,approval_identity,request_sha256)

def store_ready(store):
    """The plan store must be a real, root-owned, unwritable-by-others directory."""
    store=pathlib.Path(store)
    try: info=store.stat()
    except OSError as exc: raise Reject('plan_store_unavailable') from exc
    if not store.is_dir() or os.path.islink(store): raise Reject('plan_store_untrusted')
    if info.st_uid!=deploy_gate.TRUSTED_UID or info.st_mode & 0o022: raise Reject('plan_store_untrusted')
    return store

def register(store,plan_id,bundle):
    """Write the derived bundle, or accept the byte-identical one already registered.

    Refusing to overwrite is the point.  A registered plan is the immutable record a
    deployment cites, so a different bundle under the same name means either that the
    derivation changed underneath a live plan or that something which is not this code
    wrote the file; neither may be replaced silently.  The name already carries the
    canary run, so a retry -- which needs a fresh canary anyway -- gets a fresh name and
    cannot deadlock here.
    """
    store=store_ready(store)
    deploy_gate.match(plan_id,deploy_gate.IDENT,'plan_id')
    target=store/(plan_id+'.json')
    if os.path.lexists(target):
        if os.path.islink(target): raise Reject('plan_path_is_a_symlink')
        if deploy_gate.parse_json(deploy_gate.read_secure(target))!=bundle:
            raise Reject('registered_plan_differs_from_derivation')
        return 'unchanged'
    temp=store/('.'+plan_id+'.tmp')
    # The Command Center's own unit has to allow writing this directory. When it does
    # not, the Request is refused instead of the error escaping: an uncaught OSError
    # here would end the whole poll tick, and one unprocessable DEPLOY Request must
    # never stop VERIFY, TEST_PR, CANARY or HEALTH from being served. Found by reading
    # the live unit (`ProtectSystem=strict` with a `ReadWritePaths` list that did not
    # name the plan store) rather than by hitting it in production.
    try:
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(canonical(bundle)+b'\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp,target)
        directory=os.open(store,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    except OSError as exc:
        try: os.unlink(temp)
        except OSError: pass
        raise Reject('plan_store_unwritable') from exc
    return 'written'
