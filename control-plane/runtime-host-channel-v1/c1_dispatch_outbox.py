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
     attempt to pass as expected_attempt and never touches Runtime state itself.

This module performs no network I/O and holds no credential. `send` and `find_run`
are injected by the caller (the Agent), which is what makes the timeout and
ambiguous-outcome paths testable offline.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from c1_execution_contract import (
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

IN_FLIGHT_STATES = (INTENT, DISPATCH_AMBIGUOUS, RUN_BOUND)
TERMINAL_STATES = (RESULT_SEALED, COMPLETED)

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
    updated_at           TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DispatchOutbox:
    def __init__(self, db_path: str, clock=_now):
        self.db_path = str(db_path)
        self.clock = clock
        self._db = sqlite3.connect(self.db_path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(_SCHEMA)

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

    # --------------------------------------------------------------- registration
    def register(self, runtime_task_id, attempt) -> dict:
        """Record the intent and report what the caller is allowed to do next.

        The intent row is committed before returning, so a crash after this call can
        never lose the fact that this execution identity exists.
        """
        request = build_dispatch_request(runtime_task_id, attempt)
        request_id = request["execution_request_id"]
        row = self._row(request_id)
        if row is None:
            self._db.execute(
                "INSERT INTO c1_dispatch (execution_request_id, runtime_task_id, attempt,"
                " state, dispatches_sent, updated_at) VALUES (?,?,?,?,0,?)",
                (request_id, runtime_task_id, attempt, INTENT, self.clock()),
            )
            return {"action": "DISPATCH", "request": request}
        return {"action": self.next_action(request_id), "request": request,
                "state": row["state"]}

    def next_action(self, request_id) -> str:
        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        state = row["state"]
        if state in TERMINAL_STATES:
            return "REUSE_TERMINAL"
        if state == INTENT:
            return "DISPATCH" if row["dispatches_sent"] == 0 else "LOOKUP_RUN"
        if state == DISPATCH_AMBIGUOUS:
            return "LOOKUP_RUN"
        if state == RUN_BOUND:
            return "AWAIT_RESULT"
        raise Refused("OUTBOX_STATE_UNKNOWN")

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
        if row["state"] in TERMINAL_STATES:
            return
        if not isinstance(github_run_id, int) or github_run_id <= 0:
            raise Refused("GITHUB_RUN_ID_INVALID")
        self._update(request_id, github_run_id=github_run_id, state=RUN_BOUND)

    # --------------------------------------------------------------------- result
    def record_result(self, request_id, document, *, runtime_task_id, attempt) -> dict:
        """Store a sealed result. Identical bytes are idempotent; different bytes refuse."""
        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        validate_result(document, runtime_task_id=runtime_task_id, attempt=attempt,
                        execution_request_id_=request_id)
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
        if row["state"] == COMPLETED:
            return
        if row["state"] != RESULT_SEALED:
            raise Refused("COMPLETION_WITHOUT_A_SEALED_RESULT")
        self._update(request_id, state=COMPLETED)

    # ------------------------------------------------------------- introspection
    def completion_binding(self, request_id) -> dict:
        """What the caller must pass to Runtime.complete(): task id and exact attempt."""
        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        if row["state"] != RESULT_SEALED:
            raise Refused("COMPLETION_WITHOUT_A_SEALED_RESULT")
        return {"runtime_task_id": row["runtime_task_id"], "expected_attempt": row["attempt"]}

    def snapshot(self, request_id) -> dict:
        row = self._row(request_id)
        if row is None:
            raise Refused("UNKNOWN_EXECUTION_REQUEST_ID")
        return {k: row[k] for k in row.keys()}


def drive_once(outbox: DispatchOutbox, runtime_task_id, attempt, *, send, find_run) -> dict:
    """One bounded advance of the outbox. Returns the action taken and why.

    `send(request) -> ("sent", run_id) | ("sent", None) | ("ambiguous", reason)`
    `find_run(run_name) -> run_id | None`

    The safety property is structural: whichever branch runs, `send` is called at most
    once per execution identity, and an ambiguous outcome routes to lookup - never to a
    second POST.
    """
    request = build_dispatch_request(runtime_task_id, attempt)
    request_id = request["execution_request_id"]
    registered = outbox.register(runtime_task_id, attempt)
    action = registered["action"]

    if action == "REUSE_TERMINAL":
        return {"action": "REUSE_TERMINAL", "execution_request_id": request_id,
                "result": outbox.terminal_result(request_id)}

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
        run_id = find_run(run_identity_name(runtime_task_id, attempt, request_id))
        if run_id is None:
            return {"action": "LOOKUP_RUN_NOT_FOUND", "execution_request_id": request_id}
        outbox.record_run_lookup(request_id, run_id)
        return {"action": "RUN_BOUND", "execution_request_id": request_id,
                "github_run_id": run_id}

    if action == "AWAIT_RESULT":
        return {"action": "AWAIT_RESULT", "execution_request_id": request_id}

    raise Refused("UNKNOWN_OUTBOX_ACTION")
