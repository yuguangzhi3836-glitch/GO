"""Durable C1 dispatch outbox: the exactly-once model for Runtime -> GitHub -> Runtime.

The realistic failure this exists for:

  the Runtime (or the Agent, or the network, or the GitHub API) loses track of a
  dispatch that may or may not have started. A naive retry sends a SECOND dispatch
  for the same Runtime task, which spends money on a second real model call.

The model here, deliberately without Redis, queues or distributed locks:

  1. the execution identity is derived, never chosen:
         execution_request_id = sha256(canonical(task binding + fixed binding))
  2. the intent is written durably BEFORE anything is sent;
  3. at most ONE dispatch is ever sent per execution_request_id - enforced by the
     stored counter, not by caller discipline;
  4. an ambiguous HTTP outcome is recorded as ambiguous and resolved by LOOKUP
     (the run's deterministic name), never by a second POST;
  5. a terminal result is immutable: identical bytes are idempotent, different
     bytes fail closed;
  6. completion reuses the Runtime's own attempt fencing - this module stores the
     attempt to pass as expected_attempt and never touches Runtime state itself;
  7. an execution that can never produce a result is SETTLED rather than retried: the
     Runtime refused its completion (ABANDONED), or the run itself finished without
     succeeding (RUN_FAILED, whose no-result outcome is reported to the Runtime by
     `c1_result_pull.fail_after_pull`). Either way `unfinished()` stops reporting it, so
     a settled identity can never hold the worker forever - and neither state is a route
     back to a second POST.

This module performs no network I/O and holds no credential. `send` and `find_run`
are injected by the caller (the Agent), which is what makes the timeout and
ambiguous-outcome paths testable offline.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from c1_execution_contract import (
    KIND,
    OWNER_C,
    Refused,
    build_dispatch_request,
    canonical,
    execution_request_id,
    run_identity_name,
    sha256_hex,
    validate_result,
)

# Outbox states
INTENT = "INTENT"                        # intent recorded durably, nothing sent yet
DISPATCH_AMBIGUOUS = "DISPATCH_AMBIGUOUS"  # a POST may have landed; lookup required
RUN_BOUND = "RUN_BOUND"                  # the GitHub run id is known
RESULT_SEALED = "RESULT_SEALED"          # a terminal result is stored, immutable
COMPLETED = "COMPLETED"                  # Runtime.complete() done
# The Runtime has refused this identity's completion, and always will: its fence wants
# `status='RUNNING' AND lease_owner=this worker AND attempts==expected_attempt AND
# lease_until>now`, and a lease that has expired can never be renewed while a requeued
# task comes back as the NEXT attempt. Retrying is pointless, so the identity is
# settled instead of left in flight - otherwise it would block the worker forever.
ABANDONED = "ABANDONED"
# The GitHub run finished without succeeding. No artifact from such a run can be trusted,
# so no sealed result can ever exist for this identity either - and leaving it in flight is
# what made the worker renew its lease forever and never claim anything again. It is
# settled for the same reason ABANDONED is, but it records a different fact: ABANDONED
# means "the Runtime refused this identity", RUN_FAILED means "the execution ran and
# failed". Both are final.
RUN_FAILED = "RUN_FAILED"

IN_FLIGHT_STATES = (INTENT, DISPATCH_AMBIGUOUS, RUN_BOUND)
# Everything an identity can end as (ABANDONED keeps its own branches, so it is not listed
# here even though it is equally final).
TERMINAL_STATES = (RESULT_SEALED, COMPLETED, RUN_FAILED)
# Everything that still holds work, including a sealed result whose completion was
# interrupted: that is exactly the case a restart has to pick up. Both settled states are
# deliberately absent - a settled identity must never block the worker again.
UNFINISHED_STATES = (INTENT, DISPATCH_AMBIGUOUS, RUN_BOUND, RESULT_SEALED)
# Nothing may be sent, sealed or adopted for an identity in one of these.
SETTLED_STATES = (ABANDONED, RUN_FAILED)

# The outward-facing dispatch_status vocabulary. The internal state names are kept
# because they say exactly what the outbox actually knows (in particular the
# difference between "we are not in flight" and "we may have sent something and do
# not know"); this projection is the stable contract callers read.
DISPATCH_STATUS = {
    INTENT: "CREATED",
    DISPATCH_AMBIGUOUS: "DISPATCHED",
    RUN_BOUND: "RUNNING",
    RESULT_SEALED: "COMPLETED",
    COMPLETED: "COMPLETED",
    ABANDONED: "FAILED",
    RUN_FAILED: "FAILED",
}
DISPATCH_STATUS_VALUES = ("CREATED", "DISPATCHED", "RUNNING", "COMPLETED", "FAILED")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS c1_dispatch (
    execution_request_id TEXT PRIMARY KEY,
    runtime_task_id      TEXT NOT NULL,
    attempt              INTEGER NOT NULL,
    state                TEXT NOT NULL,
    dispatches_sent      INTEGER NOT NULL DEFAULT 0,
    github_run_id        INTEGER,
    github_run_attempt   INTEGER,
    result_json          TEXT,
    result_sha256        TEXT,
    reused_from          TEXT,
    abandon_reason       TEXT,
    failure_reason       TEXT,
    request_json         TEXT,
    updated_at           TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DispatchOutbox:
    def __init__(self, db_path: str, clock=_now, *, read_only=False):
        self.db_path = str(db_path)
        self.clock = clock
        if read_only:
            from pathlib import Path
            self._db = sqlite3.connect(Path(self.db_path).resolve().as_uri() + "?mode=ro",
                                       uri=True, isolation_level=None)
            self._db.row_factory = sqlite3.Row
            return
        self._db = sqlite3.connect(self.db_path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Add columns introduced after an outbox file may already exist on disk."""
        present = {row["name"] for row in self._db.execute("PRAGMA table_info(c1_dispatch)")}
        if "reused_from" not in present:
            self._db.execute("ALTER TABLE c1_dispatch ADD COLUMN reused_from TEXT")
        if "abandon_reason" not in present:
            self._db.execute("ALTER TABLE c1_dispatch ADD COLUMN abandon_reason TEXT")
        if "failure_reason" not in present:
            # Rows written before the failed-run settlement have no failure reason. They
            # are not broken: the column is only ever read for a RUN_FAILED row, and none
            # can predate it. Nothing is rewritten here.
            self._db.execute("ALTER TABLE c1_dispatch ADD COLUMN failure_reason TEXT")
        if "request_json" not in present:
            # Rows written before the real-task contract have no stored request. They are
            # not broken: `stored_request()` returns None for them and the caller falls
            # back to the smoke binding, which is exactly the identity they were created
            # from. Nothing is rewritten here.
            self._db.execute("ALTER TABLE c1_dispatch ADD COLUMN request_json TEXT")

    def close(self):
        self._db.close()

    # ------------------------------------------------------------------ helpers
    def _row(self, request_id):
        return self._db.execute(
            "SELECT * FROM c1_dispatch WHERE execution_request_id=?", (request_id,)
        ).fetchone()

    def _update(self, request_id, **columns):
        sets = ", ".join("%s=?" % name for name in columns)
        values = list(columns.values()) + [self.clock(), request_id]
        self._db.execute(
            "UPDATE c1_dispatch SET %s, updated_at=? WHERE execution_request_id=?" % sets, values
        )

    def _refuse_if_settled(self, request_id) -> None:
        """A settled identity is final: nothing may be sent, sealed or adopted for it.

        This is the guard that keeps `abandon` and `record_run_failed` from ever becoming
        a route back to a second dispatch.
        """
        row = self._row(request_id)
        if row is not None and row["state"] in SETTLED_STATES:
            raise Refused("EXECUTION_ABANDONED" if row["state"] == ABANDONED
                          else "EXECUTION_RUN_FAILED")

    # --------------------------------------------------------------- registration
    def register(self, runtime_task_id, attempt, *, request=None) -> dict:
        """Record the intent and report what the caller is allowed to do next.

        The intent row is committed before returning, so a crash after this call can
        never lose the fact that this execution identity exists - nor, for a real task,
        the payload the identity was derived from. Storing the request is what lets
        `resume()` rebuild an execution identity without asking the Runtime, which
        exposes no way to read a task back.

        With no `request` this derives the smoke request, which is the pre-existing
        behaviour and stays byte-identical.
        """
        if request is None:
            request = build_dispatch_request(runtime_task_id, attempt)
        request_id = request["execution_request_id"]
        row = self._row(request_id)
        if row is None:
            self._db.execute(
                "INSERT INTO c1_dispatch (execution_request_id, runtime_task_id, attempt,"
                " state, dispatches_sent, request_json, updated_at) VALUES (?,?,?,?,0,?,?)",
                (request_id, runtime_task_id, attempt, INTENT, canonical(request),
                 self.clock()),
            )
            return {"action": "DISPATCH", "request": request}
        self._confirm_stored_request(row, request)
        return {"action": self.next_action(request_id), "request": request,
                "state": row["state"]}

    def _confirm_stored_request(self, row, request) -> None:
        """Backfill a pre-contract row; refuse a request that contradicts a stored one.

        The primary key already commits the identity, so a contradiction can only mean a
        caller derived a different request for the same id. That is never resolved by
        silently preferring one of the two.
        """
        stored = row["request_json"]
        if stored is None:
            self._update(row["execution_request_id"], request_json=canonical(request))
            return
        if stored != canonical(request):
            raise Refused("STORED_REQUEST_DOES_NOT_MATCH")

    def stored_request(self, runtime_task_id, attempt):
        """The exact request this identity was born with, or None for a legacy row.

        This is how the resume leg knows what a task actually asked for: the Runtime
        kernel exposes no way to read a task back, so the outbox - which already
        remembers work in progress - remembers this too. A None means the row predates
        the real-task contract, and the caller's smoke fallback reproduces exactly the
        identity such a row was created from.
        """
        import json

        row = self._db.execute(
            "SELECT request_json FROM c1_dispatch WHERE runtime_task_id=? AND attempt=?"
            " AND request_json IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
            (runtime_task_id, attempt),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["request_json"])

    def task_kind_for(self, request_id) -> str:
        """The task kind this execution identity belongs to.

        Read from the request stored beside the row, so a sealed result is validated
        against the acceptance rule of its OWN task class - the smoke's fixed literal or a
        real task's "any non-empty answer". A row written before the real-task contract
        has no stored request and is a smoke row by construction.
        """
        row = self._row(request_id)
        if row is None or row["request_json"] is None:
            return KIND
        import json

        return json.loads(row["request_json"]).get("task_kind", KIND)

    def next_action(self, request_id) -> str:
        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        state = row["state"]
        if state == ABANDONED:
            return ABANDONED
        if state == RUN_FAILED:
            # Settled: there is no result to reuse and nothing may be dispatched.
            return RUN_FAILED
        if state in TERMINAL_STATES:
            return "REUSE_TERMINAL"
        if state == INTENT:
            return "DISPATCH" if row["dispatches_sent"] == 0 else "LOOKUP_RUN"
        if state == DISPATCH_AMBIGUOUS:
            return "LOOKUP_RUN"
        if state == RUN_BOUND:
            return "AWAIT_RESULT"
        raise Refused("OUTBOX_STATE_UNKNOWN")

    # ------------------------------------------------------------------- resume
    def unfinished(self, *, limit: int = 10) -> list[dict]:
        """Executions still holding work, oldest first. What a restart must pick up.

        `COMPLETED` is excluded because the Runtime has already been told the answer,
        and `ABANDONED` because nothing can ever be done with it again. Ordered
        oldest-first so a backlog drains in the order it was created - which matters
        because each of these identities is a real execution that may already have been
        paid for.
        """
        placeholders = ",".join("?" for _ in UNFINISHED_STATES)
        rows = self._db.execute(
            "SELECT * FROM c1_dispatch WHERE state IN (%s)"
            " ORDER BY updated_at ASC, execution_request_id ASC LIMIT ?" % placeholders,
            (*UNFINISHED_STATES, limit),
        ).fetchall()
        return [{"execution_request_id": r["execution_request_id"],
                 "runtime_task_id": r["runtime_task_id"], "attempt": r["attempt"],
                 "state": r["state"], "dispatches_sent": r["dispatches_sent"],
                 "github_run_id": r["github_run_id"]} for r in rows]

    def abandon(self, request_id, reason) -> str:
        """Settle an identity the Runtime will never accept a completion for.

        Called only after the Runtime has itself refused one. The fence conditions are
        all unrecoverable, so retrying is pointless - and leaving the row unfinished
        would keep the caller from ever doing anything else, which is the failure this
        whole module exists to avoid.

        It cannot become a route back to a second dispatch: a settled row is never
        selected by `unfinished()`, `record_dispatch_sent` refuses it outright, and
        `next_action` reports ABANDONED rather than DISPATCH or LOOKUP_RUN. A result
        already sealed for it stays visible to `terminal_for_task`, so if the Runtime
        later hands the same task out as a new attempt, that attempt still adopts the
        answer instead of paying for a new one.
        """
        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        if row["state"] == COMPLETED:
            raise Refused("CANNOT_ABANDON_A_COMPLETED_EXECUTION")
        if row["state"] in SETTLED_STATES:
            # Already settled - and a RUN_FAILED must not be rewritten as an abandoned
            # one, because the two record different facts.
            return row["state"]
        self._update(request_id, state=ABANDONED, abandon_reason=str(reason)[:200])
        return ABANDONED

    def record_run_failed(self, request_id, reason, github_run_id=None) -> str:
        """Settle an identity whose GitHub run finished without succeeding.

        No artifact from such a run can be trusted, so no sealed result can ever exist for
        this identity. Leaving it in flight is what made the worker renew its lease on
        every tick and never claim anything again - the defect this replaces. Terminal in
        exactly the way `abandon` is, with every route back to a POST closed the same way
        - and it stores no result, so a later attempt of the same Runtime task can never
        adopt a failure as if it were an answer.
        """
        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        if row["state"] == COMPLETED:
            raise Refused("CANNOT_FAIL_A_COMPLETED_EXECUTION")
        if row["state"] in SETTLED_STATES:
            return row["state"]
        self._update(request_id, state=RUN_FAILED, failure_reason=str(reason)[:200],
                     github_run_id=row["github_run_id"] or github_run_id)
        return RUN_FAILED

    def failed_for_task(self, runtime_task_id, *, exclude_request_id=None):
        """A run already settled as failed for this Runtime task, whatever attempt it was.

        The twin of `terminal_for_task`, for the case where there is nothing to adopt. The
        Runtime hands a requeued task out as a NEW attempt, and a new attempt is a new
        execution identity - so without this, a task whose first run failed would be
        dispatched, and paid for, all over again.
        """
        row = self._db.execute(
            "SELECT * FROM c1_dispatch WHERE runtime_task_id=? AND state=?"
            " AND execution_request_id != ? ORDER BY attempt ASC LIMIT 1",
            (runtime_task_id, RUN_FAILED, exclude_request_id or ""),
        ).fetchone()
        if row is None:
            return None
        return {"execution_request_id": row["execution_request_id"],
                "attempt": row["attempt"], "failure_reason": row["failure_reason"]}

    # ------------------------------------------------------------------- dispatch
    def record_dispatch_sent(self, request_id, github_run_id=None) -> None:
        """Record that exactly one dispatch POST has been sent.

        A second call for the same execution identity is refused outright: that is the
        whole point of the counter. Callers that lost the HTTP outcome must resolve it
        with `record_run_lookup`, not by sending again.
        """
        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        self._refuse_if_settled(request_id)
        if row["dispatches_sent"] >= 1:
            raise Refused("SECOND_DISPATCH_FORBIDDEN")
        self._update(request_id, dispatches_sent=row["dispatches_sent"] + 1,
                     state=RUN_BOUND if github_run_id else DISPATCH_AMBIGUOUS,
                     github_run_id=github_run_id)

    def record_run_lookup(self, request_id, github_run_id) -> None:
        """Resolve an unknown or ambiguous outcome by looking the run up by its name."""
        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        self._refuse_if_settled(request_id)
        if row["state"] in TERMINAL_STATES:
            return
        if not isinstance(github_run_id, int) or github_run_id <= 0:
            raise Refused("GITHUB_RUN_ID_INVALID")
        self._update(request_id, github_run_id=github_run_id, state=RUN_BOUND)

    # --------------------------------------------------------------------- result
    def record_result(self, request_id, document, *, runtime_task_id, attempt,
                      validator=None) -> dict:
        """Store a sealed result. Identical bytes are idempotent; different bytes refuse.

        Validation is always performed here and never skipped - what an injected
        `validator` changes is only WHICH acceptance rule applies, never WHETHER one
        does. The default is this channel's own result contract, so every existing
        caller keeps the rule it was proven with; a class whose result is not that
        document (the C13/C14 review envelope) supplies its own validator instead of
        having its result dressed up as one this contract would accept. It is called
        with the same arguments and has the same duty: refuse anything that is not a
        valid, correctly-bound, non-authorising result for this exact identity.
        """
        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        self._refuse_if_settled(request_id)
        # Validated against this identity's own task class, never a default: a real task's
        # result must not be judged by the smoke's fixed-literal rule, and the smoke's must
        # not be relaxed by the real rule.
        task_kind = self.task_kind_for(request_id)
        if validator is None:
            validate_result(document, runtime_task_id=runtime_task_id, attempt=attempt,
                            execution_request_id_=request_id, task_kind=task_kind)
        else:
            validator(document, runtime_task_id=runtime_task_id, attempt=attempt,
                      execution_request_id_=request_id, task_kind=task_kind)
        payload = canonical(document)
        digest = sha256_hex(payload)
        if row["result_json"] is not None:
            if row["result_sha256"] == digest and row["result_json"] == payload:
                return document
            raise Refused("CONFLICTING_RESULT_BYTES")
        self._update(request_id, result_json=payload, result_sha256=digest,
                     state=RESULT_SEALED)
        return document

    def terminal_result(self, request_id):
        row = self._row(request_id)
        if row is None or row["result_json"] is None:
            return None
        import json
        return json.loads(row["result_json"])

    def mark_completed(self, request_id) -> None:
        """Only a sealed, validated result may be handed to Runtime.complete()."""
        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        self._refuse_if_settled(request_id)
        if row["state"] == COMPLETED:
            return
        if row["state"] != RESULT_SEALED:
            raise Refused("COMPLETION_WITHOUT_A_SEALED_RESULT")
        self._update(request_id, state=COMPLETED)

    # -------------------------------------------------- reuse across attempts
    def terminal_for_task(self, runtime_task_id, *, exclude_request_id=None):
        """A result already sealed for this Runtime task, whatever attempt produced it.

        This is the guard against paying twice for one task: an attempt that loses its
        lease is requeued by the Runtime as a NEW attempt, and a new attempt is a new
        execution identity, so nothing else would stop a second real model call.
        """
        row = self._db.execute(
            "SELECT * FROM c1_dispatch WHERE runtime_task_id=? AND result_json IS NOT NULL"
            " AND execution_request_id != ? ORDER BY attempt ASC LIMIT 1",
            (runtime_task_id, exclude_request_id or ""),
        ).fetchone()
        if row is None:
            return None
        import json
        return {"execution_request_id": row["execution_request_id"],
                "attempt": row["attempt"],
                "result": json.loads(row["result_json"]),
                "result_json": row["result_json"],
                "result_sha256": row["result_sha256"]}

    def adopt_terminal_result(self, request_id, source) -> None:
        """Answer this execution identity with an earlier attempt's sealed result.

        The bytes are copied unchanged - a result is never rewritten to claim an attempt
        that did not produce it - and the identity it came from is recorded beside them,
        so the reuse is auditable rather than invisible.
        """
        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        self._refuse_if_settled(request_id)
        if row["result_json"] is not None:
            if row["result_json"] == source["result_json"]:
                return
            raise Refused("CONFLICTING_RESULT_BYTES")
        self._update(request_id, result_json=source["result_json"],
                     result_sha256=source["result_sha256"], state=RESULT_SEALED,
                     reused_from=source["execution_request_id"])

    # ------------------------------------------------------------- introspection
    def completion_binding(self, request_id) -> dict:
        """What the caller must pass to Runtime.complete(): cell, task id, exact attempt.

        The owner cell is part of it and is read from the request this identity was
        registered with - never from the caller. One Builder executor serves twelve
        cells, so "which cell does this completion belong to" is a fact about the
        execution, and a caller that guessed it would, at best, be told the task does not
        exist and, at worst, complete the wrong cell's task if it ever guessed a real id.
        The outbox already stores the request verbatim, so the answer is already here.
        """
        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        if row["state"] != RESULT_SEALED:
            raise Refused("COMPLETION_WITHOUT_A_SEALED_RESULT")
        return {"owner_c": self.owner_c_for(request_id),
                "runtime_task_id": row["runtime_task_id"],
                "expected_attempt": row["attempt"]}

    def owner_c_for(self, request_id) -> str:
        """The owner cell of this execution identity, from the stored request.

        A row written before the real-task contract has no stored request and is a C1
        smoke row by construction, which is exactly what the fallback reproduces - the
        same rule `stored_request()` and `task_kind_for()` already follow.
        """
        import json

        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        stored = row["request_json"]
        if stored is None:
            return OWNER_C
        return json.loads(stored).get("owner_c", OWNER_C)

    def snapshot(self, request_id) -> dict:
        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        return {k: row[k] for k in row.keys()}

    def dispatch_status(self, request_id) -> str:
        """The outward-facing status: CREATED / DISPATCHED / RUNNING / COMPLETED / FAILED.

        A sealed result that was not accepted reports FAILED; a sealed one that was
        accepted reports COMPLETED. Both are terminal, and neither permits a second
        dispatch or a second model call.
        """
        snapshot = self.snapshot(request_id)
        state = snapshot["state"]
        if state in TERMINAL_STATES:
            document = self.terminal_result(request_id)
            if document is not None and not document.get("accepted", False):
                return "FAILED"
        return DISPATCH_STATUS[state]


