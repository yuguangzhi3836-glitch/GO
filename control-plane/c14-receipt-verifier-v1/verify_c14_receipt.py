#!/usr/bin/env python3
"""Offline fail-closed verifier for externally signed C14 P-256 receipts."""
from __future__ import annotations
import argparse, base64, hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
SCHEMA="go.c14.receipt.v1"
FIELDS=("schema","receipt_id","gate","candidate_sha","application_tree","verdict","issuer","issued_at","evidence_manifest_sha256")
SHA=re.compile(r"^[0-9a-f]{40,64}$"); FP=re.compile(r"^sha256:[0-9a-f]{64}$")
class VerificationError(ValueError): pass
def canonical_receipt_bytes(receipt:dict[str,Any])->bytes:
 def walk(v):
  if isinstance(v,float): raise VerificationError("FLOATS_NOT_ALLOWED_IN_RECEIPT")
  if isinstance(v,list): return [walk(x) for x in v]
  if isinstance(v,dict): return {k:walk(x) for k,x in v.items()}
  return v
 try: return json.dumps(walk(receipt),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
 except (TypeError,UnicodeError) as e: raise VerificationError("RECEIPT_NOT_CANONICALIZABLE") from e
def parse_time(v:str)->datetime:
 try: t=datetime.fromisoformat(v.replace("Z","+00:00"))
 except (TypeError,ValueError) as e: raise VerificationError("INVALID_ISSUED_AT") from e
 if t.tzinfo is None or t.utcoffset()!=timezone.utc.utcoffset(t): raise VerificationError("ISSUED_AT_MUST_BE_UTC")
 return t.astimezone(timezone.utc)
def validate(r:Any)->dict[str,Any]:
 if not isinstance(r,dict): raise VerificationError("RECEIPT_MUST_BE_OBJECT")
 if set(r)!=set(FIELDS): raise VerificationError("RECEIPT_FIELDS_MISMATCH")
 if any(not isinstance(r[k],str) or not r[k] for k in FIELDS): raise VerificationError("INVALID_RECEIPT_FIELD")
 if r["schema"]!=SCHEMA or r["gate"]!="C14" or r["verdict"] not in {"PASS","FAIL"}: raise VerificationError("UNSUPPORTED_RECEIPT_SCOPE")
 if any(not SHA.fullmatch(r[k]) for k in ("candidate_sha","application_tree","evidence_manifest_sha256")): raise VerificationError("INVALID_DIGEST")
 parse_time(r["issued_at"]); return r
def load_key(path:Path, expected:str)->ec.EllipticCurvePublicKey:
 if not FP.fullmatch(expected): raise VerificationError("INVALID_EXPECTED_FINGERPRINT")
 try: key=serialization.load_pem_public_key(path.read_bytes())
 except Exception as e: raise VerificationError("TRUSTED_PUBLIC_KEY_UNREADABLE") from e
 if not isinstance(key,ec.EllipticCurvePublicKey) or key.curve.name!="secp256r1": raise VerificationError("TRUSTED_KEY_MUST_BE_P256")
 der=key.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
 if "sha256:"+hashlib.sha256(der).hexdigest()!=expected: raise VerificationError("TRUSTED_KEY_FINGERPRINT_MISMATCH")
 return key
def verify(envelope:Any,key:ec.EllipticCurvePublicKey,now:datetime,max_age:int)->dict[str,str]:
 if not isinstance(envelope,dict) or set(envelope)!={"receipt","signature"}: raise VerificationError("ENVELOPE_FIELDS_MISMATCH")
 r=validate(envelope["receipt"]); sig=envelope["signature"]
 if not isinstance(sig,str) or not sig: raise VerificationError("INVALID_SIGNATURE_ENCODING")
 try: raw=base64.urlsafe_b64decode(sig+"="*(-len(sig)%4))
 except Exception as e: raise VerificationError("INVALID_SIGNATURE_ENCODING") from e
 age=(now-parse_time(r["issued_at"])).total_seconds()
 if age < -60 or age > max_age: raise VerificationError("RECEIPT_OUTSIDE_FRESHNESS_WINDOW")
 try: key.verify(raw,canonical_receipt_bytes(r),ec.ECDSA(hashes.SHA256()))
 except InvalidSignature as e: raise VerificationError("SIGNATURE_INVALID") from e
 return {k:r[k] for k in FIELDS if k!="schema" and k!="gate"}
def main()->int:
 p=argparse.ArgumentParser(); p.add_argument("--receipt",required=True,type=Path); p.add_argument("--trusted-public-key",required=True,type=Path); p.add_argument("--expected-fingerprint",required=True); p.add_argument("--expected-issuer",required=True); p.add_argument("--expected-candidate-sha",required=True); p.add_argument("--expected-application-tree",required=True); p.add_argument("--expected-verdict",required=True,choices=("PASS","FAIL")); p.add_argument("--expected-evidence-manifest-sha256",required=True); p.add_argument("--max-age-seconds",type=int,default=900); p.add_argument("--verification-time"); a=p.parse_args()
 try:
  if a.max_age_seconds<=0: raise VerificationError("INVALID_MAX_AGE_SECONDS")
  now=parse_time(a.verification_time) if a.verification_time else datetime.now(timezone.utc)
  summary=verify(json.loads(a.receipt.read_text()),load_key(a.trusted_public_key,a.expected_fingerprint),now,a.max_age_seconds)
  expected={"issuer":a.expected_issuer,"candidate_sha":a.expected_candidate_sha,"application_tree":a.expected_application_tree,"verdict":a.expected_verdict,"evidence_manifest_sha256":a.expected_evidence_manifest_sha256}
  if any(summary[k]!=value for k,value in expected.items()): raise VerificationError("FIXED_BINDING_MISMATCH")
 except (OSError,json.JSONDecodeError,VerificationError) as e: print(f"VERIFY_FAIL: {e}",file=sys.stderr); return 2
 print(json.dumps({"verified":True,"receipt":summary},sort_keys=True,separators=(",",":"))); return 0
if __name__=="__main__": raise SystemExit(main())
