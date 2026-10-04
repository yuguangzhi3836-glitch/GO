"""C01-C12: one Builder executor, twelve cells, and the cell carried by the task.

What this file is for
---------------------
The Builder was proven live for one cell. Generalising it to twelve asks a small number of
questions, and each of them is about an identity or about a boundary:

  A  which spellings name a cell the Builder may run for, and which are refused?
  B  does that set still agree with the workbench's own definition of the cells?
  C  is the C1 execution identity unchanged - byte for byte - after the change?
  D  is the legacy Responses identity unchanged as well?
  E  do two cells' otherwise identical tasks get two different identities?
  F  is there still exactly one worker, one outbox and one workflow?
  G  can one worker claim for every cell, and for none of the control-only ones?
  H  does where a scan begins have any effect on identity? (it must not)
  I  does a C12 execution still resume exactly-once across a restart?
  J  does a failure return to its own cell?
  K  is C13/C14 refused in every layer that can see it?
  O  does the U6 seam answer BYPASS without pretending anything was reviewed?
  P  does the issue path carry the cell from title to Runtime call?

What is real and what is a double
---------------------------------
  REAL      every module in the channel, and the Runtime double reused from
            `test_c1_execution_loop` - the same fencing-faithful double the
            single-executor proofs used.
  DOUBLE    the GitHub transport (`GhawSealingTransport` and friends, reused from
            `test_c1_executor_boundary`), which seals a gh-aw-shaped result offline.
  NOT PROVEN HERE
            that a workflow is registered, that a dispatch reaches it, or that any cell's
            work is good. This is the offline boundary, not a live run.

No network, no credential, no paid call, no dispatch.
"""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
DEFINITIONS = REPO / "application" / "src" / "go_hotel" / "workbench" / "definitions.py"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import c1_dispatch_outbox as outbox_mod  # noqa: E402
import c1_execution_contract as contract  # noqa: E402
import c1_execution_loop as loop_mod  # noqa: E402
import c1_ghaw_builder_worker as ghaw  # noqa: E402
import c1_issue_ingress as ingress  # noqa: E402
import c1_solution_leak_gate as gate  # noqa: E402
import c1_worker as worker  # noqa: E402
import test_c1_execution_loop as harness  # noqa: E402
import test_c1_executor_boundary as boundary  # noqa: E402

WORKER_ID = ghaw.WORKER_ID
LEASE_S = 120

# The execution identities the deployed code has always produced for one fixed C1 task.
# Computed from the contract as it stands on the current main, BEFORE this generalisation,
# and pinned here so that any drift shows up as a failing test rather than as a second
# paid dispatch for a task that was already answered.
GOLDEN_TASK = "rt_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
GOLDEN_REQUEST_ID = "ba75f59ee2547d4168ffc7480943004cfabf9f41933626039ef567b2f51c5401"
GOLDEN_REAL_REQUEST_ID = "1fcb7598a6f14802750605428ee5116e1cdb45c70c1cc86e545cd092faf2b4bf"
GOLDEN_SMOKE_REQUEST_ID = "12d810e9b7a3c51d04d37d7a88074ee59d18de9582a2068dc1fc536006e20eba"
GOLDEN_GH_AW_PROMPT_SHA = "323a0c0a893ff43c4a34184effa6e6168bf6d87d2aeaaf4e0cc6652face099ec"
GOLDEN_REAL_PROMPT_SHA = "0ed7c453d411e7558d23c59ebc34416c28296dcb9fff81fb5715e69d30b98f0b"
GOLDEN_PAYLOAD_SHA = "f8597e545a96715267cb78efc45c1670540f34e96b70fd188dbbb735eecd1084"
GOLDEN_IDEMPOTENCY = "c1-ghaw-builder-v1:C1:C01-GOLDEN-1"
GOLDEN_SMOKE_IDEMPOTENCY = "c1-real-ai-worker-v1:smoke:1"
GOLDEN_REAL_IDEMPOTENCY = "c1-ai-task-v1:C1:C01-GOLDEN-1"

GOLDEN_PAYLOAD = {
    "schema_version": 1, "cell_id": "C01", "external_task_id": "C01-GOLDEN-1",
    "objective": "Golden objective: one short line.",
    "scope": "Golden scope: no real execution.",
}

FIXTURE = HERE / "issue_fixtures" / "real_c01_issues.json"