def drive_once(outbox: DispatchOutbox, runtime_task_id, attempt, *, send, find_run,
               request=None) -> dict:
    """One bounded advance of the outbox. Returns the action taken and why.

    `send(request) -> ("sent", run_id) | ("sent", None) | ("ambiguous", reason)`
    `find_run(run_name) -> run_id | None`

    The safety property is structural: whichever branch runs, `send` is called at most
    once per execution identity, and an ambiguous outcome routes to lookup - never to a
    second POST.

    `request` is the already-formed dispatch request for this execution identity. It is
    optional only so that the pre-contract smoke path keeps working unchanged: when it is
    absent the outbox is asked what this identity was registered with, and the smoke
    binding is derived only if the row predates that.
    """
    if request is None:
        request = outbox.stored_request(runtime_task_id, attempt) or \
            build_dispatch_request(runtime_task_id, attempt)
    request_id = request["execution_request_id"]
    registered = outbox.register(runtime_task_id, attempt, request=request)
    action = registered["action"]

    if action == "REUSE_TERMINAL":
        return {"action": "REUSE_TERMINAL", "execution_request_id": request_id,
                "result": outbox.terminal_result(request_id)}

    if action == ABANDONED:
        # Settled as uncompletable. `send` is not called, and never will be for this
        # execution identity.
        return {"action": ABANDONED, "execution_request_id": request_id}

    if action == RUN_FAILED:
        # Settled: the run finished without succeeding. `send` is not called, and never
        # will be for this execution identity.
        return {"action": RUN_FAILED, "execution_request_id": request_id}

    if action == "DISPATCH":
        outcome = send(request)
        kind = outcome[0]
        if kind == "sent":
            run_id = outcome[1] if len(outcome) > 1 else None
            outbox.record_dispatch_sent(request_id, github_run_id=run_id)
            return {"action": "DISPATCHED", "execution_request_id": request_id,
                    "github_run_id": run_id,
                    "resolved": run_id is not None}
        if kind == "ambiguous":
            # The POST may or may not have landed. Do NOT send again.
            outbox.record_dispatch_sent(request_id, github_run_id=None)
            return {"action": "DISPATCH_AMBIGUOUS", "execution_request_id": request_id,
                    "reason": outcome[1] if len(outcome) > 1 else "unknown"}
        raise Refused("UNKNOWN_SEND_OUTCOME")

    if action == "LOOKUP_RUN":
        # The name carries the execution's own cell. `run_identity_name` defaults to C1, and
        # that default is right only for a C1 row: left unstated here, a C12 execution looks
        # for "C1 <task> <attempt> <request id>" while its run is named "C12 <task> ...", so
        # the lookup never matches and the dispatch stays ambiguous for ever - renewing its
        # lease each tick, never binding its run, never reaching the result leg. The cell
        # comes from the request this identity was registered with, the same source
        # `c1_result_pull` reads, so both halves of the leg agree about the name.
        run_id = find_run(run_identity_name(runtime_task_id, attempt, request_id,
                                            request.get("owner_c", OWNER_C)))
        if run_id is None:
            return {"action": "LOOKUP_RUN_NOT_FOUND", "execution_request_id": request_id}
        outbox.record_run_lookup(request_id, run_id)
        return {"action": "RUN_BOUND", "execution_request_id": request_id,
                "github_run_id": run_id}

    if action == "AWAIT_RESULT":
        return {"action": "AWAIT_RESULT", "execution_request_id": request_id}

    raise Refused("UNKNOWN_OUTBOX_ACTION")
