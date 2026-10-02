"""C01 GitHub Issue -> Persistent Runtime C1 ingress (candidate, shadow by default).

What this is
------------
The Owner's existing entry point is unchanged and is not touched by this module:

    Owner phone ChatGPT -> ChatGPT Codex Connector -> a C01 issue in this repository

This module is the missing last leg of the *new* path only:

    C01 issue -> parse -> validate -> AI_TASK_V1 payload -> Runtime.enqueue()

It is deliberately NOT the old path. It never calls the old C01 session executors,
their runner, or any old C01 workflow: the exact identities this module must not
reach are listed in the accompanying document rather than repeated here, because the
test suite asserts their absence from this file's text (see
`test_c1_issue_ingress.py`, class `TheIngressIsStructurallyBounded`). It imports no
C1 execution module: the only repository interface it uses is `c1_execution_contract`,
which is where the real-task payload, the canonical cell spelling and the idempotency
key already live. There is no second task schema and no second de-duplication system
here.

Disabled by default, and structurally so
----------------------------------------
`plan_ingress()` is the only function that parses an issue to a Runtime call, and it
does not accept a Runtime at all: it cannot enqueue even when handed one. The single
enqueue path is `ingest()`, which refuses unless the ingress is explicitly enabled.

The enable switch is the environment variable `C01_RUNTIME_INGRESS_ENABLED`. Only the
exact value `true` (case-insensitive, surrounding whitespace ignored) enables it.
Unset, empty, `1`, `yes`, `Truey` or any other value leaves it disabled. Fail-safe,
because the disabled state is the one that cannot spend money.

While disabled, the module still reads, parses and computes - it reports exactly which
Runtime task it *would* create - and writes nothing anywhere.

Idempotency
-----------
One Owner C01 task is identified by `(cell, external_task_id)`, so the Runtime key is
*derived* through `c1_execution_contract.real_idempotency_key`, never chosen. Scanning
the same issue any number of times yields the same key, and the Runtime's own
`idempotency_key` UNIQUE constraint is what makes it one task. Note there is no way to
read a Runtime task back by key - the kernel exposes no such call - so this module does
not try to pre-check for an existing task; it relies on the key, which is why the key
must be derived rather than composed ad hoc.

Out of scope on purpose
-----------------------
Result write-back, issue comments, PR creation, candidate generation, C14 and C13 are
later stages. This module stops at "the task entered the Runtime".

Retries are also out of scope: `INGRESS_MAX_ATTEMPTS` is 1, because a second attempt of
the same execution is a second paid model call and owning that decision is a later,
explicit stage.
"""
from __future__ import annotations

import json
import os
import re
import sys

from c1_execution_contract import (
    OWNER_C,
    REAL_TASK_KIND,
    Refused,
    build_task_payload,
    canonical,
    canonical_cell_id,
    real_idempotency_key,
    sha256_hex,
    validate_task_payload,
)

# ---------------------------------------------------------------- enable switch
INGRESS_ENABLED_ENV = "C01_RUNTIME_INGRESS_ENABLED"
_ENABLED_LITERAL = "true"

# The task class this ingress produces. The smoke class is not reachable from here.
INGRESS_KIND = REAL_TASK_KIND
INGRESS_OWNER_C = OWNER_C

# One attempt. A retry would be a second paid dispatch of the same task, and the
# authority to spend that belongs to a later stage, not to an issue scanner.
INGRESS_MAX_ATTEMPTS = 1

# ------------------------------------------------------------------ issue shape
# The Owner's connector writes the cell and the task id into the issue TITLE, in the
# fixed three-segment form. That is the only place they are parsed from: it is
# positional and deterministic, so no task id is ever inferred from prose.
#
#     C01 · V70-R3-C01-01 · mixed hotel funds read-only diagnosis
#     ^^^   ^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#     cell  external_task_id                    scope
TITLE_SEPARATOR = re.compile(r"\s*[·•‧∙|]\s*")
TITLE_CELL = re.compile(r"^C[0-9]{1,2}$")
TITLE_TASK_ID = re.compile(r"^V[0-9]+-R[0-9]+-C[0-9]{2}-[0-9]{2}$")

# A 40-hex commit, not a substring of a longer digest (the 64-hex source-tree hashes
# that appear in the same bodies must not match).
SHA1 = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{40}(?![0-9a-fA-F])")

# Lines whose value is the canonical source this task is bound to. The markers are
# explicit; a commit that merely appears in prose is not an anchor.
ANCHOR_MARKERS = (
    "canonical source:",
    "canonical lineage:",
    "canonical_base:",
    "source_anchor:",
    "base=",
)

# The paragraph that states the objective. Both spellings are used by the Owner's
# connector today; neither is prose we have to interpret, the label is explicit.
OBJECTIVE_MARKERS = ("task:", "successor task:")

