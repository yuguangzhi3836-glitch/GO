import base64
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from receipt_verifier import Refusal, canonical_payload, public_key_fingerprint, verify_c14_receipt

BINDING={"candidate_sha":"0c3da07bc32009dee16c69125111f8e4ea9d546b","application_tree":"f6d329352dd8484010036448810a927d5eec4be7"}

class ReceiptVerifierTests(unittest.TestCase):
 def setUp(self):
  self.private=Ed25519PrivateKey.generate()
  self.public=self.private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
  self.fp=public_key_fingerprint(self.public)
 def receipt(self,**change):
  r={"schema_version":"c14-receipt-v1","algorithm":"Ed25519","key_fingerprint":self.fp,"issuer":"hk-independent-c14","verdict":"PASS","timestamp":"2026-09-19T00:00:00Z",**BINDING,"digest":"a"*64}
  r.update(change);r["signature"]=base64.b64encode(self.private.sign(canonical_payload(r))).decode();return r
 def refused(self,reason,*args):
  with self.assertRaises(Refusal) as cm: verify_c14_receipt(*args)
  self.assertEqual(cm.exception.args[0],reason)
 def test_valid_signed_receipt(self): self.assertTrue(verify_c14_receipt(self.receipt(),self.public,self.fp,BINDING)["signature_verified"])
 def test_tampered_binding_refuses(self): self.refused("receipt_binding",self.receipt(candidate_sha="0"*40),self.public,self.fp,BINDING)
 def test_untrusted_key_refuses(self): self.refused("untrusted_key",self.receipt(),self.public,"0"*64,BINDING)
 def test_bad_signature_refuses(self):
  r=self.receipt();r["signature"]=base64.b64encode(b"x"*64).decode();self.refused("receipt_signature",r,self.public,self.fp,BINDING)
 def test_extra_field_refuses(self): self.refused("receipt_schema",{**self.receipt(),"network":"enabled"},self.public,self.fp,BINDING)