class FailingRunTransport:
    """Offline GitHub whose run exists, completes, and does not succeed.

    This is the shape "the edits landed but the Draft PR step did not": a run that is
    finished and failed. A correct implementation must report the failure to the Runtime
    rather than hunt for a result that cannot exist, and must never dispatch again.
    """

    def __init__(self, *, run_id=717171, conclusion="failure"):
        self.dispatch_calls = 0
        self.conclusion = conclusion
        self.run_id = run_id

    def send(self, request):
        self.dispatch_calls += 1
        return ("sent", self.run_id)

    def find_run(self, run_name):
        return None

    def find_run_by_name(self, name):
        return {"id": self.run_id, "run_attempt": 1, "status": "completed",
                "conclusion": self.conclusion, "head_sha": "0" * 40}

    def get_run(self, run_id):
        return {"id": run_id, "run_attempt": 1, "status": "completed",
                "conclusion": self.conclusion, "head_sha": "0" * 40}

    def download_artifact(self, run_id, name):
        raise AssertionError("a run that did not succeed has no artifact to read")


def load_issue(number=79):
    with open(FIXTURE, encoding="utf-8") as handle:
        document = json.load(handle)
    for issue in document["issues"]:
        if issue["number"] == number:
            return json.loads(json.dumps(issue))
    raise AssertionError("fixture issue %s is missing" % number)


def builder_payload(cell="C01", *, external_task_id="C01-BUILDER-1",
                    objective="Do the bounded thing.",
                    scope="No real execution; offline only."):
    """A Builder payload for one cell, validated against the Builder's own boundary."""
    return contract.build_task_payload(
        cell_id=cell, external_task_id=external_task_id, objective=objective,
        scope=scope, allowed_owner_cs=contract.BUILDER_OWNER_CS)


def build_workbench_definitions():
    """Load the workbench's definitions module without importing the whole package.

    `go_hotel.workbench.__init__` pulls in the controller, the merge controller and the
    thin-workspace helpers; none of that is needed here, and any of it could fail to import
    for reasons that have nothing to do with cell boundaries. So the two packages are
    registered as empty namespaces and only `types` and `definitions` are loaded - which is
    also the honest shape: this test reads the DEFINITION, not the machinery.
    """
    src = REPO / "application" / "src"
    for name in ("go_hotel", "go_hotel.workbench"):
        if name not in sys.modules:
            package = types.ModuleType(name)
            package.__path__ = [str(src / name.replace(".", "/"))]
            sys.modules[name] = package
    for name in ("go_hotel.workbench.types", "go_hotel.workbench.definitions"):
        if name not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                name, src / (name.replace(".", "/") + ".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
    return sys.modules["go_hotel.workbench.definitions"]


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="c01-c12-")
        self.addCleanup(self._tmp.cleanup)
        self.clock = harness.Clock()
        self.runtime = harness.RuntimeDouble(self.clock)
        self.outbox = outbox_mod.DispatchOutbox(str(Path(self._tmp.name) / "outbox.db"))
        # Registered after the temp dir, so it runs before it: on Windows an open sqlite
        # handle keeps the file locked and the directory cleanup would fail.
        self.addCleanup(self.outbox.close)

    def claim_for(self, *, cursor=0):
        return worker.claim_across_owners(
            self.runtime, worker_id=WORKER_ID, lease_s=LEASE_S,
            claim_kinds=ghaw.CLAIM_KINDS, claim_owner_cs=ghaw.CLAIM_OWNER_CS,
            cursor=cursor)

    def enqueue(self, cell, *, external_task_id=None, key=None, max_attempts=1):
        payload = builder_payload(cell, external_task_id=external_task_id
                                  or "%s-TASK" % cell)
        return self.runtime.enqueue(cell, contract.GHAW_BUILDER_KIND, payload,
                                    idempotency_key=key, max_attempts=max_attempts)


