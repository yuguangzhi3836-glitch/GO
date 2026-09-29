import copy
import unittest

from go_hotel.services.hotel_direct_submission_manifest import validate_direct_submission_manifest


def sample():
    identity = dict(supplier_id="supplier-a", property_id="property-a",
                    registration_id="registration-a", canonical_hotel_id="canonical-a",
                    association_evidence_reference="association-review:123")
    def asset(aid, role, room=None):
        return dict(asset_id=aid, supplier_id="supplier-a", property_id="property-a",
                    canonical_hotel_id="canonical-a", partner_room_id=room,
                    canonical_room_id={"p1": "c1", "p2": "c2"}.get(room), role=role,
                    original_sha256="a" * 64, width=1920, height=1080,
                    byte_size=100000, mime_type="image/jpeg",
                    rights=dict(rights_holder="Hotel A", evidence_reference="signed-grant:123",
                                review_evidence_reference="rights-review:123",
                                usage_scope=["DISTRIBUTE_ON_GO"], expires_at="2027-01-01T00:00:00Z"))
    return dict(schema="HOTEL_DIRECT_SUBMISSION_V1", identity=identity,
                inventory=dict(partner_room_ids=["p1", "p2"], canonical_room_ids=["c1", "c2"],
                               complete_confirmed=True, confirmed_by="hotel-user-a",
                               confirmed_at="2026-09-19T00:00:00Z", evidence_reference="inventory-review:123"),
                room_mappings=[dict(partner_room_id=p, canonical_room_id=c, confirmed=True,
                                    evidence_reference="room-review:" + p)
                               for p, c in (("p1", "c1"), ("p2", "c2"))],
                assets=[asset("hero", "HERO"), asset("room1", "ROOM", "p1"), asset("room2", "ROOM", "p2")])


