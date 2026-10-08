"""Offline tests for the shared C1 execution contract.

The point of these tests is that BOTH sides of the path derive the same identity from
the same facts, and that a result claiming to belong to a task is checked against that
task rather than trusted.
"""
import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import c1_execution_contract as contract  # noqa: E402

TASK = "rt_" + "c" * 32
REQUEST = contract.execution_request_id(TASK, 1)


def sealed(**overrides):
    document = {
        "version": 1,
        "kind": contract.RESULT_KIND,
        "runtime_task_id": TASK,
        "attempt": 1,
        "execution_request_id": REQUEST,
        "github_run_id": 36870000000,
        "github_run_attempt": 1,
        "provider": contract.PROVIDER,
        "model": "gpt-5.6-sol",
        "response_id": "resp_1",
        "status": "SUCCEEDED",
        "output_sha256": contract.output_sha256(contract.EXPECTED_OUTPUT),
        "output": contract.EXPECTED_OUTPUT,
        "accepted": True,
        "reused_terminal_result": False,
        "authorizes_any_action": False,
    }
    document.update(overrides)
    return document


class FixedTopologyTests(unittest.TestCase):
    def test_nothing_about_where_it_runs_is_a_task_input(self):
        self.assertEqual(contract.REPO, "yuguangzhi3836-glitch/GO")
        self.assertEqual(contract.WORKFLOW_FILE, "c1-ai-execution-backend-v1.yml")
        self.assertEqual(contract.REF, "main")
        self.assertTrue(contract.DISPATCH_ENDPOINT.startswith(
            "/repos/yuguangzhi3836-glitch/GO/actions/workflows/"))
        self.assertEqual(
            set(contract.PAYLOAD), {"schema_version", "smoke_id"})

    def test_the_only_dispatch_inputs_are_the_identity_triple(self):
        request = contract.build_dispatch_request(TASK, 1)
        self.assertEqual(set(contract.dispatch_inputs(request)),
                         {"runtime_task_id", "attempt", "execution_request_id"})

    def test_the_provider_and_endpoint_are_not_parameters(self):
        self.assertEqual(contract.API_URL, "https://api.openai.com/v1/responses")
        self.assertEqual(contract.PROVIDER, "OPENAI_RESPONSES_API")


class IdentityTests(unittest.TestCase):
    def test_identity_is_derived_and_stable(self):
        self.assertEqual(contract.execution_request_id(TASK, 1), REQUEST)
        self.assertEqual(contract.execution_request_id(TASK, 1), REQUEST)
        self.assertEqual(len(REQUEST), 64)

    def test_identity_changes_with_the_task_or_the_attempt(self):
        self.assertNotEqual(contract.execution_request_id(TASK, 2), REQUEST)
        self.assertNotEqual(contract.execution_request_id("rt_" + "d" * 32, 1), REQUEST)

    def test_identity_refuses_incomplete_runtime_facts(self):
        for task, attempt in (("", 1), (TASK, 0), (TASK, -1), (TASK, True), (None, 1)):
            with self.assertRaises(contract.Refused, msg=repr((task, attempt))):
                contract.execution_request_id(task, attempt)

    def test_the_request_carries_the_derived_identity_and_the_fixed_topology(self):
        request = contract.build_dispatch_request(TASK, 3)
        self.assertEqual(request["execution_request_id"], contract.execution_request_id(TASK, 3))
        self.assertEqual(request["repo"], contract.REPO)
        self.assertEqual(request["ref"], contract.REF)
        self.assertEqual(request["workflow_file"], contract.WORKFLOW_FILE)
        self.assertEqual(request["payload"], contract.PAYLOAD)
        self.assertEqual(request["owner_c"], "C1")
        self.assertEqual(request["task_kind"], "AI_WORK_V1")

    def test_the_run_name_is_the_identity(self):
        self.assertEqual(contract.run_identity_name(TASK, 1, REQUEST),
                         "C1 %s 1 %s" % (TASK, REQUEST))


