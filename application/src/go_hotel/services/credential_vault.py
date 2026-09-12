from __future__ import annotations
import base64, hashlib, json
from dataclasses import dataclass
from cryptography.fernet import Fernet, InvalidToken
from go_hotel.core.config import settings

class CredentialVaultError(RuntimeError):
    pass

class CredentialVault:
    provider_name = "ABSTRACT"
    key_version = "v1"
    def encrypt(self, secret: dict) -> tuple[str, str, list[str]]: raise NotImplementedError
    def decrypt(self, ciphertext: str) -> dict: raise NotImplementedError

class LocalFernetCredentialVault(CredentialVault):
    """Local/dev envelope boundary. Production must replace the master-key source with KMS/HSM."""
    provider_name = "LOCAL_FERNET"
    def __init__(self, master_key: str):
        digest = hashlib.sha256(master_key.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))
    def encrypt(self, secret: dict) -> tuple[str, str, list[str]]:
        raw = json.dumps(secret, sort_keys=True, separators=(",", ":")).encode()
        ciphertext = self._fernet.encrypt(raw).decode()
        fingerprint = hashlib.sha256(raw).hexdigest()
        return ciphertext, fingerprint, sorted(secret.keys())
    def decrypt(self, ciphertext: str) -> dict:
        try: return json.loads(self._fernet.decrypt(ciphertext.encode()).decode())
        except (InvalidToken, ValueError) as exc: raise CredentialVaultError("credential decrypt failed") from exc

vault = LocalFernetCredentialVault(settings.connector_vault_master_key)
