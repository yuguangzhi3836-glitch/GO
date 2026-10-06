"""One Owner-authorized PostgreSQL correction, not a general review retry API.

Authorised 2026-10-07: rerun the 15 business cases for the unchanged #531;
retain the nine explicitly SQLite migration cases. Never repeat C14.
"""
PROFILE = "PG533-15-V1"
ISSUE = 533
PR = 531
CANDIDATE = "0b7d0403f9f171844fdcf9bf3330ff9386e82943"
APPLICATION_TREE = "0f002d4253ca71b46de2f12761b99f1e6f1ad48c"
ROUND = "FORMAL-REVIEW-I533-0b7d0403f9f1"
C13_TASK = ROUND + "-C13"
C14_TASK = ROUND + "-C14"
C13_RUNTIME = "rt_3e4039fad8a8428cb5944f190e75bc85"
C14_RUNTIME = "rt_281e86bace1c4124bc788bd71a2f058e"
C13_RUN = 37484199333
C14_RUN = 37482306650
C13_ROOT = "6c0293ec0d3bd2edf93861381df324e7358c427db5581d8c104a6a268141054f"
C14_ROOT = "889c58bcadc6ca8e5f806edfe2375f06dadb9bf1f30c2cc25aa28185fbcdd6a9"
MIGRATION = "application/tests/test_depth25_migration_history.py"
BUSINESS_PATHS = (
    "application/tests/test_v70_r4_c01_unknown_episode.py",
    "application/tests/test_unknown_episode_retention.py",
    "application/tests/test_v70_next_c01_unknown_funding.py",
    "application/tests/test_depth06_direct_checkout.py::test_unknown_funds_keep_inventory_and_block_cancel_and_timeout",
)
INVENTORY = " ".join(BUSINESS_PATHS)
FULL_INVENTORY = MIGRATION + " " + INVENTORY
CASE_COUNTS = {path.removeprefix("application/"): count
               for path, count in zip(BUSINESS_PATHS, (4, 7, 3, 1))}
ENVELOPE = {"profile": PROFILE, "prior_run_id": C13_RUN, "prior_run_attempt": 1,
            "prior_c13_root": C13_ROOT, "prior_c14_root": C14_ROOT}
# Identity is one slot for this original round. Neither comments, inventory edits,
# the newest run, nor a second BLOCKED verdict can open another paid slot.
IDEMPOTENCY_KEY = "c13-pg-correction-v1:" + ROUND
MARKER = "c13 supplement:"


def requested_profile(body):
    values = [line.strip()[len(MARKER):].strip() for line in body.splitlines()
              if line.strip().lower().startswith(MARKER)]
    if not values:
        return None
    if values != [PROFILE]:
        raise ValueError("C13_SUPPLEMENT_PROFILE_NOT_AUTHORIZED")
    return PROFILE


def validate_payload(payload):
    import json
    expected = {"cell_id": "C13", "external_task_id": C13_TASK,
                "candidate_sha": CANDIDATE, "application_tree": APPLICATION_TREE,
                "issue_number": ISSUE, "ledger_round_id": ROUND,
                "c14_task_id": C14_TASK, "c13_task_id": C13_TASK,
                "c14_run_id": C14_RUN, "c14_runtime_task_id": C14_RUNTIME,
                "machine_inventory": INVENTORY, "supplement": ENVELOPE}
    if (any(payload.get(key) != value for key, value in expected.items())
            or json.dumps(payload.get("supplement"), sort_keys=True) != json.dumps(ENVELOPE, sort_keys=True)):
        raise ValueError("C13_SUPPLEMENT_BINDING_NOT_AUTHORIZED")
