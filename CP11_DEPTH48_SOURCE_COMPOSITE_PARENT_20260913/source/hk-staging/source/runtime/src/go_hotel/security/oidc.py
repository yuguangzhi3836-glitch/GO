from __future__ import annotations
import base64, hashlib, secrets
from datetime import timedelta
from urllib.parse import urlencode
import httpx, jwt
from sqlalchemy import select
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OIDCLoginStateRow
from go_hotel.security.crypto import encrypt_secret, decrypt_secret
from go_hotel.security.service import now, aware

class OIDCService:
    def _require(self):
        if not settings.oidc_enabled or not settings.oidc_issuer or not settings.oidc_client_id or not settings.oidc_redirect_uri:
            raise ValueError('OIDC_NOT_CONFIGURED')
    def discovery(self):
        self._require()
        url=settings.oidc_issuer.rstrip('/')+'/.well-known/openid-configuration'
        r=httpx.get(url,timeout=5.0); r.raise_for_status(); return r.json()
    def start(self):
        d=self.discovery(); state=secrets.token_urlsafe(32); nonce=secrets.token_urlsafe(32); verifier=secrets.token_urlsafe(64)
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        with SessionLocal() as s:
            s.add(OIDCLoginStateRow(state=state,provider=settings.oidc_provider_name,nonce=nonce,code_verifier_ciphertext=encrypt_secret(verifier),redirect_uri=settings.oidc_redirect_uri,created_at=now(),expires_at=now()+timedelta(minutes=10)))
            s.commit()
        params={'client_id':settings.oidc_client_id,'response_type':'code','scope':'openid profile email','redirect_uri':settings.oidc_redirect_uri,'state':state,'nonce':nonce,'code_challenge':challenge,'code_challenge_method':'S256'}
        return d['authorization_endpoint']+'?'+urlencode(params)
    def callback(self,code:str,state:str):
        d=self.discovery()
        with SessionLocal() as s:
            row=s.get(OIDCLoginStateRow,state)
            if not row or row.consumed_at or aware(row.expires_at) < now(): raise ValueError('INVALID_OIDC_STATE')
            verifier=decrypt_secret(row.code_verifier_ciphertext); nonce=row.nonce; row.consumed_at=now(); s.commit()
        data={'grant_type':'authorization_code','code':code,'redirect_uri':settings.oidc_redirect_uri,'client_id':settings.oidc_client_id,'code_verifier':verifier}
        if settings.oidc_client_secret: data['client_secret']=settings.oidc_client_secret
        tr=httpx.post(d['token_endpoint'],data=data,timeout=5.0); tr.raise_for_status(); tokens=tr.json(); id_token=tokens.get('id_token')
        if not id_token: raise ValueError('OIDC_ID_TOKEN_MISSING')
        jwks=jwt.PyJWKClient(d['jwks_uri']); key=jwks.get_signing_key_from_jwt(id_token).key
        claims=jwt.decode(id_token,key=key,algorithms=['RS256','ES256'],audience=settings.oidc_client_id,issuer=settings.oidc_issuer)
        if claims.get('nonce')!=nonce: raise ValueError('OIDC_NONCE_MISMATCH')
        return claims

oidc_service=OIDCService()
