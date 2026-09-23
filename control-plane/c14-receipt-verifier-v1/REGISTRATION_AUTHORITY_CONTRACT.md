# C14 registration authority contract v1

Draft-only, offline trust registration. The registration authority and receipt signer are distinct HSM P-256 key versions.

| Role | Fixed public identity |
| --- | --- |
| Registration authority | `projects/go-c14-trust-prod-509114/locations/global/keyRings/go-c14-receipts/cryptoKeys/go-c14-registration-authority-v1/cryptoKeyVersions/1` / `sha256:87eb0ab66bd2e1f02331b2bb402ee214194b5f186c381222f9b7edd16c29dc7f` |
| Receipt signer | `projects/go-c14-trust-prod-509114/locations/global/keyRings/go-c14-receipts/cryptoKeys/go-c14-receipt-v1/cryptoKeyVersions/1` / `sha256:0ebf81cd906747a30cd0d8d44c4c2cf536c5e1277f7bf468a51b3eb3fc27ce75` |

The authority may sign only the canonical registration object. A verifier rejects any wrong resource, P-256/SPKI fingerprint, algorithm, time format, signature, or attempt to reuse the authority key as the receipt-signing key. This repository stores no private key, credential, task dispatch, Runner, C14/C13 execution or deployment capability.

## Fixed Owner single-person exception (2026-09-23)

The product owner explicitly chose single-person issuance. This exception applies **only** to the registration at PR #238 head `a8a1191e8693581bdaf58557313265be75fbe4fa`, path `control-plane/c14-receipt-verifier-v1/C14_REGISTRATION_TO_SIGN.v2.json`, Git blob `74dc7c9c6cf2da66541876d3de9c9a0549702257`, 621 bytes, SHA-256 `07ba520cfb1d782011f6b21a7582b29fd73af68524db9d4c892370475876b6a3`. The signed envelope is archived in [PR #238 comment 5791654074](https://github.com/yuguangzhi3836-glitch/GO/pull/238#issuecomment-5791654074). The signature was independently verified against the fixed registration bytes and the authority public key. Attribution to the Owner account is based on the Cloud Shell operator report, not on cryptographic proof of the human operator.

Owner has project-level signing permission on both the authority and receipt keys. Distinct key versions and fingerprints remain mandatory, but **operator/IAM separation is not achieved**. Record this as `OWNER_SINGLE_PERSON_EXCEPTION`; never record `INDEPENDENT_AUTHORITY` or `STRICT_IAM_SEPARATION`. The exception does not generalize to another registration, candidate, key version or signer, nor to C14 receipt issuance. A verifier must use independently pinned public key material and check the exact bytes, source binding, fingerprint, and signature; a PR comment or claimed identity alone is insufficient.

Before accepting this exception in an isolated runtime, independently obtain the authority public key, verify the archived signature, check the fixed Git path/blob/byte digest, run rejection cases for altered bytes/signature/key/fingerprint/source and missing exception declaration, and record who independently reviewed the evidence. Record effective IAM and impersonation rights separately; the Owner's shared signing privilege must remain visible. Permission, replay, receipt, and audit acceptance require their own evidence. This registration is not C14 PASS, a receipt, or execution authority. PR remains Draft; C14/C13, merge, installation, HK and Production remain HOLD.
