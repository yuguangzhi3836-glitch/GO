import base64, hashlib, importlib.util
from pathlib import Path
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
P=Path(__file__).parents[1]/"verify_c14_registration.py"; S=importlib.util.spec_from_file_location("r",P); V=importlib.util.module_from_spec(S); S.loader.exec_module(V)
def registration(): return {"schema":V.SCHEMA,"authority_key_version":V.AUTHORITY_VERSION,"authority_spki_sha256":V.AUTHORITY_FP,"signer_key_version":V.SIGNER_VERSION,"signer_spki_sha256":V.SIGNER_FP,"algorithm":"EC_SIGN_P256_SHA256","registered_at":"2026-09-21T10:00:00Z"}
def authority(tmp_path):
 p=ec.generate_private_key(ec.SECP256R1()); f=tmp_path/"authority.pem"; f.write_bytes(p.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)); return p,f
def envelope(private,value): return {"registration":value,"signature":base64.urlsafe_b64encode(private.sign(V.canonical(value),ec.ECDSA(hashes.SHA256()))).decode().rstrip("=")}
def test_valid_registration(tmp_path,monkeypatch):
 p,f=authority(tmp_path); der=p.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo); monkeypatch.setattr(V,"AUTHORITY_FP","sha256:"+hashlib.sha256(der).hexdigest()); v=registration(); v["authority_spki_sha256"]=V.AUTHORITY_FP; assert V.verify(envelope(p,v),V.load_authority(f))["signer_key_version"]==V.SIGNER_VERSION
@pytest.mark.parametrize("field,value",[("authority_key_version",V.SIGNER_VERSION),("authority_spki_sha256",V.SIGNER_FP),("signer_key_version",V.AUTHORITY_VERSION),("signer_spki_sha256",V.AUTHORITY_FP),("algorithm","ED25519"),("registered_at","2026-09-21T10:00:00+00:00")])
def test_same_key_or_wrong_scope_fails(field,value):
 v=registration(); v[field]=value
 with pytest.raises(V.RegistrationError): V.validate_registration(v)
def test_tamper_and_bad_encoding_fail(tmp_path,monkeypatch):
 p,f=authority(tmp_path); der=p.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo); monkeypatch.setattr(V,"AUTHORITY_FP","sha256:"+hashlib.sha256(der).hexdigest()); v=registration(); v["authority_spki_sha256"]=V.AUTHORITY_FP; e=envelope(p,v); e["registration"]["signer_spki_sha256"]="sha256:"+"0"*64
 with pytest.raises(V.RegistrationError): V.verify(e,V.load_authority(f))
 e=envelope(p,v); e["signature"]="!bad!"
 with pytest.raises(V.RegistrationError): V.verify(e,V.load_authority(f))
