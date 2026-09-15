import hashlib,json
from pathlib import Path
from datetime import datetime,timezone
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[3]
EVIDENCE=ROOT/'evidence/v70-round2-20260914'
OUT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
now=lambda:datetime.now(timezone.utc).isoformat()
checks=[]
for cell in ('c03','c06','c09'):
    m=EVIDENCE/cell/'SHA256SUMS.json'
    for rel,digest in json.loads(m.read_text()).items():
        p=ROOT/rel;ok=p.is_file() and sha(p)==digest
        assert ok,rel
        checks.append({'path':rel,'sha256':digest,'verified':True})
for line in (EVIDENCE/'c07/SHA256SUMS').read_text().splitlines():
    digest,rel=line.split(maxsplit=1);p=EVIDENCE/'c07'/rel
    assert sha(p)==digest,rel
    checks.append({'path':str(p.relative_to(ROOT)),'sha256':digest,'verified':True})
originals=[]
for n in range(1,13):
    for p in sorted((EVIDENCE/f'c{n:02d}').glob('*')):
        if p.is_file() and p.suffix in {'.log','.xml','.json','.md','.py','.patch'}:
            row={'path':str(p.relative_to(ROOT)),'sha256':sha(p),'size':p.stat().st_size}
            if p.suffix=='.xml':
                root=ET.parse(p).getroot(); suites=[root] if root.tag=='testsuite' else root.findall('testsuite')
                row['junit_counts']={k:sum(int(s.get(k,'0')) for s in suites) for k in ('tests','failures','errors','skipped')}
            originals.append(row)
audit={'reviewer':'/root/c13_independent','completed_at_utc':now(),
    'meaning':'Original evidence bytes inspected and retained. Index does not transfer builder results into independent acceptance.',
    'declared_checksum_entries_verified':len(checks),'checksum_checks':checks,'original_evidence_files':originals,
    'red_originals':{
      'C04':'Initial receipt checks 4 failures / 5 collected; additional C14 same-order equal-amount historical receipt 1 failure / 1 collected; final 33 builder passes.',
      'C07':'19 original failures from missing preference service/API, with separate interpreter exit127 preserved. Expanded final suite has 51 builder passes; expanded cases are not represented as original red cases. Original per-process start times absent and not inferred.',
      'C08':'1 failure / 2 collected before fix, 14 final builder passes. Final third ACK-loss test added subsequently.',
      'C09':'6 failures / 16 collected before fix, 25 final builder passes.',
      'C10':'12 failures / 12 collected before fix, 27 final builder passes.',
      'C11':'2 failures remain unmodified; independent current-candidate reproduction also fails 2/2.'},
    'no_false_red_for_evidence_only_cells':['C01','C02','C03','C05','C06']}