# =============================================================== A
class A_WhichCellsTheBuilderServes(unittest.TestCase):
    """The range, and the fact that it is a range and not a spelling."""

    def test_every_builder_cell_is_accepted_in_both_spellings(self):
        for canonical, padded in (("C1", "C01"), ("C2", "C02"), ("C9", "C09"),
                                  ("C10", "C10"), ("C11", "C11"), ("C12", "C12")):
            for spelling in (canonical, padded):
                with self.subTest(spelling=spelling):
                    self.assertEqual(builder_payload(spelling)["cell_id"], canonical)

    def test_the_control_only_cells_are_refused_by_the_validator(self):
        for cell in ("C13", "C14"):
            with self.subTest(cell=cell):
                with self.assertRaises(contract.Refused) as raised:
                    builder_payload(cell)
                self.assertEqual(raised.exception.reason,
                                 "TASK_PAYLOAD_CELL_NOT_OWNED_BY_THIS_EXECUTOR")

    def test_anything_that_is_not_a_cell_is_refused(self):
        for cell in ("C0", "C00", "C15", "C99", "", "C1x", "cell 3", None, 1, ["C2"]):
            with self.subTest(cell=cell):
                with self.assertRaises(contract.Refused):
                    builder_payload(cell)

    def test_the_global_parser_still_knows_all_fourteen_cells(self):
        # Excluding C13/C14 from the Builder must not damage the shared canonicaliser: the
        # kernel really does have fourteen cells, and everything else that reads a cell
        # goes through this one function.
        for index in range(1, 15):
            with self.subTest(index=index):
                self.assertEqual(contract.canonical_cell_id("C%02d" % index),
                                 "C%d" % index)
                self.assertEqual(contract.canonical_cell_id("C%d" % index), "C%d" % index)
        self.assertEqual(contract.canonical_cell_id("C13"), "C13")
        self.assertEqual(contract.canonical_cell_id("C14"), "C14")

    def test_the_builder_range_is_exactly_c1_to_c12(self):
        self.assertEqual(contract.BUILDER_OWNER_CS,
                         tuple("C%d" % index for index in range(1, 13)))
        self.assertNotIn("C13", contract.BUILDER_OWNER_CS)
        self.assertNotIn("C14", contract.BUILDER_OWNER_CS)
        self.assertEqual(contract.allowed_owner_cs_for_kind(contract.GHAW_BUILDER_KIND),
                         contract.BUILDER_OWNER_CS)

    def test_the_responses_kind_still_admits_c1_only(self):
        for kind in (contract.REAL_TASK_KIND, contract.KIND):
            with self.subTest(kind=kind):
                self.assertEqual(contract.allowed_owner_cs_for_kind(kind), ("C1",))
        with self.assertRaises(contract.Refused) as raised:
            contract.build_task_payload(
                cell_id="C02", external_task_id="X", objective="o", scope="s",
                allowed_owner_cs=contract.allowed_owner_cs_for_kind(
                    contract.REAL_TASK_KIND))
        self.assertEqual(raised.exception.reason,
                         "TASK_PAYLOAD_CELL_NOT_OWNED_BY_THIS_EXECUTOR")


# =============================================================== B
class B_TheWorkbenchDefinesTheBoundary(unittest.TestCase):
    """The Builder's range is bound to the workbench's own declaration of the cells."""

    @classmethod
    def setUpClass(cls):
        cls.definitions = build_workbench_definitions()

    def test_the_definition_is_present_and_is_the_authority(self):
        self.assertTrue(DEFINITIONS.is_file(),
                        "the workbench definitions must be present to bind the Builder's "
                        "cell range to the Owner's own declaration of the cells")

    def test_the_builder_range_is_exactly_the_non_control_only_cells(self):
        workspaces = self.definitions.WORKSPACES
        by_id = {workspace.cell_id: workspace for workspace in workspaces}
        plain = tuple(workspace.cell_id for workspace in workspaces
                      if not workspace.control_only)
        control = tuple(workspace.cell_id for workspace in workspaces
                        if workspace.control_only)
        # The definition spells cells `C01`..`C14`; the range is written canonically.
        self.assertEqual(plain, tuple("C%02d" % index for index in range(1, 13)))
        self.assertEqual(control, ("C13", "C14"))
        self.assertEqual(contract.BUILDER_OWNER_CS,
                         tuple(contract.canonical_cell_id(cell_id) for cell_id in plain))
        self.assertEqual(by_id["C13"].control_only, True)
        self.assertEqual(by_id["C14"].control_only, True)
        for index in range(1, 13):
            with self.subTest(cell=index):
                self.assertIs(by_id["C%02d" % index].control_only, False)

    def test_the_policy_still_forbids_a_builder_for_c13(self):
        rules = self.definitions.WORKBENCH_POLICY["rules"]
        self.assertIs(rules["c13_builder_forbidden"], True)
        self.assertIs(rules["c14_business_truth_mutation_forbidden"], True)


