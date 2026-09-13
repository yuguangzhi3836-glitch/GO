from __future__ import annotations
import base64, hashlib, hmac, secrets, struct, time
from urllib.parse import quote
from .crypto import encrypt_secret, decrypt_secret
from go_hotel.core.config import settings

def new_secret()->str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')

def _decode(secret:str)->bytes:
    return base64.b32decode(secret + '='*((8-len(secret)%8)%8), casefold=True)

def totp(secret:str, at:int|None=None, digits:int=6, period:int=30)->str:
    counter=int((at if at is not None else time.time())//period)
    digest=hmac.new(_decode(secret),struct.pack('>Q',counter),hashlib.sha1).digest()
    off=digest[-1]&0x0f
    code=(struct.unpack('>I',digest[off:off+4])[0]&0x7fffffff)%(10**digits)
    return str(code).zfill(digits)

def verify_totp(secret:str, code:str, window:int=1)->bool:
    now=int(time.time())
    return any(hmac.compare_digest(totp(secret,now+(i*30)),str(code).zfill(6)) for i in range(-window,window+1))

def provisioning_uri(username:str, secret:str)->str:
    label=quote(f'{settings.mfa_issuer}:{username}')
    return f'otpauth://totp/{label}?secret={secret}&issuer={quote(settings.mfa_issuer)}&algorithm=SHA1&digits=6&period=30'

def seal(secret:str)->str: return encrypt_secret(secret)
def unseal(secret_ciphertext:str)->str: return decrypt_secret(secret_ciphertext)
