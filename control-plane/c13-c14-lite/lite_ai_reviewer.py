"""Read-only AI reviewer used by both Lite V2 jobs.

Design constraints taken from the task (sections 13, 17, 18, 25, 26):

* **read-only**: this module only ever POSTs text to the model endpoint and parses
  JSON back. It never executes candidate code, never runs Docker, never touches a
  database, and never holds a deployment credential.
* **fresh execution**: one request produces one ``ai_execution_id`` (the provider
  response id). C13 and C14 each get their own, which is what makes the
  independence check machine-checkable instead of a written claim.
* **structured output**: the verdict is constrained by a JSON schema, so a
  free-text answer can never be reinterpreted as PASS.
* **quota honesty**: a provider/quota failure becomes ``BLOCKED`` with
  ``failure_class = AI_QUOTA_EXHAUSTED`` — never FAIL, never a silent PASS.

``stub`` mode exists so the workflow plumbing and the whole acceptance chain can be
tested deterministically offline. Stub opinions are permanently labelled
``ai_provider = LOCAL_STUB_DETERMINISTIC`` and can never be mistaken for a real
review.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from lite_canonical import digest, digest_bytes
from lite_errors import AI_REVIEW, BLOCKED, classify_ai_failure

API_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.6-sol"
STUB_PROVIDER = "LOCAL_STUB_DETERMINISTIC"

C14_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "candidate_sha", "findings", "blocking_issues", "remediation_status", "not_applicable", "summary"],
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS_SCOPED", "FAIL", "BLOCKED", "NOT_APPLICABLE"]},
        "candidate_sha": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "severity", "statement"],
                "properties": {
                    "id": {"type": "string"},
                    "severity": {"type": "string", "enum": ["BLOCKER", "MAJOR", "MINOR", "INFO"]},
                    "statement": {"type": "string"},
                },
            },
        },
        "blocking_issues": {"type": "array", "items": {"type": "string"}},
        "remediation_status": {"type": "string", "enum": ["OPEN", "PARTIAL", "CLOSED", "NOT_REQUIRED"]},
        "not_applicable": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["review_scope", "basis", "applicable_rule_set", "applicable_rule_version", "why_not_applicable"],
            "properties": {
                "review_scope": {"type": "string"},
                "basis": {"type": "string"},
                "applicable_rule_set": {"type": "string"},
                "applicable_rule_version": {"type": "string"},
                "why_not_applicable": {"type": "string"},
            },
        },
        "summary": {"type": "string"},
    },
}

C13_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "candidate_sha", "quality_findings", "remaining_risks", "summary"],
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS_SCOPED", "FAIL", "BLOCKED"]},
        "candidate_sha": {"type": "string"},
        "quality_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "severity", "statement"],
                "properties": {
                    "id": {"type": "string"},
                    "severity": {"type": "string", "enum": ["BLOCKER", "MAJOR", "MINOR", "INFO"]},
                    "statement": {"type": "string"},
                },
            },
        },
        "remaining_risks": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
}

ROLE_SCHEMAS = {"c14": C14_OUTPUT_SCHEMA, "c13": C13_OUTPUT_SCHEMA}


class ReviewUnavailable(RuntimeError):
    """The review could not be produced. Always a BLOCKED, never a FAIL/PASS."""

    def __init__(self, failure_class: str, detail: str, http_status=None):
        super().__init__(f"{failure_class}: {detail}")
        self.failure_class = failure_class
        self.verdict = BLOCKED
        self.detail = detail
        self.http_status = http_status


ROLE_RULES = {
    "c14": (
        "You are C14: the constitution, permission, legal, regulatory, contract and AI-behaviour "
        "rule reviewer for the GO project. You are NOT a second quality tester. Do not ask for or "
        "assume Docker, PostgreSQL, regression, recovery or journey test results. Review rules, "
        "permissions, IAM changes, contracts, regulatory duties and AI behaviour rules only. "
        "Judge only against the rule text supplied in these facts: it is the authoritative "
        "rule source for this round and the only basis you may use. If that text is absent or "
        "insufficient to decide, return BLOCKED and say what is missing - never NOT_APPLICABLE. "
        "Return NOT_APPLICABLE (with scope, basis and rule reference) only when the rule text "
        "is present and you can show that these rules do not apply to this candidate's "
        "change. "
        "You are not a second GitHub process checker. These are mechanically verifiable "
        "repository-process facts, and their absence or formatting must NOT on its own produce "
        "a blocking finding: whether a short-lived branch exists, how many reviews a pull "
        "request has, GitHub CI/check status, whether a pull-request template field is present, "
        "whether a change class was written as a string, and the general completeness of pull "
        "request metadata. Checking that class of fact belongs to a deterministic preflight, "
        "not to semantic rule review. You DO still judge whether what the brief claims is "
        "actually true of the change: if the brief declares a change class such as PRODUCT_FIX "
        "while the diff really alters an authority, a topology, an IAM boundary or a governance "
        "contract, that inconsistency is a real governance finding and must be reported."
    ),
    "c13": (
        "You are C13: the independent quality acceptance reviewer for the GO project. You did not "
        "write the code under review and you must not accept the author's own tests as proof. You "
        "receive the review brief, machine-test evidence, source and acceptance criteria. You must "
        "not claim to have executed anything yourself; judge the supplied machine evidence and the "
        "source against the brief the candidate was answering. "
        "These are not failures and must not be turned into a non-PASS verdict: naming that could "
        "be prettier, a function that could be more elegant, further refactoring, additional "
        "non-required tests, documentation polish, and ordinary best-practice advice. Report them "
        "as quality_findings or remaining_risks if they are worth saying, and leave the verdict at "
        "PASS_SCOPED. A verdict other than PASS_SCOPED needs a real blocker within your "
        "responsibility: an original task objective the candidate did not meet, a required machine "
        "test that actually failed, a demonstrated regression, a security / recovery / journey "
        "blocker, a material quality defect directly relevant to the task, or the absence of the "
        "key evidence needed to decide at all."
    ),
}

#: The shared standard both cells are held to. It exists because the first real Review E2E
#: showed the opposite failure mode: a reviewer that never learned the original task, and a
#: prompt that never said a clean review was an acceptable outcome, will grade a candidate
#: against its own idea of best practice and escalate what it finds.
#:
#: It changes no output field and no verdict vocabulary. It only states what the verdict means:
#: PASS_SCOPED is "this is acceptable", not "this is perfect".
REVIEW_STANDARD = (
    "REVIEW STANDARD (acceptance, not perfection)",
    "- The review goal is acceptance, not perfection.",
    "- Judge the candidate against the supplied review brief and against the rules, acceptance "
    "criteria and evidence that apply to your role.",
    "- Do not invent requirements outside the supplied review brief, authoritative rules, "
    "acceptance criteria or machine evidence. A practice that is merely good is not a "
    "requirement the candidate failed.",
    "- Finding nothing blocking is a valid and successful review result.",
    "- Minor, advisory, stylistic, cleanup, readability, optional-hardening or "
    "future-improvement findings may be reported, but they do not require rework.",
    "- PASS_SCOPED may include non-blocking findings and remaining risks.",
    "- Do not manufacture findings merely to demonstrate reviewer value.",
    "- Rework is justified only by a real blocking defect within the reviewer's assigned "
    "responsibility.",
)


def build_prompt(role: str, facts: dict) -> str:
    """Deterministic prompt: the same facts always produce the same bytes."""
    lines = [
        ROLE_RULES[role],
        "",
        *REVIEW_STANDARD,
        "",
        "HARD CONSTRAINTS",
        "- Read-only. Never execute candidate code, Docker, databases or deployments.",
        "- Base every statement on the supplied facts; do not invent test results.",
        "- The candidate SHA in your answer MUST be exactly the frozen candidate SHA below.",
        "- You cannot authorise anything: deployment, merge and release remain human decisions.",
        "- Answer with JSON only, matching the provided output schema.",
        "",
        "FROZEN CANDIDATE",
        json.dumps(facts, ensure_ascii=False, sort_keys=True, indent=2),
    ]
    return "\n".join(lines) + "\n"


def _facts_digest(facts: dict) -> str:
    return digest(facts)


def _extract_text(payload) -> str:
    if not isinstance(payload, dict):
        raise ReviewUnavailable(classify_ai_failure(None, "", "bad_payload"), "response_not_an_object")
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"]
    for item in payload.get("output", []) or []:
        for block in item.get("content", []) or []:
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                return text
    raise ReviewUnavailable(classify_ai_failure(None, "", "no_output_text"), "no_output_text")


def _call_api(*, prompt: str, model: str, api_key: str, schema: dict, role: str, timeout: int):
    body = json.dumps(
        {
            "model": model,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": f"go_c13c14_lite_{role}_verdict",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "go-c13c14-lite-reviewer",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = error.read().decode("utf-8", "replace")
        except Exception:  # pragma: no cover - best effort only
            detail = "unreadable_error_body"
        raise ReviewUnavailable(classify_ai_failure(error.code, detail), detail[:400], http_status=error.code) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ReviewUnavailable(classify_ai_failure(transport_error=str(error)), str(error)[:400]) from error
    payload = json.loads(raw.decode("utf-8"))
    return payload, _extract_text(payload), raw


def _stub_opinion(role: str, facts: dict) -> dict:
    seed = _facts_digest(facts)
    candidate_sha = facts["candidate_sha"]
    if role == "c14":
        opinion = {
            "verdict": "PASS_SCOPED",
            "candidate_sha": candidate_sha,
            "findings": [],
            "blocking_issues": [],
            "remediation_status": "NOT_REQUIRED",
            "not_applicable": None,
            "summary": f"LOCAL STUB deterministic rule review (seed {seed[:16]}). No network call was made.",
        }
    else:
        opinion = {
            "verdict": "PASS_SCOPED",
            "candidate_sha": candidate_sha,
            "quality_findings": [],
            "remaining_risks": [
                "LOCAL STUB: this opinion is a deterministic placeholder, not a real AI quality review."
            ],
            "summary": f"LOCAL STUB deterministic quality acceptance (seed {seed[:16]}). No network call was made.",
        }
    return opinion


def validate_opinion(role: str, opinion, candidate_sha: str) -> None:
    if not isinstance(opinion, dict):
        raise ReviewUnavailable("AI_PROVIDER_FAILURE", "opinion_not_an_object")
    if role == "c14":
        required = set(C14_OUTPUT_SCHEMA["required"])
    else:
        required = set(C13_OUTPUT_SCHEMA["required"])
    if set(opinion) != required:
        raise ReviewUnavailable("AI_PROVIDER_FAILURE", "opinion_field_set_mismatch")
    if opinion.get("candidate_sha") != candidate_sha:
        raise ReviewUnavailable("AI_PROVIDER_FAILURE", "opinion_candidate_mismatch")


def run(
    role: str,
    facts: dict,
    *,
    model: str = DEFAULT_MODEL,
    api_key=None,
    stub: bool = False,
    timeout: int = 180,
) -> dict:
    """Produce one fresh review execution. Raises ``ReviewUnavailable`` on failure."""
    if role not in ROLE_SCHEMAS:
        raise ValueError("role must be c13 or c14")
    if not isinstance(facts, dict) or not facts.get("candidate_sha"):
        raise ValueError("facts must be an object carrying candidate_sha")

    prompt = build_prompt(role, facts)
    prompt_sha256 = digest_bytes(prompt.encode("utf-8"))
    input_sha256 = _facts_digest(facts)

    if stub:
        opinion = _stub_opinion(role, facts)
        opinion_sha256 = digest(opinion)
        return {
            "role": role,
            "verdict": opinion["verdict"],
            "opinion": opinion,
            "opinion_sha256": opinion_sha256,
            "prompt_sha256": prompt_sha256,
            "input_sha256": input_sha256,
            "ai_provider": STUB_PROVIDER,
            "ai_model": "deterministic-stub",
            "ai_execution_id": f"stub-{opinion_sha256[:32]}",
            "failure_class": None,
            "decision_origin": AI_REVIEW,
            "ai_called": True,
        }

    if not api_key:
        raise ReviewUnavailable("AI_PROVIDER_FAILURE", "api_key_not_supplied")
    payload, text, _raw = _call_api(
        prompt=prompt, model=model, api_key=api_key, schema=ROLE_SCHEMAS[role], role=role, timeout=timeout
    )
    try:
        opinion = json.loads(text)
    except ValueError as error:
        raise ReviewUnavailable("AI_PROVIDER_FAILURE", "opinion_not_json") from error
    validate_opinion(role, opinion, facts["candidate_sha"])
    execution_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(execution_id, str) or not execution_id.strip():
        raise ReviewUnavailable("AI_PROVIDER_FAILURE", "provider_execution_id_missing")
    return {
        "role": role,
        "verdict": opinion["verdict"],
        "opinion": opinion,
        "opinion_sha256": digest(opinion),
        "prompt_sha256": prompt_sha256,
        "input_sha256": input_sha256,
        "ai_provider": "OPENAI_RESPONSES_API",
        "ai_model": model,
        "ai_execution_id": execution_id,
        "failure_class": None,
        "decision_origin": AI_REVIEW,
        "ai_called": True,
    }


def blocked_outcome(role: str, facts: dict, failure_class: str, detail: str) -> dict:
    """The only outcome a provider/quota failure may produce: BLOCKED, with identity kept."""
    prompt = build_prompt(role, facts)
    return {
        "role": role,
        "verdict": BLOCKED,
        "opinion": None,
        "opinion_sha256": None,
        "prompt_sha256": digest_bytes(prompt.encode("utf-8")),
        "input_sha256": _facts_digest(facts),
        "ai_provider": "OPENAI_RESPONSES_API",
        "ai_model": None,
        "ai_execution_id": None,
        "failure_class": failure_class,
        "decision_origin": AI_REVIEW,
        "ai_called": True,
        "detail": detail,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=sorted(ROLE_SCHEMAS))
    parser.add_argument("--facts", required=True, help="path to the frozen facts JSON")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stub", action="store_true", help="offline deterministic opinion (never a real review)")
    args = parser.parse_args(argv)

    facts = json.loads(open(args.facts, encoding="utf-8").read())
    try:
        outcome = run(args.role, facts, model=args.model, api_key=__import__("os").environ.get("OPENAI_API_KEY"), stub=args.stub)
    except ReviewUnavailable as error:
        outcome = blocked_outcome(args.role, facts, error.failure_class, error.detail)
        outcome["http_status"] = error.http_status
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(outcome, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"role": outcome["role"], "verdict": outcome["verdict"], "failure_class": outcome["failure_class"]}))
    return 0 if outcome["verdict"] != BLOCKED else 1


if __name__ == "__main__":
    sys.exit(main())
