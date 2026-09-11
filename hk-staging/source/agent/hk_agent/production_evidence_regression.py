import base64, copy
from hk_agent import transport

def run(private_path, public_path):
    evidence={"schema_version":"1","task_id":"production-evidence-test","nonce":"production-evidence-nonce","action_id":"CONTROL_PLANE_HEALTH","environment":"HK-STAGING-01","status":"SUCCESS","started_at":"2026-09-06T00:00:00.000000+00:00","finished_at":"2026-09-06T00:00:01.000000+00:00","result":{"test":True},"agent_version":"0.4.5-rebuilt"}
    signed=transport.sign(copy.deepcopy(evidence), private_path)
    public=transport.public_key(public_path)
    def verified(value):
        try:
            public.verify(base64.b64decode(value["signature"],validate=True),transport.canonical(value))
            return True
        except Exception:
            return False
    tampered=copy.deepcopy(signed); tampered["status"]="FAIL"
    return {"PRODUCTION_EVIDENCE_PEM_LOADING":True,"PRODUCTION_EVIDENCE_SIGN":isinstance(signed.get("signature"),str),"PRODUCTION_EVIDENCE_VERIFY":verified(signed),"TAMPERED_EVIDENCE_VERIFY":not verified(tampered)}