# =============================================================== C
class C_TheLiveC1IdentityIsFrozen(unittest.TestCase):
    """The identity the deployed C01 execution already has must not move.

    If it did, an already-answered execution would look like a brand-new one and a second
    paid model call would become possible. The values were taken from the contract as it
    stands on main before this change.
    """

    def _ghaw_request(self):
        spec = contract.task_spec(contract.GHAW_BUILDER_KIND, GOLDEN_PAYLOAD)
        return contract.build_dispatch_request(GOLDEN_TASK, 1, spec)

    def test_the_gh_aw_binding_and_request_id_are_unchanged(self):
        request = self._ghaw_request()
        self.assertEqual(request["execution_request_id"], GOLDEN_REQUEST_ID)
        self.assertEqual(request["owner_c"], "C1")
        self.assertEqual(request["payload"]["cell_id"], "C1")
        self.assertEqual(request["payload_sha256"], GOLDEN_PAYLOAD_SHA)
        self.assertEqual(request["prompt_sha256"], GOLDEN_GH_AW_PROMPT_SHA)
        self.assertEqual(request["provider"], contract.PROVIDER_GHAW_BUILDER)
        self.assertEqual(request["workflow_file"], contract.GHAW_BUILDER_WORKFLOW_FILE)

    def test_the_gh_aw_run_name_and_idempotency_are_unchanged(self):
        request = self._ghaw_request()
        self.assertEqual(
            contract.run_identity_name(GOLDEN_TASK, 1, GOLDEN_REQUEST_ID),
            "C1 %s 1 %s" % (GOLDEN_TASK, GOLDEN_REQUEST_ID))
        self.assertEqual(
            contract.task_idempotency_key(contract.GHAW_BUILDER_KIND, "C01",
                                          "C01-GOLDEN-1"),
            GOLDEN_IDEMPOTENCY)

    def test_the_prompt_bytes_for_c1_are_unchanged(self):
        prompt = contract.prompt_for_task(contract.GHAW_BUILDER_KIND, GOLDEN_PAYLOAD)
        self.assertTrue(prompt.startswith("GO C1 gh-aw Builder task (GHAW_BUILDER_V1).\n"))
        self.assertEqual(contract.prompt_sha256(prompt), GOLDEN_GH_AW_PROMPT_SHA)

    def test_the_run_name_leads_with_the_executions_own_cell(self):
        # The run name is how a dispatch with an unknown HTTP outcome is resolved, so the
        # cell has to be in it - a C12 run looked up under a C1 name would simply never be
        # found, and the execution would sit in the outbox forever. C1 renders exactly the
        # bytes it always has, which is why the freeze test above still passes.
        for cell in ("C1", "C2", "C12"):
            with self.subTest(cell=cell):
                name = contract.run_identity_name(GOLDEN_TASK, 1, "RID", owner_c=cell)
                self.assertTrue(name.startswith(cell + " "), name)
        source = (WORKFLOWS / "c1-gh-aw-builder-v1.md").read_text(encoding="utf-8")
        self.assertIn('run-name: "${{ inputs.owner_c }} ', source)


# =============================================================== D
class D_TheLegacyResponsesIdentityIsFrozen(unittest.TestCase):
    """The Responses class keeps C1, its identity and its schedule."""

    def test_the_smoke_binding_is_unchanged(self):
        binding = contract.task_binding(GOLDEN_TASK, 1)
        self.assertEqual(binding["owner_c"], "C1")
        self.assertEqual(binding["idempotency_key"], GOLDEN_SMOKE_IDEMPOTENCY)
        self.assertEqual(contract.execution_request_id(GOLDEN_TASK, 1),
                         GOLDEN_SMOKE_REQUEST_ID)
        self.assertEqual(
            contract.run_identity_name(GOLDEN_TASK, 1, GOLDEN_SMOKE_REQUEST_ID),
            "C1 %s 1 %s" % (GOLDEN_TASK, GOLDEN_SMOKE_REQUEST_ID))

    def test_the_responses_real_task_identity_is_unchanged(self):
        spec = contract.task_spec(contract.REAL_TASK_KIND, GOLDEN_PAYLOAD)
        request = contract.build_dispatch_request(GOLDEN_TASK, 1, spec)
        self.assertEqual(request["execution_request_id"], GOLDEN_REAL_REQUEST_ID)
        self.assertEqual(request["owner_c"], "C1")
        self.assertEqual(request["prompt_sha256"], GOLDEN_REAL_PROMPT_SHA)
        self.assertEqual(contract.real_idempotency_key("C01", "C01-GOLDEN-1"),
                         GOLDEN_REAL_IDEMPOTENCY)

    def test_the_responses_executor_still_serves_one_cell_and_two_kinds(self):
        self.assertEqual(worker.OWNER_C, "C1")
        self.assertEqual(worker.CLAIM_OWNER_CS, ("C1",))
        self.assertEqual(worker.CLAIM_KINDS, ("AI_WORK_V1", "AI_TASK_V1"))
        self.assertNotIn(contract.GHAW_BUILDER_KIND, worker.CLAIM_KINDS)


# =============================================================== E
class E_TwoCellsTwoIdentities(unittest.TestCase):
    """The cell is inside the identity, so the same words in two cells are two tasks."""

    def _requests(self):
        requests = {}
        for cell in ("C1", "C2", "C12"):
            payload = builder_payload(cell, external_task_id="SAME-TASK",
                                      objective="Same objective.", scope="Same scope.")
            spec = contract.task_spec(contract.GHAW_BUILDER_KIND, payload)
            requests[cell] = contract.build_dispatch_request(GOLDEN_TASK, 1, spec)
        return requests

    def test_the_owner_and_the_request_id_differ_per_cell(self):
        requests = self._requests()
        self.assertEqual([requests[cell]["owner_c"] for cell in ("C1", "C2", "C12")],
                         ["C1", "C2", "C12"])
        ids = [requests[cell]["execution_request_id"] for cell in ("C1", "C2", "C12")]
        self.assertEqual(len(set(ids)), 3, "one cell's execution must not be another's")

    def test_the_idempotency_key_differs_per_cell(self):
        keys = {contract.task_idempotency_key(contract.GHAW_BUILDER_KIND, cell,
                                              "SAME-TASK")
                for cell in ("C1", "C2", "C12")}
        self.assertEqual(len(keys), 3)

    def test_the_prompt_names_the_tasks_own_cell(self):
        for cell in ("C2", "C12"):
            with self.subTest(cell=cell):
                payload = builder_payload(cell, external_task_id="SAME-TASK")
                prompt = contract.prompt_for_task(contract.GHAW_BUILDER_KIND, payload)
                self.assertTrue(prompt.startswith(
                    "GO %s gh-aw Builder task (GHAW_BUILDER_V1).\n" % cell))