(OUT/'ORIGINAL_EVIDENCE_AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n')
manifest=json.loads((EVIDENCE/'CANDIDATE_SOURCE.json').read_text())
c14path=EVIDENCE/'c14/FINAL_C14_REVIEW.json';c14=json.loads(c14path.read_text())
runs=[json.loads((OUT/(name+'.result.json')).read_text()) for name in ('independent-scopes','c11-known-open-gap')]
assert c14['completed_at_utc']<runs[0]['started_at']<runs[0]['finished_at']<runs[1]['started_at']<runs[1]['finished_at']
assert runs[0]['exit_code']==0 and runs[1]['exit_code']==1
assert all(r['source_unchanged'] for r in runs)
for rel,digest in c14['integration_files_sha256'].items():assert sha(ROOT/rel)==digest,rel
cells=[
('C01','PASS_SCOPED','Mixed hotel credit/cash changes and cancellation retain forfeiture and original expiry; isolated rollback cases.', 'Unknown money outcomes during mixed credit/cash checkout.'),
('C02','PASS_SCOPED','Partial-passenger body/leg requests rejected with no quote/money/ticket side effects; unsupported feature remains explicit.', 'Passenger-coupon selection and allocation design/implementation; no claim of partial-party change completion.'),
('C03','PASS_SCOPED','Local rail API/change recovery, dual inventory holds, confirmed/failed resolution and final refund pool release.', 'Unpaid-expiry versus payment/cancellation race and full target-inventory rejection; PostgreSQL remains unproved.'),
('C04','PASS_SCOPED','Refund completion matches exact frozen-plan payment intent, capture, amount and operation key. Historical equal-amount, duplicate, amount/currency/parent/key faults stay pending and safely retry.', 'Read-only reconciliation design for historical refunded-state versus frozen-plan contradictions; no auto-repair or money execution.'),
('C05','PASS_SCOPED','Repeated unknown result episodes restore correct ride phase and preserve fulfillment terminal guards.', 'Evidence-loss/corruption recovery for unknown results and same-phase provider confirmation.'),
('C06','PASS_SCOPED','Attraction consumed quote contract, refund/redemption exclusion and changed-session capacity; SQLite synthetic runtime.', 'Destination timezone and validity-window facts plus local-session redemption boundary implementation.'),
('C07','PASS_SCOPED','P0 explicit SELF owner preference write/read, encrypted persistence, exact consent/purpose/key, revision, revocation and expiry; no admin impersonation or session auto-promotion.', 'PostgreSQL concurrent consent withdrawal and actual process-restart durability; companion preference graph remains outside this SELF-only scope.'),
('C08','PASS_SCOPED','Transient success-audit commit failure is bounded and fail closed; already-committed completion survives lost acknowledgement without repeating compute.', 'Durable restart recovery for persistent audit outage / process termination; ROUTING rows under permanent outage remain unclosed.'),
('C09','PASS_SCOPED','Persisted risk/review/remediation fields reject overrides; existing ACTIVE decision and sealed evidence remain unchanged on rejected input; serious risk veto retained.', 'Concurrent same-hotel reevaluation and durable hook replay preserve a single current judgment/evidence snapshot.'),
('C10','PASS_SCOPED','Six vertical create/attach preserve canonical order facts over caller amounts/currency while retaining notes and ownership behavior.', 'Batch N+1 current-state reads; historical attachment monetary snapshots not rewritten in this scope.'),
('C11','HOLD','16 inherited completion-guard cases pass, but sync/async post-commit callback probes independently fail 2/2 on this candidate.', 'Explicit proven-no-side-effect versus uncertain outcome contract, then reconcile/replay implementation for flight checkout/change and reviewed call sites.'),
('C12','PASS_SCOPED','Local validator requires gate sequence and distinct reviewers; all 14 idle cells trigger SCHEDULER_FAIL and history-preserving ASSIGNED followups with no invented ACK/RUNNING.', 'Apply validator to actual central ledger; actual ongoing worker liveness and remote scheduler automation are unproved.'),
('C13','PASS_SCOPED','Independent exact-candidate source verification, 210 scoped passes, 11 new reviewer-authored boundaries, plus separate two-case known-failure hold.', 'Verify immutable archive/CI candidate binding and final central ledger references without manufacturing remote execution.'),
('C14','PASS_SCOPED','Independent C14 record, source manifest, timestamps and integration hashes verified; C04 change request is closed for this candidate.', 'Review subsequent depth changes as new exact candidates; this acceptance cannot transfer to changed source.'),
]
result={'schema':'go.v70.round2.c13.review.v1','reviewer':'/root/c13_independent','reviewer_cell':'C13',
    'status':'PASS_SCOPED','candidate_overall_result':'HOLD_C11_KNOWN_FAILURE_AND_UNPROVEN_RELEASE_SCOPES',
    'completed_at_utc':now(),'source_anchor':manifest['source_anchor'],'application_git_tree':manifest['application_git_tree'],
    'source_tree_sha256':manifest['source_tree_sha256'],'source_files':manifest['source_files'],
    'candidate_manifest_path':str((EVIDENCE/'CANDIDATE_SOURCE.json').relative_to(ROOT)),
    'candidate_manifest_sha256':sha(EVIDENCE/'CANDIDATE_SOURCE.json'),
    'c14_record':{'path':str(c14path.relative_to(ROOT)),'sha256':sha(c14path),'completed_at_utc':c14['completed_at_utc'],'status':c14['status'],'reviewer':c14['reviewer']},
    'independent_scoped_tests':{'tests':210,'passed':210,'failed':0,'errors':0,'skipped':0,'reviewer_authored_new_boundaries':11,'pytest_duration_seconds':25.30,'result':runs[0]},
    'known_open_gap_tests':{'cell':'C11','tests':2,'passed':0,'failed':2,'errors':0,'skipped':0,'pytest_exit_code':1,'result':runs[1],'meaning':'Known real failing tests; not skipped, xfailed, repaired or counted as passing.'},
    'source_identity_checks':{'before_after_1341_files_equal':True,'each_declared_file_git_blob_and_sha256_verified':True,'application_git_tree_independently_reconstructed':True,'source_sha256_independently_recomputed':True,'integration_files_remain_equal_to_c14':True,'local_git_head':'NOT_AVAILABLE_MATERIALIZED_SOURCE_ONLY'},
    'original_evidence_audit':{'path':str((OUT/'ORIGINAL_EVIDENCE_AUDIT.json').relative_to(ROOT)),'sha256':sha(OUT/'ORIGINAL_EVIDENCE_AUDIT.json'),'missing_blocking_red_or_green_originals':[]},
    'cells':[{'cell':cid,'decision':decision,'accepted_or_observed_scope':scope,'allowed_next_task':next_task,'domain_completion_percent':None} for cid,decision,scope,next_task in cells],
    'independence':{'source_or_implementer_tests_modified_by_c13':False,'c14_and_c13_are_distinct_agents':True,'c13_runtime_started_after_c14_final_pass':True,'only_new_c13_diagnostic_tests_and_evidence_written':True},
    'limitations':['SQLite and FastAPI TestClient synthetic data; no PostgreSQL, external provider or real funds acceptance.','No frozen-image, browser/physical-device, HK or Production acceptance.','C07 connection dispose/reopen is not an operating-system process restart.','C02 partial passengers, C06 timezone validity, C08 permanent outage, C10 N+1 and C11 uncertain outcomes remain depth work.','Local scheduler validation proves record consistency, not remote 14-worker liveness.','210 passing scoped tests and 2 failing C11 tests must be reported separately; whole-domain or complete-system 100 percent is not established.'],
    'whole_domain_complete_count':0,'full_release':'HOLD','hong_kong':'NOT_ACCESSED','production':'HOLD','remote_write_merge_deploy':False}
