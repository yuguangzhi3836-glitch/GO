import copy
import unittest

import c14_trust_manifest as trust


MANIFEST = {
    "schema": trust.SCHEMA,
    "project": trust.PROJECT,
    "kms_key_version": trust.KEY_RESOURCE_PREFIX + "1",
    "algorithm": trust.ALGORITHM,
    "public_key_spki_sha256": "a" * 64,
    "service_account": trust.SERVICE_ACCOUNT,
    "kms_role": trust.ROLE,
    "state": "VERIFIED",
    "registered_at": "2026-09-20T16:00:00Z",
    "verifiers": [
        {"id": "kms-custodian-01", "role": "KMS custodian", "verified_at": "2026-09-20T16:01:00Z", "attestation": "Compared console key version, algorithm and public-key fingerprint."},
        {"id": "security-reviewer-01", "role": "Independent reviewer", "verified_at": "2026-09-20T16:02:00Z", "attestation": "Independently compared key-scoped signer role and all trust fields."},
    ],
}


class TrustRegistrationTests(unittest.TestCase):
    def test_complete_public_registration_is_accepted(self):
        trust.validate(MANIFEST)
        self.assertEqual(len(trust.manifest_sha256(MANIFEST)), 64)

    def test_pending_template_never_becomes_trust_anchor(self):
        value = copy.deepcopy(MANIFEST)
        value["state"] = "PENDING_TWO_PERSON_VERIFICATION"
        with self.assertRaisesRegex(trust.TrustManifestRejected, "NOT_VERIFIED"):
            trust.validate(value)

    def test_version_must_be_exact_key_and_version(self):
        value = copy.deepcopy(MANIFEST)
        value["kms_key_version"] = "projects/x/locations/global/keyRings/y/cryptoKeys/z/cryptoKeyVersions/1"
        with self.assertRaisesRegex(trust.TrustManifestRejected, "KMS_VERSION_MUST_BE_FIXED"):
            trust.validate(value)

    def test_fingerprint_role_and_service_identity_are_pinned(self):
        for field, bad in (("public_key_spki_sha256", "A" * 64), ("kms_role", "roles/owner"), ("service_account", "other@example.com")):
            with self.subTest(field=field):
                value = copy.deepcopy(MANIFEST)
                value[field] = bad
                with self.assertRaises(trust.TrustManifestRejected):
                    trust.validate(value)

    def test_two_different_verifiers_are_required(self):
        value = copy.deepcopy(MANIFEST)
        value["verifiers"][1]["id"] = value["verifiers"][0]["id"]
        with self.assertRaisesRegex(trust.TrustManifestRejected, "DISTINCT"):
            trust.validate(value)

