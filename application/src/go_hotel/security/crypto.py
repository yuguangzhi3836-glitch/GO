from __future__ import annotations
import base64, hashlib, hmac, json, os, secrets, time
from go_hotel.core.config import settings

def _b64e(b:bytes)->str: return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def _b64d(s:str)->bytes: return base64.urlsafe_b64decode(s + "="*((4-len(s)%4)%4))

def hash_password(password:str)->str:
    salt=os.urandom(16); iterations=260_000
    dk=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,iterations)
    return f"pbkdf2_sha256${iterations}${_b64e(salt)}${_b64e(dk)}"

def verify_password(password:str, encoded:str)->bool:
    try:
        algo,it,salt,digest=encoded.split("$",3)
        if algo!="pbkdf2_sha256": return False
        calc=hashlib.pbkdf2_hmac("sha256",password.encode(),_b64d(salt),int(it))
        return hmac.compare_digest(calc,_b64d(digest))
    except Exception: return False

def encode_jwt(claims:dict)->str:
    header={"alg":"HS256","typ":"JWT"}
    h=_b64e(json.dumps(header,separators=(",",":"),sort_keys=True).encode())
    p=_b64e(json.dumps(claims,separators=(",",":"),sort_keys=True).encode())
    sig=hmac.new(settings.jwt_signing_key.encode(),f"{h}.{p}".encode(),hashlib.sha256).digest()
    return f"{h}.{p}.{_b64e(sig)}"

def decode_jwt(token:str)->dict:
    parts=token.split(".")
    if len(parts)!=3: raise ValueError("INVALID_TOKEN")
    expected=hmac.new(settings.jwt_signing_key.encode(),f"{parts[0]}.{parts[1]}".encode(),hashlib.sha256).digest()
    if not hmac.compare_digest(expected,_b64d(parts[2])): raise ValueError("INVALID_SIGNATURE")
    claims=json.loads(_b64d(parts[1]))
    if int(claims.get("exp",0)) < int(time.time()): raise ValueError("TOKEN_EXPIRED")
    return claims

def random_token()->str: return secrets.token_urlsafe(48)
def token_hash(token:str)->str: return hashlib.sha256(token.encode()).hexdigest()

def encrypt_secret(value:str)->str:
    from cryptography.fernet import Fernet
    key=base64.urlsafe_b64encode(hashlib.sha256(settings.connector_vault_master_key.encode()).digest())
    return Fernet(key).encrypt(value.encode()).decode()

def decrypt_secret(value:str)->str:
    from cryptography.fernet import Fernet
    key=base64.urlsafe_b64encode(hashlib.sha256(settings.connector_vault_master_key.encode()).digest())
    return Fernet(key).decrypt(value.encode()).decode()
