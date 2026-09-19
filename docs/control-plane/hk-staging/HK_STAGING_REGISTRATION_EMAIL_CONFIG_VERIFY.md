# HK_STAGING_REGISTRATION_EMAIL_CONFIG_VERIFY

Status: **candidate only — not installed, not requestable, not deployed.**

This action is a signed, replay-protected HK-STAGING verification task. Its Request has exactly the five common fields; the signed Task has an empty parameter object. It cannot accept a sender, recipient, provider, command, path, URL, test code, credential, or secret reference from the caller.

The fixed local probe succeeds only when all gates are PASS:

- configured sender is exactly `postmaster@goaidirect.com`;
- the application confirms the preconfigured credential reference is usable;
- a dedicated internally configured test challenge is sent;
- delivery is confirmed, the challenge is redeemed, and audit is recorded;
- no secret, code, recipient, provider response, or message content appears in Task/Evidence/stdout.

The secret remains Hong Kong's one-time responsibility in its controlled key store. The committed code references only the fixed identifier `hk-staging-registration-email`; it contains no credential material.

Installation requires the HK root-owned config file and the application-owned Unix-socket probe. Until both are installed and a successful signed Evidence record exists, Command Center must treat this action as unavailable and fail closed.
