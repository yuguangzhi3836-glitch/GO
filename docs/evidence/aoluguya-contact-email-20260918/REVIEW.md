# Contacts form — reviewed local candidate; not submitted or deployed

Base: exact PR196 source `aad78d00052c243186657072b872637a85ba1a8f`; frontend blob verified. PR196 and earlier candidate directories were not modified. Root is independently completing the fixed PR196 deployment. This work does not start another release or touch runtime data.

Files: application/frontend/admin/hotel-page-factory.js, application/tests_frontend/hotel_catalog_contacts.test.mjs, .github/workflows/catalog-load-repair.yml, and this review note.

Adds a normal form for the fixed primary Aoluguya hotel. Known defaults come from `catalog_review/CONTACTS_PUBLIC_SOURCES_20260918.json`: Ctrip telephone 0451-88800808 (normalized +8645188800808), Ctrip address 黑龙江哈尔滨松北区创新三路800号, and Hyatt anson.liu@hyatt.com with **WEDDINGS_EVENTS_CONTACT** purpose. The latter is not claimed a general reservations mailbox.

User explicitly provided `1720574900@qq.com` and attributed it to Ctrip. Its evidence classification is **USER_PROVIDED_CTRIP_ATTRIBUTION**, not independent page verification. Root did not retrieve this email from the public page; the login redirect was not followed after approval rejection. This default appears with the same plain-language disclosure in the form and preview. It is an independently stored PUBLIC_SOURCE / GENERAL contact snapshot, using a `USER_PROVIDED_CTRIP_ATTRIBUTION:` source-key prefix and the attributed Ctrip URL. Independently observed phone/address stay in their own snapshot; Hyatt remains a separate official wedding/event snapshot. No general reservations mailbox is asserted. Values remain configurable under the same schema and evidence attribution. The two purpose fields cannot contain the same email. Known contact purposes display in Chinese rather than raw enum codes.

Unlike the one-off recovery-file controls, this form does not pin a whole JSON file hash. It accepts updated valid contact values without a new frontend deployment, under a fixed hotel identity, fixed API and restricted typed fields. Phone normalization supports E.164 or the documented Harbin 0451 landline form; email/length/HTML/control-character checks apply. Public source URL must be the hotel's HTTPS Ctrip page, and the official events URL must be the hotel's HTTPS Hyatt weddings/meetings/special-events page. Source type/rights/confidence/purpose are derived by code, never accepted as editable form fields. No credentials, query, fragment or arbitrary endpoint is accepted.

Normal workflow: admin:rules principal → protected active scope/no running jobs → DRAFT profile → reviewed preview → fresh profile/contact fingerprint → existing sources/ingest → immutable snapshot payload/source readback → contact/address/DRAFT readback. Sources remain PUBLIC_SOURCE (5000) for Ctrip and OFFICIAL_WEBSITE (9500) for Hyatt. Payload is only supported address and contacts. URL-derived stable source keys, fixed external hotel identity, and unchanged payload preserve existing ingest idempotence.

The public address is supplementary evidence. If an existing address has higher source rank/confidence, it remains canonical; the preview says so and final readback verifies it is retained while the new snapshot preserves the supplemental address. Existing same-value contacts with stronger rank/confidence and matching purpose are reused, not downgraded. Suppressed/non-public contacts, unknown provenance, duplicate identities and stronger-source incompatible purposes stop before writes. Final readback requires exact phone normalization, source/type when written, and wedding/event classification of the Hyatt email.

No publication, media rights, source rank changes, arbitrary fetch, cookie/token extraction, account escalation or direct DB writes. Root must complete the existing signed deployment/VERIFY/fresh-runtime prerequisites before actual product clicks. UI authorization is not a substitute for deployment acceptance.

Sequential existing API calls are not a cross-request transaction; partial writes are truthfully reported. Archived-source identity conflicts can only be rejected by backend ingestion because normal UI cannot read archived profiles. Concurrent third-party edits after the final preflight are still subject to existing backend semantics; no new global concurrency/transaction guarantee is claimed.

Validation to date: 16 contact behavioral tests PASS, plus all 21 inherited scope/facts/gallery tests PASS against the latest contact UI snapshot. No live browser or visual acceptance is claimed.

## ROOM media status

C01 verified 17 official detail-page stable room codes, but `HYATT_OFFICIAL_CODE_CROSSWALK_REVIEW_20260918.json` still has no proven code-to-Golden room_type_id mapping. No ROOM batch UI/plan is implemented here. Existing 21 GALLERY records and UNKNOWN rights remain the approved media scope; do not infer mapping from names or filenames.

CI adds only branch `fix/aoluguya-contact-email-20260918` and the contact test path to the existing node command. Existing backend/PG/source evidence gates remain unchanged. Exact base PR196 source is `aad78d00052c243186657072b872637a85ba1a8f`, root tree `b120ef433a36b7396557377453ba79b3ec4f1d1c`. Tests are local mocked normal-API behavior tests; real contact ingestion/readback must still be completed by root after deployment.
