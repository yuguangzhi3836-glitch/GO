# C14 registration authority contract v1

Draft-only, offline trust registration. The registration authority and receipt signer are distinct HSM P-256 key versions.

| Role | Fixed public identity |
| --- | --- |
| Registration authority | `projects/go-c14-trust-prod-509114/locations/global/keyRings/go-c14-receipts/cryptoKeys/go-c14-registration-authority-v1/cryptoKeyVersions/1` / `sha256:87eb0ab66bd2e1f02331b2bb402ee214194b5f186c381222f9b7edd16c29dc7f` |
| Receipt signer | `projects/go-c14-trust-prod-509114/locations/global/keyRings/go-c14-receipts/cryptoKeys/go-c14-receipt-v1/cryptoKeyVersions/1` / `sha256:0ebf81cd906747a30cd0d8d44c4c2cf536c5e1277f7bf468a51b3eb3fc27ce75` |

The authority may sign only the canonical registration object. A verifier rejects any wrong resource, P-256/SPKI fingerprint, algorithm, time format, signature, or attempt to reuse the authority key as the receipt-signing key. This repository stores no private key, credential, task dispatch, Runner, C14/C13 execution or deployment capability.