# =============================================================== F
class F_OneOfEverything(unittest.TestCase):
    """Twelve cells must not become twelve of anything."""

    def test_one_executor_module_and_one_unit(self):
        self.assertEqual(sorted(p.name for p in HERE.glob("*ghaw*worker*.py")),
                         ["c1_ghaw_builder_worker.py"])
        self.assertEqual(sorted(p.name for p in (HERE / "systemd").glob("*ghaw*")),
                         ["go-runtime-host-ghaw-builder-worker.service"])

    def test_the_worker_declares_one_boundary_for_all_twelve_cells(self):
        self.assertEqual(ghaw.WORKER_ID, "go-runtime-host-ghaw-builder-worker")
        self.assertEqual(ghaw.OUTBOX_DB, "/var/lib/go-runtime-c1/outbox-ghaw-builder.db")
        self.assertEqual(ghaw.WORKFLOW_FILE, contract.GHAW_BUILDER_WORKFLOW_FILE)
        self.assertEqual(ghaw.CLAIM_KINDS, (contract.GHAW_BUILDER_KIND,))
        self.assertEqual(ghaw.CLAIM_OWNER_CS, contract.BUILDER_OWNER_CS)
        self.assertFalse(hasattr(ghaw, "OWNER_C"),
                         "a single-cell constant must not survive on the Builder")

    def test_there_is_no_per_cell_worker_outbox_or_unit(self):
        for index in range(2, 15):
            cell = "c%d" % index
            with self.subTest(cell=cell):
                for pattern in ("%s_worker*.py" % cell, "%s_*.py" % cell,
                                "*%s-worker*" % cell):
                    self.assertEqual(sorted(HERE.glob(pattern)), [], pattern)
                    self.assertEqual(sorted((HERE / "systemd").glob(pattern)), [], pattern)

    def test_there_is_one_builder_workflow_and_it_is_the_declared_one(self):
        self.assertEqual(sorted(p.name for p in WORKFLOWS.glob("*gh-aw-builder*")),
                         ["c1-gh-aw-builder-v1.lock.yml", "c1-gh-aw-builder-v1.md"])
        self.assertEqual(contract.GHAW_BUILDER_WORKFLOW_FILE,
                         "c1-gh-aw-builder-v1.lock.yml")

    def test_the_outbox_path_is_named_once(self):
        # The path still says `c1`; renaming it would be a migration, and a migration is
        # not what this round is. What matters is that it is declared exactly once, so
        # there is one Builder outbox and no second one hiding behind a per-cell name.
        hits = []
        for module in ("c1_ghaw_builder_worker.py", "c1_execution_contract.py",
                       "c1_worker.py"):
            for line in (HERE / module).read_text(encoding="utf-8").splitlines():
                if (line.startswith("OUTBOX_DB")
                        and "outbox-ghaw-builder.db" in line):
                    hits.append((module, line.strip()))
        self.assertEqual(hits, [("c1_ghaw_builder_worker.py",
                                 'OUTBOX_DB = "/var/lib/go-runtime-c1/'
                                 'outbox-ghaw-builder.db"')])