class ReviewRoundRevisionTests(unittest.TestCase):
    """`review_round_identity(..., revision=)` - the one-way door, and its one new door.

    The live round this was built for is used as the literal: issue #559 and candidate
    `22df468b...` is the round that ran on RT01 as `rt_d21926f78f9f434e9830a3e43106018d`, and
    its identity is already recorded in Runtime Evidence and in the sealed C14 receipt. Any
    change to the revision-1 derivation would orphan that Evidence, so revision 1 is checked
    against the value that is actually live rather than against a new expectation.
    """
    ISSUE = 559
    CANDIDATE = "22df468b7ed22a66707d3108e3d9568597619f04"
    LIVE_R1_ROUND = "FORMAL-REVIEW-I559-22df468b7ed2"

    def test_revision_one_is_the_live_rounds_identity_byte_for_byte(self):
        self.assertEqual(contract.review_round_identity(self.ISSUE, self.CANDIDATE),
                         {"ledger_round_id": self.LIVE_R1_ROUND,
                          "c14_task_id": self.LIVE_R1_ROUND + "-C14",
                          "c13_task_id": self.LIVE_R1_ROUND + "-C13"})
        # The no-argument form and the explicit form must be indistinguishable: a caller that
        # predates the revision (the Builder path) cannot be given a different answer.
        self.assertEqual(contract.review_round_identity(self.ISSUE, self.CANDIDATE),
                         contract.review_round_identity(self.ISSUE, self.CANDIDATE, 1))

    def test_a_later_revision_is_the_same_derivation_with_a_suffix(self):
        r2 = contract.review_round_identity(self.ISSUE, self.CANDIDATE, 2)
        self.assertEqual(r2["ledger_round_id"], self.LIVE_R1_ROUND + "-R2")
        self.assertEqual(r2["c14_task_id"], self.LIVE_R1_ROUND + "-R2-C14")
        self.assertEqual(r2["c13_task_id"], self.LIVE_R1_ROUND + "-R2-C13")

    def test_every_derived_name_moves_with_the_revision(self):
        # The request id and the Runtime idempotency key are not computed here, but they are
        # derived from the round id, so they move together. This states the property the
        # R2 round depends on rather than restating the two derivations.
        r1 = contract.review_round_identity(self.ISSUE, self.CANDIDATE)
        r2 = contract.review_round_identity(self.ISSUE, self.CANDIDATE, 2)
        self.assertNotEqual(contract.review_request_id(self.CANDIDATE, r1["ledger_round_id"]),
                            contract.review_request_id(self.CANDIDATE, r2["ledger_round_id"]))
        self.assertNotEqual(
            contract.task_idempotency_key(contract.C14_REVIEW_KIND, "C14", r1["c14_task_id"]),
            contract.task_idempotency_key(contract.C14_REVIEW_KIND, "C14", r2["c14_task_id"]))

    def test_the_revision_is_never_inferred_only_passed(self):
        import inspect

        parameter = inspect.signature(
            contract.review_round_identity).parameters["revision"]
        self.assertIs(parameter.default, 1)
        self.assertIs(parameter.kind, inspect.Parameter.POSITIONAL_OR_KEYWORD)

    def test_revisions_outside_the_bound_are_refused(self):
        for revision in (0, -1, -99, 100, 1000, True, False, "1", "2", 1.0, 2.0, None, [1]):
            with self.subTest(revision=revision):
                with self.assertRaises(contract.Refused) as caught:
                    contract.review_round_identity(self.ISSUE, self.CANDIDATE, revision)
                self.assertEqual(caught.exception.reason, "REVIEW_REVISION_INVALID")

    def test_the_boundary_revisions_are_accepted(self):
        for revision in (1, 2, 99):
            with self.subTest(revision=revision):
                round_id = contract.review_round_identity(
                    self.ISSUE, self.CANDIDATE, revision)["ledger_round_id"]
                self.assertEqual(round_id.startswith(self.LIVE_R1_ROUND), True)
                # Every derived name still fits the id bound the payload enforces.
                self.assertLess(len(round_id + "-C14"), contract.MAX_REVIEW_ID)
        self.assertEqual(contract.MAX_REVIEW_REVISION, 99)

    def test_the_candidate_and_issue_checks_still_come_first(self):
        # A bad revision must not mask a bad candidate: the pre-existing refusals are
        # unchanged, in the same order.
        with self.assertRaises(contract.Refused) as caught:
            contract.review_round_identity(0, self.CANDIDATE, 2)
        self.assertEqual(caught.exception.reason, "ISSUE_NUMBER_INVALID")
        with self.assertRaises(contract.Refused) as caught:
            contract.review_round_identity(self.ISSUE, "not-a-sha", 2)
        self.assertEqual(caught.exception.reason, "REVIEW_CANDIDATE_SHA_INVALID")

    def test_a_revision_does_not_change_anything_else_about_the_round(self):
        # Same candidate, same provenance, same shape: the revision names a different round,
        # it does not change what a round is.
        for revision in (1, 2, 99):
            with self.subTest(revision=revision):
                identity = contract.review_round_identity(self.ISSUE, self.CANDIDATE, revision)
                self.assertEqual(set(identity),
                                 {"ledger_round_id", "c14_task_id", "c13_task_id"})
                self.assertEqual(identity["c14_task_id"], identity["ledger_round_id"] + "-C14")
                self.assertEqual(identity["c13_task_id"], identity["ledger_round_id"] + "-C13")