# Fields this ingress must produce. Missing any of them is a refusal, never a guess.
REQUIRED_FIELDS = ("issue_number", "cell_id", "external_task_id", "objective",
                   "scope", "source_anchor")


def _strip_list_marker(line: str) -> str:
    """Drop a leading markdown list marker and surrounding space from one line."""
    return line.strip().lstrip("-*+").strip()


def ingress_enabled(environ=None) -> bool:
    """True only for an explicit `true`. Everything else, including unset, is off."""
    env = os.environ if environ is None else environ
    value = env.get(INGRESS_ENABLED_ENV)
    if value is None:
        return False
    return value.strip().lower() == _ENABLED_LITERAL


def _parse_title(title: str) -> tuple:
    """Split the three-segment title, or refuse.

    Cell and task id come from here, so a title that does not have exactly the
    expected shape is refused rather than partially understood.
    """
    if not isinstance(title, str) or not title.strip():
        raise Refused("ISSUE_TITLE_INVALID")
    parts = [p.strip() for p in TITLE_SEPARATOR.split(title.strip())]
    if len(parts) != 3 or not all(parts):
        raise Refused("ISSUE_TITLE_NOT_THREE_SEGMENTS")
    cell, task_id, scope = parts
    if not TITLE_CELL.match(cell):
        raise Refused("ISSUE_TITLE_CELL_NOT_FOUND")
    if not TITLE_TASK_ID.match(task_id):
        raise Refused("ISSUE_TITLE_TASK_ID_NOT_FOUND")
    # The task id carries the cell as well; a mismatch means one of them was edited
    # by hand and the pair cannot be trusted as an identity.
    if "-%s-" % cell.upper() not in task_id.upper():
        raise Refused("ISSUE_TITLE_TASK_ID_CELL_MISMATCH")
    return cell.upper(), task_id, scope


def _parse_objective(body: str) -> str:
    """The paragraph introduced by an explicit objective label, or refuse."""
    lines = body.splitlines()
    for index, raw in enumerate(lines):
        line = _strip_list_marker(raw)
        lowered = line.lower()
        for marker in OBJECTIVE_MARKERS:
            if lowered.startswith(marker):
                chunk = [line[len(marker):].strip()]
                for follow in lines[index + 1:]:
                    if not follow.strip():
                        break
                    chunk.append(follow.strip())
                text = " ".join(part for part in chunk if part).strip()
                if not text:
                    raise Refused("INGRESS_OBJECTIVE_EMPTY")
                return text
    raise Refused("INGRESS_OBJECTIVE_NOT_FOUND")


def _parse_source_anchor(body: str) -> str:
    """The canonical source commit bound by an explicit anchor line, or refuse.

    Exactly one distinct commit must be found across the anchor lines. More than one
    is ambiguous and is refused rather than resolved by preference.
    """
    found = []
    for raw in body.splitlines():
        line = _strip_list_marker(raw)
        lowered = line.lower()
        if not any(lowered.startswith(marker) for marker in ANCHOR_MARKERS):
            continue
        matches = SHA1.findall(line)
        if len(matches) > 1:
            raise Refused("INGRESS_SOURCE_ANCHOR_AMBIGUOUS")
        if matches:
            found.append(matches[0].lower())
    distinct = sorted(set(found))
    if not distinct:
        raise Refused("INGRESS_SOURCE_ANCHOR_NOT_FOUND")
    if len(distinct) > 1:
        raise Refused("INGRESS_SOURCE_ANCHOR_AMBIGUOUS")
    return distinct[0]


def _parse_explicit_field(body: str, names) -> str | None:
    """Read an explicit `NAME: value` line, if the body carries one.

    Optional: the title already carries cell and task id. When the body repeats them,
    the two must agree - a disagreement is refused, not silently resolved.
    """
    for raw in body.splitlines():
        line = _strip_list_marker(raw)
        for name in names:
            if line.lower().startswith(name + ":"):
                value = line[len(name) + 1:].strip().strip("`").strip()
                if value:
                    return value
    return None