# =============================================================== G
class G_OneWorkerEveryCell(Case):
    """One worker, one kind, twelve owners."""

    def test_the_worker_claims_a_task_of_each_cell(self):
        for cell in ("C1", "C2", "C12"):
            self.enqueue(cell, external_task_id="T-%s" % cell, key="k-%s" % cell)
        owners, cursor = [], 0
        for _ in range(3):
            claimed, cursor = self.claim_for(cursor=cursor)
            self.assertIsNotNone(claimed)
            owners.append(claimed.owner_c)
        self.assertEqual(sorted(owners), ["C1", "C12", "C2"])

    def test_one_tick_claims_at_most_one_task(self):
        for cell in ("C1", "C2"):
            self.enqueue(cell, external_task_id="T-%s" % cell, key="k-%s" % cell)
        claimed, _ = self.claim_for()
        self.assertIsNotNone(claimed)
        remaining = [task for task in self.runtime.tasks.values() if task.status == "QUEUED"]
        self.assertEqual(len(remaining), 1)

    def test_the_control_only_cells_are_never_claimed(self):
        # A C13/C14 task in the queue is what a mis-issued enqueue would look like. The
        # worker never even asks those cells, so such a task is simply never picked up.
        for cell in ("C13", "C14"):
            self.runtime.enqueue(cell, contract.GHAW_BUILDER_KIND,
                                 {"schema_version": 1, "cell_id": cell,
                                  "external_task_id": "%s-TASK" % cell},
                                 idempotency_key="raw-%s" % cell)
        claimed, _ = self.claim_for()
        self.assertIsNone(claimed)
        self.assertEqual(ghaw.CLAIM_OWNER_CS, contract.BUILDER_OWNER_CS)

    def test_the_loop_refuses_a_control_only_claim_even_if_one_arrives(self):
        # The layer below the claim filter: if a C13 task were ever handed to this worker
        # anyway, the loop refuses it before anything is registered or dispatched.
        class FakeClaim:
            task_id = GOLDEN_TASK
            attempts = 1
            kind = contract.GHAW_BUILDER_KIND
            payload = {"schema_version": 1, "cell_id": "C13",
                       "external_task_id": "C13-TASK", "objective": "o", "scope": "s"}

            def __init__(self, owner_c):
                self.owner_c = owner_c

        for cell in ("C13", "C14"):
            with self.subTest(cell=cell):
                outcome = loop_mod.advance(self.outbox, self.runtime, FakeClaim(cell),
                                           worker_id=WORKER_ID, client=boundary
                                           .GhawSealingTransport(),
                                           claimable_kinds=ghaw.CLAIM_KINDS)
                self.assertEqual(outcome["action"], "NOT_A_C1_TASK")
                self.assertEqual(outcome["reason"], "OWNER_C_MISMATCH")
        self.assertEqual(self.outbox.unfinished(limit=10), [])


# =============================================================== H
class H_SchedulingIsNotIdentity(unittest.TestCase):
    """Where a scan begins is convenience; it must not reach the identity."""

    def test_the_scan_order_cannot_change_the_execution_identity(self):
        payload = builder_payload("C12", external_task_id="C12-SCHED")
        spec = contract.task_spec(contract.GHAW_BUILDER_KIND, payload)
        identities = set()
        for cursor in (0, 1, 7, 11, 12):
            runtime = harness.RuntimeDouble(harness.Clock())
            runtime.enqueue("C12", contract.GHAW_BUILDER_KIND, payload,
                            idempotency_key="k-sched", max_attempts=1)
            claimed, _ = worker.claim_across_owners(
                runtime, worker_id=WORKER_ID, lease_s=LEASE_S,
                claim_kinds=ghaw.CLAIM_KINDS, claim_owner_cs=ghaw.CLAIM_OWNER_CS,
                cursor=cursor)
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.owner_c, "C12")
            identities.add(contract.execution_request_id(claimed.task_id, claimed.attempts,
                                                         spec))
        self.assertEqual(len(identities), 1)

    def test_the_cursor_is_a_plain_integer_and_nothing_is_persisted_for_it(self):
        source = (HERE / "c1_worker.py").read_text(encoding="utf-8")
        self.assertIn("owner_cursor = 0", source)
        # No table, no file, no column: a durable cursor would be durable state that
        # decides nothing, which is exactly what this channel refuses to add.
        for forbidden in ("cursor", "round_robin"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, (HERE / "c1_dispatch_outbox.py")
                                 .read_text(encoding="utf-8"))


# =============================================================== I
class I_C12RestartKeepsExactlyOnce(Case):
    """The single-executor restart proof, run for a cell other than C1."""

    def test_a_c12_execution_resumes_after_a_restart_without_a_second_dispatch(self):
        payload = builder_payload("C12", external_task_id="C12-RESTART")
        transport = boundary.GhawSealingTransport(hold_ticks=2)
        task_id = self.runtime.enqueue("C12", contract.GHAW_BUILDER_KIND, payload,
                                       idempotency_key="k-restart", max_attempts=1)
        claimed, _ = self.claim_for()
        first = loop_mod.advance(self.outbox, self.runtime, claimed, worker_id=WORKER_ID,
                                 client=transport, claimable_kinds=ghaw.CLAIM_KINDS)
        self.assertEqual(first["state"], "RUNNING")
        request_id = first["execution_request_id"]
        self.assertEqual(transport.dispatch_calls, 1)

        # The process dies. A brand-new outbox object over the same file, and a brand-new
        # worker, are the whole of the restart: nothing else survives.
        self.outbox.close()
        revived = outbox_mod.DispatchOutbox(str(Path(self._tmp.name) / "outbox.db"))
        self.addCleanup(revived.close)
        for _ in range(4):
            outcome = loop_mod.resume(revived, self.runtime, task_id, claimed.attempts,
                                      worker_id=WORKER_ID, client=transport,
                                      claimable_kinds=ghaw.CLAIM_KINDS)
            if outcome["action"] in ("COMPLETED", "ALREADY_COMPLETED"):
                break

        self.assertEqual(outcome["action"], "COMPLETED")
        self.assertEqual(outcome["execution_request_id"], request_id)
        self.assertEqual(transport.dispatch_calls, 1, "a restart must not dispatch again")
        self.assertEqual(revived.snapshot(request_id)["dispatches_sent"], 1)
        self.assertEqual(self.runtime.status_of(task_id), "SUCCEEDED")
        completed = [row for row in self.runtime.evidence
                     if row["event_type"] == "TASK_COMPLETED" and row["task_id"] == task_id]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["c_id"], "C12")


