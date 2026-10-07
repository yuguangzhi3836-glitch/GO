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
# The first correction slot reached GitHub once and terminated before pytest because the
# execution backend rejected its frozen node id.  These facts are checked from the
# installed read-only outbox before the final slot can be planned; they are not a retry
# switch and cannot be supplied by the issue body.
FAILED_CORRECTION_RUNTIME = "rt_67d93377c49440f99b311cca079280fd"
FAILED_CORRECTION_REQUEST = "4df930cb2812ec444d03e1b197e3cbef4ba4c2b6e4d5a1b14847864f96f06c21"
FAILED_CORRECTION_RUN = 37564091557
# This is the final paid slot for the same frozen evidence scope.  Neither comments,
# inventory edits, the newest run nor a verdict can open a third slot.
IDEMPOTENCY_KEY = "c13-pg-correction-v2:" + ROUND
MARKER = "c13 supplement:"
# `PROFILE` above names the frozen EVIDENCE scope and stays V1 forever: the failed V1
# stored request, the execution-side envelope checks and the prior-outbox validation all
# read it, so renaming it would invalidate history instead of guarding it.  ACTIVATION is
# therefore a separate identity, and it is an ADMISSION-ONLY one: `ACTIVATION_PROFILE`
# never travels in the payload or in `runtime_transport`, and `ENVELOPE["profile"]` stays
# `PROFILE` because that is what the workflow and the pytest plugin check.  The V1 marker
# is a CONSUMED generation - it already reached GitHub once and terminated before pytest -
# so it must never open a slot again.
ACTIVATION_PROFILE = "PG533-15-V2"


def requested_profile(body):
    """Which generation this issue body asks to ACTIVATE, or a refusal.

    Three outcomes, and the difference between them is the whole point:

    * no `C13 supplement:` line at all -> `None`; an ordinary review issue, untouched.
    * exactly `PG533-15-V2`            -> that profile; the one explicit activation.
    * anything else                    -> raise, i.e. refuse.

    The consumed V1 marker must RAISE rather than return `None`.  Returning `None` would
    let the issue fall through to the ordinary review path and commission a SECOND C14 for
    a scope that already has one; raising stops it at the ingress with a named reason and
    no Runtime call.  Among the markers this function does read, a body that still carries
    the consumed generation is refused as consumed whatever else it also carries, so a
    half-finished V1 -> V2 body edit cannot half-activate the recovery slot.

    Marker detection is unchanged: only an unprefixed `C13 supplement:` line is a marker,
    so surrounding whitespace is trimmed but a leading list or emphasis marker is not.  A
    body whose only such line carries a `-`/`*`/`+` prefix is therefore not a supplement
    request and takes the ordinary path.  That is bounded and fail-closed where it counts -
    `None` selects the ordinary review plan, and only `ACTIVATION_PROFILE` selects the
    supplement, so no prefixed line can reach the paid slot.
    """
    values = [line.strip()[len(MARKER):].strip() for line in body.splitlines()
              if line.strip().lower().startswith(MARKER)]
    if not values:
        return None
    if values == [ACTIVATION_PROFILE]:
        return ACTIVATION_PROFILE
    if PROFILE in values:
        raise ValueError("C13_SUPPLEMENT_V1_CONSUMED")
    raise ValueError("C13_SUPPLEMENT_PROFILE_NOT_AUTHORIZED")


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
