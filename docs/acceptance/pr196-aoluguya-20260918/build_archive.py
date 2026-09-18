"""Build a local, explicit-allowlist evidence archive; no network or publication."""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
PREFIX = 'docs/acceptance/pr196-aoluguya-20260918/'
GROUPS = {
 'source': ('integration-gate/pr196-source', ['HASHONLY_RESULT.json']),
 'admission': ('integration-gate/pr195-admission', [
  'CANDIDATE_SOURCE.json','ACTIVE_CANDIDATE.json','FACTS_PACKAGE.json',
  'FACTS_MANIFEST.json','FROZEN_HASHES.json','CANDIDATE_CONTRACT.json',
  'CC_FACTS_RECEIPT.json','HK_FACTS_RECEIPT.json','ADMISSION_RECEIPT_VERIFICATION.json',
  'C13_FINAL_FACTS_REVIEW.json','C13_ABSENCE_REVIEW.json',
  'CURRENT_BASELINE_PROOF.json','CONTROL_SOURCE_PROVENANCE_CORRECTION.json']),
 'test-pr': ('integration-gate/pr195-admission/formal', [
  'TASK.json','EVIDENCE.json','TASK_VERIFICATION.json','INDEPENDENT_VERIFICATION.json','REFERENCES.json']),
 'formal': ('integration-gate/pr196-formal', [
  'VERIFY_TASK.json','VERIFY_EVIDENCE.json','CANARY_TASK.json','CANARY_EVIDENCE.json',
  'DEPLOY_TASK.json','DEPLOY_EVIDENCE.json','POST_VERIFY_TASK.json','POST_VERIFY_EVIDENCE.json',
  'CHAIN_VERIFICATION.json','POST_VERIFY_REFERENCES.json','ARCHIVE_FILES.json',
  'HK_HOST_READBACK.json','VERIFICATION.json','host_readback.py','verify_chain.py',
  'test_verify_chain.py','VERIFY_CHAIN_TEST_LOG.txt']),
 'expired-attempt': ('integration-gate/pr196-formal', [
  'ATTEMPT1_VERIFY_TASK.json','ATTEMPT1_VERIFY_EVIDENCE.json',
  'ATTEMPT1_CANARY_TASK.json','ATTEMPT1_CANARY_EVIDENCE.json',
  'ATTEMPT1_DEPLOY_TASK.json','ATTEMPT1_NOT_EXECUTED.json','REQUEST_REFERENCES.json']),
 'rooms': ('catalog_review', [
  'HYATT_ROOM_DETAIL_CODE_CHAIN_20260918.json','HYATT_OFFICIAL_CODE_CROSSWALK_REVIEW_20260918.json',
  'HYATT_ROOMS_LIVE_DOM_20260918.json','HYATT_LIVE_DOM_INDEPENDENT_REVIEW_20260918.json']),
 'build-ui': ('catalog_review', ['BUILD_SCOPE_AFTER_20260918.txt','BUILD_FACTS_AFTER_20260918.txt','BUILD_PROGRESS_20260918.json','HYATT_WEBP_REFRESH_FIRST_ITEM_HOLD.json']),
 'gallery-diagnosis': ('catalog_review/gallery_diagnosis', ['FIRST_ASSET_READBACK.json']),
 'pr198-reviewed-not-deployed': ('catalog-contacts-ui', ['C13_REVIEW.json','C13_PR198_CI_REVIEW.json','C13_PR198_TREE_BINDING.json','SUBMITTED.json','C13_CONTACT_TEST.log','C13_INHERITED_TEST.log','C13_CI_JOB_105461441191.log']),
 'contacts': ('catalog_review', ['CONTACTS_PUBLIC_SOURCES_20260918.json']),
 'contact-independent-review': ('catalog-reset/ctrip-contact', ['FACTS.json','official-source-excerpts.txt']),
}
# Add only explicitly reviewed filenames here after fresh observations arrive.
# An empty list is PENDING, never an implicit successful UI/host readback.
READBACK_FILES = []  # [(archive_relative_path, workspace_relative_path), ...]

def sha(data):
    return hashlib.sha256(data).hexdigest()

def reject_sensitive(value, where):
    if isinstance(value, dict):
        for key, child in value.items():
            if re.fullmatch(r'(password|passwd|access_token|refresh_token|session_token|cookie|cookies|authorization|private_key)', key, re.I) and child:
                raise ValueError('Sensitive field in '+where+': '+key)
            reject_sensitive(child, where)
    elif isinstance(value, list):
        for child in value:
            reject_sensitive(child, where)
    elif isinstance(value, str):
        if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}|[?&](?:token|thirdPartytoken|access_token)=', value):
            raise ValueError('Credential-shaped value in '+where)
        # FACTS_PACKAGE retains signed JSON as strings; inspect without rewriting.
        if value.lstrip().startswith(('{','[')):
            try:
                parsed=json.loads(value)
            except ValueError:
                return
            reject_sensitive(parsed, where)