def parse_c01_issue(issue) -> dict:
    """Parse one already-open C01 issue into the facts a Runtime task needs.

    Fails closed on anything unexpected. In particular:
      * a pull request is not an issue;
      * a closed issue is not ingested (the Owner's own history shows closed C01
        issues have already been superseded by the next one in the same slot);
      * a missing field is a refusal - no task id, objective or anchor is ever
        inferred from natural language.
    """
    if type(issue) is not dict:
        raise Refused("ISSUE_NOT_AN_OBJECT")
    if "pull_request" in issue:
        raise Refused("ISSUE_IS_A_PULL_REQUEST")
    if issue.get("state") != "open":
        raise Refused("ISSUE_NOT_OPEN")

    number = issue.get("number")
    if type(number) is not int or number <= 0:
        raise Refused("ISSUE_NUMBER_INVALID")

    title_cell, title_task_id, title_scope = _parse_title(issue.get("title"))

    body = issue.get("body")
    if not isinstance(body, str) or not body.strip():
        raise Refused("ISSUE_BODY_EMPTY")

    explicit_cell = _parse_explicit_field(body, ("cell_id",))
    explicit_task = _parse_explicit_field(body, ("task_id",))
    if explicit_cell is not None and explicit_cell.upper() != title_cell:
        raise Refused("INGRESS_CELL_TITLE_BODY_MISMATCH")
    if explicit_task is not None and explicit_task != title_task_id:
        raise Refused("INGRESS_TASK_ID_TITLE_BODY_MISMATCH")

    cell_id = canonical_cell_id(title_cell)
    if cell_id != INGRESS_OWNER_C:
        # This ingress owns C01 only. Another cell's issue is another cell's business.
        raise Refused("INGRESS_ISSUE_IS_NOT_C01")

    parsed = {
        "issue_number": number,
        "cell_id": cell_id,
        "external_task_id": title_task_id,
        "objective": _parse_objective(body),
        "scope": title_scope,
        "source_anchor": _parse_source_anchor(body),
    }
    missing = [name for name in REQUIRED_FIELDS if not parsed.get(name)]
    if missing:
        raise Refused("INGRESS_FIELD_MISSING:" + ",".join(missing))
    return parsed


def plan_ingress(issue, *, environ=None) -> dict:
    """Compute the Runtime call this issue would produce. Never enqueues.

    There is no Runtime parameter here on purpose: this function is not able to
    enqueue anything, in any configuration, so the disabled path cannot be bypassed
    by passing one in.
    """
    parsed = parse_c01_issue(issue)
    payload = build_task_payload(
        cell_id=parsed["cell_id"],
        external_task_id=parsed["external_task_id"],
        objective=parsed["objective"],
        scope=parsed["scope"],
        source_anchor=parsed["source_anchor"],
        issue_number=parsed["issue_number"],
    )
    # Re-validate what will actually be handed to the Runtime, so the plan cannot
    # describe something the contract would refuse.
    payload = validate_task_payload(payload)
    idempotency_key = real_idempotency_key(payload["cell_id"], payload["external_task_id"])
    enabled = ingress_enabled(environ)
    return {
        "action": "SHADOW_PLAN" if enabled else "DISABLED",
        "enabled": enabled,
        "enqueued": False,
        "issue_number": parsed["issue_number"],
        "external_task_id": parsed["external_task_id"],
        "payload_sha256": sha256_hex(canonical(payload)),
        "would_enqueue": {
            "owner_c": INGRESS_OWNER_C,
            "kind": INGRESS_KIND,
            "payload": payload,
            "idempotency_key": idempotency_key,
            "max_attempts": INGRESS_MAX_ATTEMPTS,
        },
    }


def ingest(issue, *, runtime=None, environ=None) -> dict:
    """Plan, and enqueue only when explicitly enabled and given a Runtime.

    The refusal when enabled-without-a-Runtime is deliberate: "enabled but nothing to
    enqueue into" must be a loud error, not a silent no-op that looks like success.
    """
    plan = plan_ingress(issue, environ=environ)
    if not plan["enabled"]:
        return plan
    if runtime is None:
        raise Refused("RUNTIME_REQUIRED_WHEN_INGRESS_ENABLED")

    call = plan["would_enqueue"]
    task_id = runtime.enqueue(
        call["owner_c"],
        call["kind"],
        call["payload"],
        idempotency_key=call["idempotency_key"],
        max_attempts=call["max_attempts"],
    )
    result = dict(plan)
    result.update({"action": "ENQUEUED", "enqueued": True, "runtime_task_id": task_id})
    return result


# ------------------------------------------------------------------------ CLI
def _load_issue(path: str, number: int) -> dict:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    if isinstance(document, dict) and "issues" in document:
        for issue in document["issues"]:
            if issue.get("number") == number:
                return issue
        raise Refused("FIXTURE_ISSUE_NOT_FOUND")
    return document


def main(argv=None) -> int:
    """Print the plan for one issue. There is no flag that can enable or enqueue.

    Shadow use only: this command reads an issue, prints exactly which Runtime task
    it would create, and stops. The enable switch is environment-side, so nothing in
    argv can turn the ingress on.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 3 or argv[0] != "--plan":
        print("usage: c1_issue_ingress.py --plan <issues.json> <issue_number>",
              file=sys.stderr)
        return 2
    try:
        number = int(argv[2])
    except ValueError:
        print("issue number must be an integer", file=sys.stderr)
        return 2
    try:
        issue = _load_issue(argv[1], number)
        plan = plan_ingress(issue)
    except Refused as refusal:
        print("REFUSED %s" % refusal.reason)
        return 3
    except OSError as error:
        print("could not read the fixture: %s" % error, file=sys.stderr)
        return 2
    except ValueError as error:
        print("fixture is not valid JSON: %s" % error, file=sys.stderr)
        return 2
    print(canonical(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
