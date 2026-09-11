from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

REQUIRED = {
    'candidate_sha', 'xcode_version', 'device_model', 'ios_version', 'device_udid_sha256',
    'destination', 'build_exit_code', 'app_intents_smoke', 'transaction_lifecycle_smoke',
    'evidence_sha256'
}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--evidence',type=Path,required=True); p.add_argument('--candidate-sha',required=True); a=p.parse_args()
    if not a.evidence.is_file(): raise SystemExit('APPLE_PHYSICAL_DEVICE_EVIDENCE_REQUIRED')
    raw=a.evidence.read_bytes(); data=json.loads(raw)
    missing=sorted(REQUIRED-set(data))
    if missing: raise SystemExit('APPLE_DEVICE_EVIDENCE_FIELDS_MISSING:'+','.join(missing))
    if data['candidate_sha'] != a.candidate_sha: raise SystemExit('APPLE_DEVICE_CANDIDATE_SHA_MISMATCH')
    if 'Simulator' in str(data['destination']) or 'platform=iOS' not in str(data['destination']): raise SystemExit('APPLE_PHYSICAL_IOS_DESTINATION_REQUIRED')
    if int(data['build_exit_code']) != 0: raise SystemExit('APPLE_DEVICE_BUILD_FAILED')
    if data['app_intents_smoke'] != 'PASS' or data['transaction_lifecycle_smoke'] != 'PASS': raise SystemExit('APPLE_DEVICE_SMOKE_FAILED')
    udid_hash=str(data['device_udid_sha256'])
    if len(udid_hash)!=64 or any(c not in '0123456789abcdef' for c in udid_hash.lower()): raise SystemExit('APPLE_DEVICE_UDID_HASH_INVALID')
    declared=str(data['evidence_sha256'])
    canonical=dict(data); canonical['evidence_sha256']=''
    computed=hashlib.sha256((json.dumps(canonical,sort_keys=True,separators=(',',':'))+'\n').encode()).hexdigest()
    if declared != computed: raise SystemExit('APPLE_DEVICE_EVIDENCE_DIGEST_MISMATCH')
    print('APPLE_PHYSICAL_DEVICE_GATE=PASS')

if __name__=='__main__': main()