class DirectSubmissionManifestTest(unittest.TestCase):
    def rejected(self, mutate):
        data = sample()
        mutate(data)
        with self.assertRaises(ValueError):
            validate_direct_submission_manifest(data)

    def test_valid_is_only_unverified_structure(self):
        result = validate_direct_submission_manifest(sample())
        self.assertEqual(result["validation_state"], "STRUCTURE_VALID_EVIDENCE_UNVERIFIED")
        self.assertFalse(result["published"])
        self.assertFalse(result["publishable"])
        self.assertFalse(result["rights_granted"])
        self.assertEqual(len(result["manifest_sha256"]), 64)

    def test_input_untouched_and_output_detached(self):
        data = sample()
        before = copy.deepcopy(data)
        result = validate_direct_submission_manifest(data)
        self.assertEqual(data, before)
        result["manifest"]["identity"]["property_id"] = "changed"
        self.assertEqual(data, before)

    def test_hash_order_invariant_and_expected_hash(self):
        data = sample()
        expected = validate_direct_submission_manifest(data)["manifest_sha256"]
        data["assets"].reverse()
        data["room_mappings"].reverse()
        data["inventory"]["canonical_room_ids"].reverse()
        data["inventory"]["partner_room_ids"].reverse()
        self.assertEqual(validate_direct_submission_manifest(data, expected_sha256=expected)["manifest_sha256"], expected)
        data["assets"][0]["rights"]["evidence_reference"] = "changed-reference"
        with self.assertRaisesRegex(ValueError, "hash_mismatch"):
            validate_direct_submission_manifest(data, expected_sha256=expected)

    def test_version_and_unknown_fields(self):
        for key, value in (("schema", "OFFICIAL_CATALOG_REPLICATION_V1"), ("published", True), ("source_url", "https://invented.invalid")):
            with self.subTest(key=key):
                self.rejected(lambda d: d.update({key: value}))

    def test_identity_association_required(self):
        for key in sample()["identity"]:
            with self.subTest(key=key):
                self.rejected(lambda d: d["identity"].pop(key))

    def test_cross_hotel_and_supplier_rejected(self):
        for key in ("supplier_id", "property_id", "canonical_hotel_id"):
            with self.subTest(key=key):
                self.rejected(lambda d: d["assets"][0].update({key: "other"}))

    def test_room_binding_rejected(self):
        for key, value in (("partner_room_id", "unmapped"), ("canonical_room_id", "c2")):
            with self.subTest(key=key):
                self.rejected(lambda d: d["assets"][1].update({key: value}))
        self.rejected(lambda d: d["assets"][0].update(partner_room_id="p1"))

    def test_inventory_exact_parity(self):
        self.rejected(lambda d: d["room_mappings"].pop())
        self.rejected(lambda d: d["inventory"]["partner_room_ids"].append("p3"))
        self.rejected(lambda d: d["inventory"]["canonical_room_ids"].append("c3"))
        self.rejected(lambda d: d["inventory"].update(complete_confirmed=False))
        self.rejected(lambda d: d["inventory"].update(complete_confirmed=1))
        self.rejected(lambda d: d["room_mappings"][0].update(confirmed=1))

    def test_duplicate_room_identity_or_target(self):
        self.rejected(lambda d: d["inventory"]["partner_room_ids"].append("p1"))
        self.rejected(lambda d: d["room_mappings"].append(copy.deepcopy(d["room_mappings"][0])))
        self.rejected(lambda d: d["room_mappings"][1].update(canonical_room_id="c1"))

    def test_hero_and_each_room_image_required(self):
        for index in range(3):
            with self.subTest(index=index):
                self.rejected(lambda d: d["assets"].pop(index))

    def test_duplicate_asset_or_usage(self):
        self.rejected(lambda d: d["assets"].append(copy.deepcopy(d["assets"][0])))
        self.rejected(lambda d: d["assets"].append(dict(d["assets"][0], asset_id="duplicate-usage")))

    def test_original_hash_and_image_requirements(self):
        for key, value in (("original_sha256", "A" * 64), ("original_sha256", "abcd"),
                           ("width", True), ("height", 719), ("width", 1080),
                           ("byte_size", 0), ("byte_size", 15 * 1024 * 1024 + 1),
                           ("mime_type", "image/svg+xml"), ("role", "UNKNOWN")):
            with self.subTest(key=key, value=value):
                self.rejected(lambda d: d["assets"][0].update({key: value}))
        self.rejected(lambda d: d["assets"][0].update(width=40000, height=40000))

    def test_rights_reference_scope_and_expiry(self):
        for key, value in (("evidence_reference", ""), ("review_evidence_reference", ""),
                           ("usage_scope", ["INTERNAL"]), ("expires_at", "2026-09-19T00:00:00Z"),
                           ("expires_at", "2026-09-18T00:00:00Z"), ("expires_at", "2027-01-01")):
            with self.subTest(key=key):
                self.rejected(lambda d: d["assets"][0]["rights"].update({key: value}))
        data = sample()
        data["assets"][0]["rights"]["expires_at"] = None
        self.assertFalse(validate_direct_submission_manifest(data)["publishable"])

    def test_timestamp_offsets_compare_as_instants(self):
        self.rejected(lambda d: d["assets"][0]["rights"].update(expires_at="2026-09-19T08:00:00+08:00"))
        for value in ("2026-09-19T00:00:00", "2026-09-99T00:00:00Z", "0001-01-01T00:00:00+14:00", True):
            with self.subTest(value=value):
                self.rejected(lambda d: d["inventory"].update(confirmed_at=value))

    def test_credentials_rejected_without_echoing_secret(self):
        for key in ("password", "access_token", "Authorization", "cookies", "验证码", "api-key"):
            data = sample()
            data["assets"][0]["rights"][key] = "do-not-echo-this"
            with self.assertRaises(ValueError) as ctx:
                validate_direct_submission_manifest(data)
            self.assertNotIn("do-not-echo-this", str(ctx.exception))
            self.assertIn("credentials", str(ctx.exception))
        self.rejected(lambda d: d["identity"].update(association_evidence_reference="Bearer abc.secret"))
        self.rejected(lambda d: d["identity"].update(association_evidence_reference="password=hidden"))
        self.rejected(lambda d: d["identity"].update(association_evidence_reference="https://user:hidden@example.invalid/proof"))

    def test_malformed_json_types_rejected(self):
        for data in (None, [], 1, "manifest", {1: "value"}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_direct_submission_manifest(data)
        self.rejected(lambda d: d["assets"][0].update(width=1920.0))
        self.rejected(lambda d: d["identity"].update(property_id=" property-a "))

    def test_current_rights_are_explicitly_not_evaluated(self):
        # No implicit wall-clock dependency or fabricated grant from evidence IDs.
        data = sample()
        data["inventory"]["confirmed_at"] = "2020-01-01T00:00:00Z"
        for asset in data["assets"]:
            asset["rights"]["expires_at"] = "2021-01-01T00:00:00Z"
        result = validate_direct_submission_manifest(data)
        self.assertFalse(result["publishable"])
        self.assertFalse(result["rights_granted"])


if __name__ == "__main__":
    unittest.main()