(OUT/'FINAL_C13_REVIEW.json').write_text(json.dumps(result,indent=2)+'\n')
md=['# C13 independent acceptance','',f"Anchor: `{manifest['source_anchor']}`.",f"Candidate application tree: `{manifest['application_git_tree']}`.",f"Source SHA256: `{manifest['source_tree_sha256']}`; 1341 declared files.",'',
'**Scoped acceptance: 210/210 PASS, including 11 independent reviewer-authored boundary cases.**',
'**Separate C11 open-gap reproduction: 2/2 FAIL, pytest exit 1. Overall release remains HOLD.**','',
'C14 finalized at '+c14['completed_at_utc']+'. C13 runtime started at '+runs[0]['started_at']+'. Source bytes and both tree fingerprints match before and after each run; all C14 integration hashes still match. No business source or implementer test was edited.','',
'| Cell | Decision | Scope / next task |','| --- | --- | --- |']
for cid,decision,scope,next_task in cells:md.append(f'| {cid} | {decision} | {scope} Next: {next_task} |')
md+=['','Original red/green logs remain intact. Initial interpreter failures are distinct from product test failures; expanded C07/C08 cases are not claimed as original red cases. C04 same-order equal-amount historical refund receipt bypass was reproduced, fixed, reviewed by C14, and independently exercised with additional receipt faults.','',
'No entire domain is marked 100 percent complete. No PostgreSQL, real supplier/funds, process-restart, frozen-image, complete browser/device or Hong Kong deployment acceptance is inferred. Local scheduler followups do not establish remote worker liveness.','',
'Raw commands, UTC timestamps, logs, JUnit and before/after file fingerprints are in this directory. `FINAL_C13_REVIEW.json` is the machine-readable result.']
(OUT/'README.md').write_text('\n'.join(md)+'\n')
checksums={str(p.relative_to(ROOT)):sha(p) for p in sorted(OUT.glob('*')) if p.is_file() and p.name!='SHA256SUMS.json'}
(OUT/'SHA256SUMS.json').write_text(json.dumps(checksums,indent=2)+'\n')
print(json.dumps({'final_review_sha256':sha(OUT/'FINAL_C13_REVIEW.json'),'completed_at_utc':result['completed_at_utc'],'status':result['status'],'overall':result['candidate_overall_result'],'scoped_passed':210,'known_failed':2,'original_checksum_entries_verified':len(checks)}))
