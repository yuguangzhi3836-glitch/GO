"""Bounded failure diagnosis and idempotent source-Issue receipt publication.

This is a hook on the existing Runtime execution loop, not another scheduler.  It runs
only after the exact GitHub run bound to an outbox identity is terminal and unsuccessful.
It never executes text read from a log, never dispatches a workflow, and never creates a
second Runtime task.  Its one write is a comment on the Formal Issue that originated the
task; a stable marker makes the write idempotent across process crashes.
"""
from __future__ import annotations

import hashlib
import json
import re

from c1_execution_contract import Refused, canonical

MAX_RECEIPT_ATTEMPTS = 3
MAX_COMMAND = 300
MAX_ERROR = 500

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z\s*")
_SECRET = re.compile(
    r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?|"
    r"(?:token|secret|password|passwd|api[_-]?key)\s*[:=]\s*)\S+"
)
_TOKENISH = re.compile(r"(?i)\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|sk-[A-Za-z0-9_-]{12,})\b")
_EXIT = re.compile(r"Process completed with exit code\s+(\d+)", re.I)


class ReceiptRetry(RuntimeError):
    """A transient receipt write failed and may be retried without re-dispatching."""


def _clean(value, limit):
    text = _ANSI.sub("", str(value or ""))
    text = _TIMESTAMP.sub("", text)
    text = _SECRET.sub(lambda m: m.group(1) + "[REDACTED]", text)
    text = _TOKENISH.sub("[REDACTED_TOKEN]", text)
    text = text.replace("`", "'").replace("@", "＠")
    text = " ".join(text.split())
    return text[:limit] or None


def _first_failed_job(jobs):
    ordered = sorted((j for j in jobs if isinstance(j, dict)),
                     key=lambda j: (j.get("started_at") or j.get("created_at") or "",
                                    j.get("id") or 0))
    for job in ordered:
        if job.get("conclusion") in ("failure", "cancelled", "timed_out",
                                     "action_required", "startup_failure"):
            return job
    return None


def _first_failed_step(job):
    for step in job.get("steps") or []:
        if isinstance(step, dict) and step.get("conclusion") in (
                "failure", "cancelled", "timed_out", "action_required"):
            return step
    return None


def _diagnose(job, log_text, *, log_error=None):
    steps = job.get("steps") or []
    runner_id = job.get("runner_id") or 0
    step = _first_failed_step(job)
    lines = str(log_text or "").splitlines()
    command = None
    exit_code = None
    error = None

    current_command = None
    for raw in lines:
        line = _TIMESTAMP.sub("", _ANSI.sub("", raw)).strip()
        if "##[group]Run " in line:
            current_command = line.split("##[group]Run ", 1)[1]
        matched = _EXIT.search(line)
        if matched and int(matched.group(1)) != 0 and exit_code is None:
            # A job log contains successful setup commands before the failing command.
            # The command whose group owns the first non-zero completion is the failed
            # command; taking the first Run group would bind the receipt to the wrong step.
            command = current_command
            exit_code = int(matched.group(1))
        if error is None and not matched and any(token in line for token in (
                "##[error]", "NO_CHANGED_PATHS", "BLOCKED BY CELL SCOPE",
                "Read-only file system", "ModuleNotFoundError", "Traceback")):
            error = line.replace("##[error]", "", 1).strip()

    if step and command is None:
        command = step.get("name")
    command = _clean(command, MAX_COMMAND)
    error = _clean(error or log_error, MAX_ERROR)

    if log_error:
        classification = "EVIDENCE_BLOCKED"
        next_action = ("Actions permission/evidence owner: restore job-log read access; "
                       "do not infer a code defect without the failed command")
    elif job.get("conclusion") == "cancelled" and not steps and not runner_id:
        classification = "EXTERNAL_RUNNER_BLOCKED"
        next_action = ("Actions/runner owner: determine why no runner was assigned, "
                       "restore runner availability, then authorize one bounded validation run")
    elif error and ("NO_CHANGED_PATHS" in error or "BLOCKED BY CELL SCOPE" in error):
        classification = "OWNERSHIP_BLOCKED"
        next_action = ("repository owner for the blocked paths: implement the narrow fix or "
                       "persist a no-patch BLOCKED receipt; do not widen the cell allowlist")
    elif exit_code is not None:
        classification = "CODE_OR_TEST_FAILURE"
        next_action = ("owning source cell: reproduce the exact command, make one narrow "
                       "candidate fix, and validate before C14 then C13")
    else:
        classification = "UNPROVEN"
        next_action = ("execution owner: obtain the missing command, exit code and sanitized "
                       "error before assigning or retrying work")

    return {"classification": classification, "first_failed_command": command,
            "exit_code": exit_code, "sanitized_error": error,
            "next_action": next_action}