def build():
    selected=[(group+'/'+name, base+'/'+name) for group,(base,names) in GROUPS.items() for name in names]
    selected += READBACK_FILES
    archive_files=json.loads((ROOT/'integration-gate/pr196-formal/ARCHIVE_FILES.json').read_text())
    for pinned in archive_files['files']:
        assert sha((ROOT/pinned['path']).read_bytes())==pinned['sha256'], pinned['path']
    old_reference=OUT/'files/formal/REQUEST_REFERENCES.json'
    if old_reference.exists():
        old_reference.unlink()
    elements=[]; manifest=[]
    for dest, src in selected:
        data=(ROOT/src).read_bytes(); text=data.decode('utf-8')
        reject_sensitive(text, src)
        target=OUT/'files'/dest; target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(data)
        manifest.append({'archive_path':dest,'original_workspace_path':src,'bytes':len(data),'sha256':sha(data),'bytes_preserved':True})
        elements.append({'path':PREFIX+dest,'mode':'100644','type':'blob','content':text})
    source=json.loads((ROOT/'integration-gate/pr195-admission/CANDIDATE_SOURCE.json').read_text())
    chain=json.loads((ROOT/'integration-gate/pr196-formal/CHAIN_VERIFICATION.json').read_text())
    old=json.loads((ROOT/'integration-gate/pr196-formal/ATTEMPT1_NOT_EXECUTED.json').read_text())
    assert source['pr_number']=='196' and source['source_commit']=='aad78d00052c243186657072b872637a85ba1a8f'
    assert chain['status']=='PASS' and old['deployment_performed'] is False and not old['attempts'] and not old['processed']
    rooms=json.loads((ROOT/'catalog_review/HYATT_OFFICIAL_CODE_CROSSWALK_REVIEW_20260918.json').read_text())
    assert rooms['summary']['golden_room_id_crosswalk']=='HOLD'
    contacts=json.loads((ROOT/'catalog_review/CONTACTS_PUBLIC_SOURCES_20260918.json').read_text())
    user_email=next(x for x in contacts['facts'] if x['value']=='1720574900@qq.com')
    assert user_email['provenance']=='USER_PROVIDED_CTRIP_ATTRIBUTION' and user_email['independently_observed_on_ctrip'] is False
    state={'schema':'go.pr196.catalog-acceptance.local-archive.v1','assembled_at':dt.datetime.now(dt.timezone.utc).isoformat(),
      'publication_performed':False,'source':source,'formal_chain_status':chain['status'],
      'old_deploy_attempt':old,'room_code_chain':rooms['summary'],
      'user_email_provenance':user_email,
      'fresh_host_readback':json.loads((ROOT/'integration-gate/pr196-formal/VERIFICATION.json').read_text()),
      'post_mutation_ui_readback':json.loads((ROOT/'catalog_review/BUILD_PROGRESS_20260918.json').read_text()),
      'overall_catalog_acceptance':'PARTIAL',
      'catalog_archive_112':'ARCHIVED_RETAINED_2_INDIVIDUALLY_READ_BACK_112_NO_PHYSICAL_DELETE',
      'facts_17':'3_SOURCES_17_ROOMS_DRAFT_69_PERCENT_14_ANOMALIES',
      'gallery_21':'1_SAVED_WEBP_0_MATCH_ORIGINAL_JPEG_PLAN_STOPPED_RIGHTS_UNKNOWN_NOT_PUBLISHABLE',
      'pr198_email':{'source_commit':'f80f13acfb6eb5653770bd880bcb92d455292a54','review':'PASS_EXACT_SOURCE_AND_CI_37_FRONTEND_38_BACKEND','deployed':False,'email_database_written':False},
      'performance_evidence':'PR197_NOT_DUPLICATED','files':manifest}
    state_text=json.dumps(state,ensure_ascii=False,indent=2)+'\n'
    (OUT/'MANIFEST.json').write_text(state_text)
    elements.append({'path':PREFIX+'MANIFEST.json','mode':'100644','type':'blob','content':state_text})
    for name in ['README.md','build_archive.py']:
        elements.append({'path':PREFIX+name,'mode':'100644','type':'blob','content':(OUT/name).read_text()})
    (OUT/'TREE_ELEMENTS.json').write_text(json.dumps(elements,ensure_ascii=False))
    print(json.dumps({'files':len(elements),'tree_elements_bytes':(OUT/'TREE_ELEMENTS.json').stat().st_size,'tree_elements_sha256':sha((OUT/'TREE_ELEMENTS.json').read_bytes()),'published':False}))

if __name__=='__main__':
    build()