# =============================================================== J
class J_FailureReturnsToItsOwnCell(Case):
    """A failure is reported to the cell that owns the task, and to no one else."""

    def test_a_failed_c7_run_is_reported_to_c7(self):
        payload = builder_payload("C7", external_task_id="C7-FAIL")
        task_id = self.runtime.enqueue("C7", contract.GHAW_BUILDER_KIND, payload,
                                       idempotency_key="k-fail", max_attempts=1)
        c1_id = self.enqueue("C1", external_task_id="C1-QUIET", key="k-quiet-c1")
        c8_id = self.enqueue("C8", external_task_id="C8-QUIET", key="k-quiet-c8")

        # C7 sits at index 6, so a scan starting there reaches it before the C1 and C8
        # tasks that are also queued - which is the point: one worker, twelve cells, and
        # the cell a task belongs to decides which one is claimed, not where the scan
        # happened to begin.
        claimed, _ = self.claim_for(cursor=contract.BUILDER_OWNER_CS.index("C7"))
        self.assertEqual(claimed.owner_c, "C7")
        outcome = loop_mod.advance(self.outbox, self.runtime, claimed, worker_id=WORKER_ID,
                                   client=FailingRunTransport(),
                                   claimable_kinds=ghaw.CLAIM_KINDS)
        self.assertEqual(outcome["action"], "RUN_FAILED")

        self.assertEqual(self.runtime.status_of(task_id), "FAILED")
        completed = [row for row in self.runtime.evidence
                     if row["event_type"] == "TASK_COMPLETED" and row["task_id"] == task_id]
        self.assertEqual(len(completed), 1)
        # The cell the Runtime was told is the task's own. One worker completing for twelve
        # cells makes this the only thing standing between a C7 failure and a C1 record.
        self.assertEqual(completed[0]["c_id"], "C7")
        self.assertFalse(completed[0]["body"]["result"]["authorizes_any_action"])

        # And the other cells' queued work is untouched.
        self.assertEqual(self.runtime.status_of(c1_id), "QUEUED")
        self.assertEqual(self.runtime.status_of(c8_id), "QUEUED")


# =============================================================== K
class K_TheControlOnlyCellsAreRefusedEverywhere(unittest.TestCase):
    """Three independent refusals, and the workflow is one of them."""

    def test_the_workflow_states_the_range_and_refuses_its_own(self):
        source = (WORKFLOWS / "c1-gh-aw-builder-v1.md").read_text(encoding="utf-8")
        self.assertIn('tuple("C%d" % n for n in range(1, 13))', source)
        for token in ("TASK_PAYLOAD_CELL_NOT_OWNED_BY_BUILDER_EXECUTOR",
                      "OWNER_C_NOT_OWNED_BY_BUILDER_EXECUTOR",
                      "OWNER_C_DOES_NOT_MATCH_TASK_PAYLOAD",
                      "OWNER_C_MISSING"):
            with self.subTest(token=token):
                self.assertIn(token, source)

    def test_the_workflow_does_not_learn_the_range_from_the_contract(self):
        # The workflow runs in its own checkout; it cannot import the channel, so it must
        # not pretend to. Its range is its own, and `test_c1_ghaw_registration` exercises
        # the gate that enforces it.
        source = (WORKFLOWS / "c1-gh-aw-builder-v1.md").read_text(encoding="utf-8")
        self.assertNotIn("c1_execution_contract", source)
        self.assertNotIn("BUILDER_OWNER_CS", source)

    def test_the_worker_the_validator_and_the_workflow_all_agree(self):
        self.assertEqual(ghaw.CLAIM_OWNER_CS, contract.BUILDER_OWNER_CS)
        self.assertNotIn("C13", contract.BUILDER_OWNER_CS)
        self.assertNotIn("C14", contract.BUILDER_OWNER_CS)
        lock = (WORKFLOWS / "c1-gh-aw-builder-v1.lock.yml").read_text(encoding="utf-8")
        self.assertIn("TASK_PAYLOAD_CELL_NOT_OWNED_BY_BUILDER_EXECUTOR", lock)