class ResultValidationTests(unittest.TestCase):
    def test_a_well_formed_result_is_accepted(self):
        contract.validate_result(sealed(), runtime_task_id=TASK, attempt=1,
                                 execution_request_id_=REQUEST)

    def test_every_field_is_required(self):
        for field in sorted(contract.RESULT_FIELDS):
            broken = sealed()
            broken.pop(field)
            with self.assertRaises(contract.Refused, msg=field) as caught:
                contract.validate_result(broken, runtime_task_id=TASK, attempt=1,
                                         execution_request_id_=REQUEST)
            self.assertEqual(caught.exception.reason, "RESULT_MISSING_FIELDS")

    def test_unexpected_fields_are_refused(self):
        broken = sealed(prompt="do something else")
        with self.assertRaises(contract.Refused) as caught:
            contract.validate_result(broken, runtime_task_id=TASK, attempt=1,
                                     execution_request_id_=REQUEST)
        self.assertEqual(caught.exception.reason, "RESULT_UNEXPECTED_FIELDS")

    def test_a_failure_reason_is_allowed_only_on_a_failure(self):
        broken = sealed(failure_reason="BOOM")
        with self.assertRaises(contract.Refused):
            contract.validate_result(broken, runtime_task_id=TASK, attempt=1,
                                     execution_request_id_=REQUEST)

    def test_a_result_for_another_task_or_attempt_is_refused(self):
        other_task = sealed(runtime_task_id="rt_" + "e" * 32)
        with self.assertRaises(contract.Refused) as caught:
            contract.validate_result(other_task, runtime_task_id=TASK, attempt=1,
                                     execution_request_id_=REQUEST)
        self.assertEqual(caught.exception.reason, "RESULT_TASK_MISMATCH")

        other_attempt = sealed(attempt=2)
        with self.assertRaises(contract.Refused) as caught:
            contract.validate_result(other_attempt, runtime_task_id=TASK, attempt=1,
                                     execution_request_id_=REQUEST)
        self.assertEqual(caught.exception.reason, "RESULT_ATTEMPT_MISMATCH")

    def test_a_stale_attempt_cannot_be_completed(self):
        # The result is valid for attempt 1; asking to complete attempt 2 must refuse.
        with self.assertRaises(contract.Refused) as caught:
            contract.validate_result(sealed(), runtime_task_id=TASK, attempt=2,
                                     execution_request_id_=contract.execution_request_id(TASK, 2))
        self.assertEqual(caught.exception.reason, "RESULT_ATTEMPT_MISMATCH")

    def test_a_result_claiming_another_execution_identity_is_refused(self):
        broken = sealed(execution_request_id=contract.execution_request_id(TASK, 5))
        with self.assertRaises(contract.Refused) as caught:
            contract.validate_result(broken, runtime_task_id=TASK, attempt=1,
                                     execution_request_id_=REQUEST)
        self.assertEqual(caught.exception.reason, "RESULT_EXECUTION_REQUEST_ID_MISMATCH")

    def test_the_output_hash_is_recomputed(self):
        broken = sealed(output=contract.EXPECTED_OUTPUT, output_sha256="0" * 64)
        with self.assertRaises(contract.Refused) as caught:
            contract.validate_result(broken, runtime_task_id=TASK, attempt=1,
                                     execution_request_id_=REQUEST)
        self.assertEqual(caught.exception.reason, "RESULT_OUTPUT_HASH_MISMATCH")

    def test_a_result_may_not_authorize_anything(self):
        broken = sealed(authorizes_any_action=True)
        with self.assertRaises(contract.Refused) as caught:
            contract.validate_result(broken, runtime_task_id=TASK, attempt=1,
                                     execution_request_id_=REQUEST)
        self.assertEqual(caught.exception.reason,
                         "RESULT_MUST_NOT_AUTHORIZE_ANY_ACTION")

    def test_status_must_agree_with_accepted(self):
        broken = sealed(status="FAILED")
        with self.assertRaises(contract.Refused) as caught:
            contract.validate_result(broken, runtime_task_id=TASK, attempt=1,
                                     execution_request_id_=REQUEST)
        self.assertEqual(caught.exception.reason,
                         "RESULT_STATUS_INCONSISTENT_WITH_ACCEPTED")

    def test_an_accepted_result_must_carry_the_expected_output(self):
        output = "some other text"
        broken = sealed(output=output, output_sha256=contract.output_sha256(output))
        with self.assertRaises(contract.Refused) as caught:
            contract.validate_result(broken, runtime_task_id=TASK, attempt=1,
                                     execution_request_id_=REQUEST)
        self.assertEqual(caught.exception.reason,
                         "RESULT_ACCEPTED_WITHOUT_THE_EXPECTED_OUTPUT")

    def test_a_failed_result_is_valid_and_must_carry_a_reason(self):
        output = "not the smoke string"
        failed = sealed(status="FAILED", accepted=False, output=output,
                        output_sha256=contract.output_sha256(output),
                        failure_reason="MODEL_OUTPUT_DID_NOT_MATCH_SMOKE_STRING")
        contract.validate_result(failed, runtime_task_id=TASK, attempt=1,
                                 execution_request_id_=REQUEST)
        without_reason = copy.deepcopy(failed)
        without_reason.pop("failure_reason")
        with self.assertRaises(contract.Refused) as caught:
            contract.validate_result(without_reason, runtime_task_id=TASK, attempt=1,
                                     execution_request_id_=REQUEST)
        self.assertEqual(caught.exception.reason, "RESULT_FAILED_WITHOUT_A_REASON")

    def test_malformed_documents_are_refused(self):
        for broken in (None, [], "result", 7, {}):
            with self.assertRaises(contract.Refused, msg=repr(broken)):
                contract.validate_result(broken, runtime_task_id=TASK, attempt=1,
                                         execution_request_id_=REQUEST)

    def test_a_wrong_run_identity_is_refused(self):
        for field, value in (("github_run_id", 0), ("github_run_id", "1"),
                             ("github_run_attempt", 0), ("github_run_attempt", None)):
            broken = sealed(**{field: value})
            with self.assertRaises(contract.Refused, msg=field):
                contract.validate_result(broken, runtime_task_id=TASK, attempt=1,
                                         execution_request_id_=REQUEST)

    def test_a_wrong_provider_is_refused(self):
        broken = sealed(provider="SOME_OTHER_PROVIDER")
        with self.assertRaises(contract.Refused) as caught:
            contract.validate_result(broken, runtime_task_id=TASK, attempt=1,
                                     execution_request_id_=REQUEST)
        self.assertEqual(caught.exception.reason, "RESULT_PROVIDER_MISMATCH")

    def test_canonical_form_is_stable_and_order_independent(self):
        self.assertEqual(contract.canonical({"b": 1, "a": [2, 3]}), '{"a":[2,3],"b":1}')
        self.assertEqual(contract.canonical(dict(sealed())),
                         contract.canonical(dict(reversed(list(sealed().items())))))


if __name__ == "__main__":
    unittest.main()
