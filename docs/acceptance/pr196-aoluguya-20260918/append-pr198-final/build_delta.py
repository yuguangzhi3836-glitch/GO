"""Explicit local PR200 evidence increment. Does not publish or operate HK."""
import datetime as dt
import hashlib
import json
from pathlib import Path
from build_archive import ROOT, reject_sensitive

OUT=Path(__file__).resolve().parent/'append-pr198-final'
PREFIX='docs/acceptance/pr196-aoluguya-20260918/append-pr198-final/'
GROUPS={
 'hk-memory-probe':('catalog_review/hk_media_preflight',[
  'HK_PUBLIC_MEMORY_PREFLIGHT.json','HK_MEASURED_PLAN_BINDING.json',
  'C13_RESULT_REVIEW.json','C13_REVIEW.json','operator_hk_public_media_probe.py',
  'host_readonly_wrapper.py','probe_inside_container.py']),
 'plans':('catalog_review/operator_inputs',[
  'aoluguya_hyatt_gallery_harvest_hk_measured_plan.json','aoluguya_hyatt_gallery_harvest_plan.json']),
 'final-pr198':('catalog-gallery-format-ui',[
  'C13_REVIEW.json','C13_PREVIOUS_HOLD_REVIEW.json','C13_TEST.log','tests.log',
  'SUBMITTED.json','SOURCE_BINDING.json','REVIEW.md',
  'C13_FINAL198_CI_REVIEW.json','C13_FINAL198_TREE_BINDING.json',
  'C13_FINAL198_CHECKS_SNAPSHOT.json','C13_CI_JOB_105466300759.log']),
 'admission-final198':('integration-gate/contacts-next',[
  'CANDIDATE_SOURCE.json','SOURCE_PROOF_RAW.json','CANDIDATE_PROOF.json',
  'C13_SOURCE_PROBE_REVIEW.json','C13_FINAL_FACTS_REVIEW.json','C13_FINAL_TEST.log',
  'C13_HASHONLY_REVIEW.json','C13_HASHONLY_TEST.log','FACTS_PACKAGE.json','FACTS_MANIFEST.json',
  'FROZEN_HASHES.json','ACTIVE_CANDIDATE.json','CANDIDATE_CONTRACT.json','CURRENT_BASELINE_PROOF.json',
  'HK_FACTS_RECEIPT.json','CC_FACTS_RECEIPT.json','CC_FACTS_RECEIPT_RAW_ENVELOPE.json',
  'ADMISSION_RECEIPT_VERIFICATION.json','PREFLIGHT_AND_TASK_VERIFICATION.json']),
 'test-final198':('integration-gate/contacts-next/formal',[
  'TASK.json','EVIDENCE.json','REFERENCES.json','REFERENCES_ORIGINAL.json',
  'CANARY_SUBMITTED.json','VERIFY_SUBMITTED.json','DEPLOY_PREPARED.json']),
 'canary-final198':('integration-gate/pr198-formal',[
  'CANARY_TASK.json','CANARY_EVIDENCE.json','CHAIN_VERIFICATION.json','REFERENCES.json',
  'C13_PREPARATION_REVIEW.json','ARCHIVE_FILES.json',
  'VERIFY_TASK.json','VERIFY_EVIDENCE.json','DEPLOY_TASK.json','DEPLOY_EVIDENCE.json','DEPLOY_REFERENCES.json',
  'POST_VERIFY_TASK.json','POST_VERIFY_EVIDENCE.json','POST_VERIFY_REFERENCES.json',
  'HK_HOST_READBACK.json','VERIFICATION.json','C13_BOUND_READONLY_REVIEW.json',
  'host_readback.py','verify_chain.py','verify_host_closeout.py']),
 'ci-failures-final198':('catalog-gallery-format-ui',[
  'C13_FAILED_CHECK_CLASSIFICATION.json',
  'C13_FAILED_JOB_105466312398.log','C13_FAILED_JOB_105466312578.log',
  'C13_FAILED_JOB_105466312806.log','C13_FAILED_JOB_105466312857.log',
  'C13_FAILED_JOB_105466313061.log','C13_FAILED_JOB_105466313165.log',
  'C13_FAILED_JOB_105466313214.log','C13_FAILED_JOB_105466313233.log',
  'C13_FAILED_JOB_105466313259.log','C13_FAILED_JOB_105466313284.log',
  'C13_FAILED_JOB_105466313303.log','C13_FAILED_JOB_105466313322.log',
  'C13_FAILED_JOB_105466313378.log','C13_FAILED_JOB_105466313389.log']),
 'post-deploy-ui':('catalog_review',['CONTACTS_WRITTEN_PR198_20260918.json','CONTACTS_AFTER_PR198_20260918.txt','CONTACTS_NORMALIZED_PR198_20260918.txt','CONTACTS_NORMALIZED_PR198_20260918.json']),
 'media-persistence':('catalog_review/media_persistence_diagnosis',['OBSERVATION.json']),
 'public-area-capture':('catalog_review',['aoluguya_hyatt_public_area_candidates.json','EASON_PUBLIC_AREA_FETCH.json','HYATT_PUBLIC_AREA_CAPTURE_SUMMARY.json','HYATT_HOME_LIVE_DOM_20260918.json','HYATT_PUBLIC_GALLERY_LIVE_DOM_20260918.json']),
 'contact-provenance':('catalog_review',['CONTACTS_PUBLIC_SOURCES_20260918.json']),
}
def sha(b): return hashlib.sha256(b).hexdigest()
def build():
 OUT.mkdir(parents=True,exist_ok=True)
 elements=[]; files=[]
 for group,(base,names) in GROUPS.items():
  for name in names:
   src=ROOT/base/name; data=src.read_bytes(); text=data.decode('utf-8'); reject_sensitive(text,str(src))
   target=OUT/'files'/group/name; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(data)
   rel=group+'/'+name
   files.append({'archive_path':rel,'source_path':base+'/'+name,'bytes':len(data),'sha256':sha(data)})
   elements.append({'path':PREFIX+rel,'mode':'100644','type':'blob','content':text})
 ci=json.loads((ROOT/'catalog-gallery-format-ui/C13_FINAL198_CI_REVIEW.json').read_text())
 assert ci['source_commit']=='f827a3aefd95fd95dedb2bd2ecc93ae01111ea90'
 for name,h in ci['evidence_sha256'].items():
  assert sha((ROOT/'catalog-gallery-format-ui'/name).read_bytes())==h
 probe=json.loads((ROOT/'catalog_review/hk_media_preflight/HK_MEASURED_PLAN_BINDING.json').read_text())
 assert sha((ROOT/probe['plan_path']).read_bytes())==probe['raw_sha256']
 assert sha((ROOT/'catalog_review/hk_media_preflight/HK_PUBLIC_MEMORY_PREFLIGHT.json').read_bytes())==probe['evidence_lf_sha256']
 failures=json.loads((ROOT/'catalog-gallery-format-ui/C13_FAILED_CHECK_CLASSIFICATION.json').read_text())
 assert len(failures['jobs'])==14
 for job in failures['jobs']:
  assert sha((ROOT/'catalog-gallery-format-ui'/job['log']).read_bytes())==job['sha256']
 receipts=json.loads((ROOT/'integration-gate/contacts-next/ADMISSION_RECEIPT_VERIFICATION.json').read_text())
 for label in ['HK','CC']:
  assert sha((ROOT/('integration-gate/contacts-next/'+label+'_FACTS_RECEIPT.json')).read_bytes())==receipts[label.lower()+'_original_receipt_sha256']
 closeout=json.loads((ROOT/'integration-gate/pr198-formal/ARCHIVE_FILES.json').read_text())
 for name,h in closeout['files'].items():
  assert sha((ROOT/'integration-gate/pr198-formal'/name).read_bytes())==h
 capture=json.loads((ROOT/'catalog_review/HYATT_PUBLIC_AREA_CAPTURE_SUMMARY.json').read_text())
 assert sha((ROOT/'catalog_review/EASON_PUBLIC_AREA_FETCH.json').read_bytes())==capture['local_reserialized_report_sha256']
 state={'schema':'go.catalog-acceptance.append.v1','assembled_at':dt.datetime.now(dt.timezone.utc).isoformat(),
  'source_commit':ci['source_commit'],'ci_required_catalog_gate':ci['verdict'],
  'tests':ci['tests'],'all_ci_pass':ci['all_ci_pass'],'other_checks':ci['other_checks']['summary'],
  'other_failure_causes':'C13_13_FIXED_SOURCE_PATHSET_1_FIXED_APPLICATION_TREE_PRECONDITIONS_FUNCTIONAL_SUITES_NOT_CERTIFIED',
  'memory_probe':'21_WEBP_METADATA_DECODED_IN_MEMORY_NOT_21_PERSISTED_ASSETS',
  'last_catalog_write_state':'POST_PR198_3_CONTACTS_17_ROOM_FACTS_DRAFT69_CURRENT_MEDIA0',
  'new_public_area_assets':'19_DOWNLOADED_EASON_ONLY_PLUS_PRIOR21_DISTINCT_DAM40_NOT_HK_INGESTED_RIGHTS_UNKNOWN',
  'overall_catalog_acceptance':'PARTIAL',
  'address_normalization':json.loads((ROOT/'catalog_review/CONTACTS_NORMALIZED_PR198_20260918.json').read_text()),
  'final_head_test_pr':'ORIGINAL_SIGNED_TASK_EVIDENCE_INCLUDED',
  'final_head_admission':'PASS_OFFLINE_RECEIPT_BINDING_NOT_DEPLOYMENT',
  'final_head_canary':'ORIGINAL_SIGNED_PAIR_PASS',
  'final_head_verify':'ORIGINAL_SIGNED_PAIR_PASS',
  'final_head_deploy':'DEPLOY_POST_VERIFY_AND_HOST_BINDING_PASS','contact_email_database_write':'UI_NOTICE_AND_READBACK_3_CONTACTS_PROVENANCE_PRESERVED',
  'gallery_21_persisted_readback':'CURRENT0_NO_PERSISTENT_MOUNT_FORMER1_NOT_CURRENT',
  'publication_performed':False,'performance_evidence':'PR197_NOT_DUPLICATED','files':files}
 state_text=json.dumps(state,ensure_ascii=False,indent=2)+'\n'
 (OUT/'MANIFEST.json').write_text(state_text)
 for name,content in [('MANIFEST.json',state_text),('README.md',(OUT/'README.md').read_text()),('build_delta.py',Path(__file__).read_text())]:
  elements.append({'path':PREFIX+name,'mode':'100644','type':'blob','content':content})
 (OUT/'TREE_ELEMENTS.json').write_text(json.dumps(elements,ensure_ascii=False))
 print(json.dumps({'files':len(elements),'bytes':(OUT/'TREE_ELEMENTS.json').stat().st_size,'sha256':sha((OUT/'TREE_ELEMENTS.json').read_bytes()),'published':False}))
if __name__=='__main__': build()
