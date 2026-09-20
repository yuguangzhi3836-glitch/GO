import base64, hashlib, importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
P=Path(__file__).parents[1]/"verify_c14_receipt.py"; S=importlib.util.spec_from_file_location("v",P); V=importlib.util.module_from_spec(S); S.loader.exec_module(V)
def envelope(private,now):
 r={"schema":"go.c14.receipt.v1","receipt_id":"synthetic-1","gate":"C14","candidate_sha":"a"*40,"application_tree":"b"*40,"verdict":"PASS","issuer":"independent-test-host","issued_at":now.isoformat().replace("+00:00","Z"),"evidence_manifest_sha256":"c"*64}
 return {"receipt":r,"signature":base64.urlsafe_b64encode(private.sign(V.canonical_receipt_bytes(r),ec.ECDSA(hashes.SHA256()))).decode().rstrip("=")}
def keyfile(tmp_path,public):
 path=tmp_path/"pub.pem"; path.write_bytes(public.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)); der=public.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo); return path,"sha256:"+hashlib.sha256(der).hexdigest()
def test_valid_receipt(tmp_path):
 private=ec.generate_private_key(ec.SECP256R1()); path,fp=keyfile(tmp_path,private.public_key()); now=datetime(2026,9,20,12,0,tzinfo=timezone.utc)
 assert V.verify(envelope(private,now),V.load_key(path,fp),now,900)["candidate_sha"]=="a"*40
@pytest.mark.parametrize("field,value",[("candidate_sha","d"*40),("verdict","FAIL"),("issued_at","2026-09-20T11:44:59Z")])
def test_tamper_or_stale_fails(tmp_path,field,value):
 private=ec.generate_private_key(ec.SECP256R1()); path,fp=keyfile(tmp_path,private.public_key()); now=datetime(2026,9,20,12,0,tzinfo=timezone.utc); e=envelope(private,now); e["receipt"][field]=value
 with pytest.raises(V.VerificationError): V.verify(e,V.load_key(path,fp),now,900)