# =============================================================== O
class O_TheSolutionLeakGateIsABypass(unittest.TestCase):
    """U6: an interface that is present, honest, and enforced by nothing yet."""

    def test_the_default_mode_passes_without_reviewing_anything(self):
        record = gate.evaluate(objective="objective", scope="scope")
        self.assertEqual(record["decision"], "PASS")
        self.assertEqual(record["reason"], "GATE_DISABLED")
        self.assertIs(record["enabled"], False)
        self.assertIs(record["reviewed"], False)
        self.assertIs(record["model_called"], False)
        self.assertEqual(record["calls"], 0)

    def test_a_disabled_gate_is_never_described_as_a_review(self):
        # `PASS` from a disabled gate means "not blocking". It must never be readable as
        # "a checker looked at this and approved it", which is what `reviewed` is for.
        record = gate.evaluate(objective="objective", scope="scope")
        self.assertFalse(record["reviewed"] and record["decision"] == "PASS")

    def test_enabling_the_switch_without_a_checker_refuses(self):
        original = gate.SOLUTION_LEAK_GATE_ENABLED
        gate.SOLUTION_LEAK_GATE_ENABLED = True
        try:
            with self.assertRaises(contract.Refused) as raised:
                gate.evaluate(objective="objective", scope="scope")
            self.assertEqual(raised.exception.reason,
                             "SOLUTION_LEAK_GATE_NOT_IMPLEMENTED")
            self.assertEqual(gate.describe()["mode"], "UNIMPLEMENTED")
            self.assertEqual(gate.describe()["decision"], "REFUSED")
        finally:
            gate.SOLUTION_LEAK_GATE_ENABLED = original

    def test_the_switch_ships_off(self):
        self.assertIs(gate.SOLUTION_LEAK_GATE_ENABLED, False)
        self.assertEqual(gate.describe()["mode"], "BYPASS")
        self.assertEqual(gate.describe()["enforcement"], "DEFERRED")

    def test_the_ingress_composes_the_plan_around_the_gate_record(self):
        plan = ingress.plan_ingress(load_issue(79), environ={})
        record = plan["solution_leak_gate"]
        self.assertEqual(record["reason"], "GATE_DISABLED")
        self.assertIs(record["reviewed"], False)
        self.assertEqual(record["calls"], 0)

    def test_this_round_adds_no_model_dependency(self):
        source = (HERE / "c1_solution_leak_gate.py").read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        for forbidden in ("import deepseek", "import openai", "import requests",
                          "urllib", "http.client", "socket", "sdk"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, code.split('"""')[-1])


# =============================================================== P
class P_TheIssuePathCarriesTheCell(Case):
    """One consumer, twelve cells, one Runtime call per issue."""

    def test_each_cells_issue_becomes_that_cells_task(self):
        for cell in ("C01", "C02", "C09", "C12"):
            issue = load_issue(79)
            issue["title"] = "%s · V70-R3-%s-01 · a bounded engineering task" % (cell, cell)
            with self.subTest(cell=cell):
                plan = ingress.plan_ingress(issue, environ={})
                call = plan["would_enqueue"]
                canonical = contract.canonical_cell_id(cell)
                self.assertEqual(call["owner_c"], canonical)
                self.assertEqual(call["payload"]["cell_id"], canonical)
                self.assertEqual(call["kind"], contract.GHAW_BUILDER_KIND)
                self.assertTrue(call["idempotency_key"].endswith(":" + canonical
                                                                 + ":V70-R3-%s-01" % cell))

    def test_enabling_the_ingress_enqueues_under_the_issues_own_cell(self):
        issue = load_issue(79)
        issue["title"] = "C12 · V70-R3-C12-01 · a bounded engineering task"
        result = ingress.ingest(issue, runtime=self.runtime,
                                environ={ingress.INGRESS_ENABLED_ENV: "true"})
        self.assertTrue(result["enqueued"])
        owner = self.runtime.tasks[result["runtime_task_id"]].owner_c
        self.assertEqual(owner, "C12")

    def test_the_control_only_cells_never_reach_the_runtime(self):
        for cell in ("C13", "C14"):
            issue = load_issue(79)
            issue["title"] = "%s · V70-R3-%s-01 · not a builder task" % (cell, cell)
            with self.subTest(cell=cell):
                with self.assertRaises(contract.Refused):
                    ingress.ingest(issue, runtime=self.runtime,
                                   environ={ingress.INGRESS_ENABLED_ENV: "true"})
        self.assertEqual(self.runtime.tasks, {})


if __name__ == "__main__":
    unittest.main()