def _fingerprint(request, run, job):
    payload = request.get("payload") or {}
    material = {
        "repo": request.get("repo"), "run_id": run["id"],
        "run_attempt": run.get("run_attempt", 1), "job_id": job.get("id"),
        "candidate_sha": run.get("head_sha") or payload.get("source_anchor"),
    }
    digest = hashlib.sha256(canonical(material).encode("utf-8")).hexdigest()
    return material, digest


def _comment(report):
    evidence = report["evidence"]
    diagnosis = report["diagnosis"]
    lines = [
        "<!-- GO_FAILURE_CLOSURE:%s -->" % report["fingerprint"],
        "失败闭环自动回执（未重跑、未新增付费派发）",
        "",
        "- 状态：**FAILURE_OBSERVED**",
        "- 分类：`%s`" % diagnosis["classification"],
        "- 绑定：repo=`%s` / run=`%s` / attempt=`%s` / job=`%s` / candidate=`%s`"
        % (evidence.get("repo"), evidence.get("run_id"), evidence.get("run_attempt"),
           evidence.get("job_id"), evidence.get("candidate_sha") or "UNPROVEN"),
        "- 首个失败命令：`%s`" % (diagnosis.get("first_failed_command") or "N/A（无执行证据）"),
        "- 退出码：`%s`" % (diagnosis.get("exit_code")
                            if diagnosis.get("exit_code") is not None else "N/A"),
        "- 脱敏错误：`%s`" % (diagnosis.get("sanitized_error") or "UNPROVEN"),
        "- 具体下一任务：%s" % diagnosis["next_action"],
        "",
        "此回执只记录失败事实和责任路径；不代表已实现、已测试、独立审核或已部署。",
    ]
    return "\n".join(lines)


def close_failed_run(request, run, outbox, client):
    """Diagnose one terminal failed run and publish/reuse one source-Issue receipt.

    A transient comment transport error raises ``ReceiptRetry`` for at most three ticks.
    Permission failures and exhausted retries return a BLOCKED report so the Runtime can
    retain the exact blocker in its own terminal Evidence instead of looping forever.
    """
    request_id = request["execution_request_id"]
    prior = outbox.failure_receipt(request_id)
    if prior and prior.get("status") in ("PUBLISHED", "REUSED", "BLOCKED"):
        return prior

    payload = request.get("payload") or {}
    issue_number = payload.get("issue_number")
    if type(issue_number) is not int or issue_number <= 0:
        report = {"status": "BLOCKED", "reason": "SOURCE_ISSUE_UNBOUND",
                  "fingerprint": None, "evidence": {"repo": request.get("repo"),
                  "run_id": run["id"], "run_attempt": run.get("run_attempt", 1),
                  "job_id": None, "candidate_sha": run.get("head_sha")},
                  "diagnosis": {"classification": "IDENTITY_BLOCKED",
                  "first_failed_command": None, "exit_code": None,
                  "sanitized_error": "task payload has no source issue",
                  "next_action": "ingress owner: bind a valid source issue; do not guess"}}
        outbox.record_failure_receipt(request_id, report)
        return report

    jobs_error = None
    try:
        jobs = client.list_run_jobs(run["id"], run.get("run_attempt", 1))
    except Refused as exc:
        # Job-list evidence is useful but must never become an unbounded blocker.  The
        # receipt remains publishable and says exactly which evidence access failed.
        jobs = []
        jobs_error = exc.reason
    job = _first_failed_job(jobs) or {"id": None, "conclusion": run.get("conclusion"),
                                      "steps": [], "runner_id": 0}
    log_text = ""
    log_error = None
    if job.get("id") is not None and job.get("steps"):
        try:
            log_text = client.download_job_log(job["id"])
        except Refused as exc:
            log_error = exc.reason
    evidence, fingerprint = _fingerprint(request, run, job)
    diagnosis = _diagnose(job, log_text, log_error=log_error or jobs_error)
    report = {"status": "PENDING", "fingerprint": fingerprint,
              "evidence": evidence, "diagnosis": diagnosis}
    marker = "GO_FAILURE_CLOSURE:%s" % fingerprint

    try:
        if client.issue_comment_contains(issue_number, marker):
            report["status"] = "REUSED"
        else:
            client.post_issue_comment(issue_number, _comment(report))
            report["status"] = "PUBLISHED"
        outbox.record_failure_receipt(request_id, report)
        return report
    except Refused as exc:
        attempts = outbox.record_failure_receipt_attempt(request_id, exc.reason, report)
        if exc.reason in ("GITHUB_HTTP_401", "GITHUB_HTTP_403"):
            report.update({"status": "BLOCKED", "reason": exc.reason,
                           "attempts": attempts})
            outbox.record_failure_receipt(request_id, report)
            return report
        if attempts < MAX_RECEIPT_ATTEMPTS:
            raise ReceiptRetry(exc.reason) from None
        report.update({"status": "BLOCKED", "reason": "RECEIPT_RETRY_EXHAUSTED:" + exc.reason,
                       "attempts": attempts})
        outbox.record_failure_receipt(request_id, report)
        return report
