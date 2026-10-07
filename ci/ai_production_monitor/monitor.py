#!/usr/bin/env python3
"""Observation-only Boss 14-Cell activity + C13/C14 quality monitor for Issue #260.

The collector reads existing Formal Task Issues, Builder PRs and sealed C13/C14
GitHub Actions artifacts. It updates only the marked Live Metrics section of the
long-lived monitor issue. It never changes a review verdict, candidate, branch,
deployment state, runtime, or remediation plan.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

START_MARKER = "<!-- AI_PRODUCTION_MONITOR:START -->"
END_MARKER = "<!-- AI_PRODUCTION_MONITOR:END -->"
DEFAULT_ISSUE = 260
DEFAULT_TZ = "Asia/Shanghai"
C14_ARTIFACT = re.compile(r"^c13c14-lite-c14-([0-9a-f]{40})$")
C13_ARTIFACT = re.compile(r"^c13c14-lite-c13-([0-9a-f]{40})$")
PASSLIKE_C14 = {"PASS_SCOPED", "NOT_APPLICABLE"}
PASSLIKE_C13 = {"PASS_SCOPED"}
PRODUCTION_REVIEW_BRANCH = "main"
PRODUCTION_REVIEW_EVENT = "workflow_dispatch"
DEFAULT_BOSS_LOGIN = "yuguangzhi3836-glitch"
FORMAL_TASK_RE = re.compile(
    r"^C(?P<cell>0[1-9]|1[0-2])\s*·\s*(?P<task_id>V\d+-R\d+-C\d{2}-\d+)\s*·\s*(?P<scope>.+?)\s*$"
)
FORMAL_REVIEW_RE = re.compile(r"^C14\s*·\s*REVIEW\s*·\s*(?P<scope>.+?)\s*$", re.I)
CANDIDATE_PR_RE = re.compile(r"Candidate\s+PR\s*:\s*#(?P<number>\d+)", re.I)


class NonProductionArtifact(ValueError):
    """Known synthetic/POC artifact that must not enter production metrics."""


@dataclass(frozen=True)
class ReviewRecord:
    role: str
    candidate_sha: str
    verdict: str
    issued_at: datetime
    run_id: int | None = None
    artifact_id: int | None = None
    failure_class: str | None = None


class GitHubAPI:
    def __init__(self, repository: str, token: str, api_base: str = "https://api.github.com"):
        self.repository = repository
        self.token = token
        self.api_base = api_base.rstrip("/")

    def _request(self, method: str, path: str, body: dict | None = None) -> tuple[bytes, dict]:
        url = path if path.startswith("http") else f"{self.api_base}{path}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "go-ai-production-quality-monitor",
                **({"Content-Type": "application/json"} if data is not None else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read(), dict(response.headers.items())
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"GitHub API {method} {url} failed: HTTP {error.code}: {detail}") from error

    def get_json(self, path: str) -> dict:
        raw, _ = self._request("GET", path)
        return json.loads(raw.decode("utf-8"))

    def patch_json(self, path: str, body: dict) -> dict:
        raw, _ = self._request("PATCH", path, body)
        return json.loads(raw.decode("utf-8"))

    def get_bytes(self, path: str) -> bytes:
        raw, _ = self._request("GET", path)
        return raw

    def list_recent_artifacts(self, cutoff: datetime, max_pages: int = 20) -> list[dict]:
        artifacts: list[dict] = []
        encoded_repo = "/".join(urllib.parse.quote(part, safe="") for part in self.repository.split("/"))
        for page in range(1, max_pages + 1):
            payload = self.get_json(
                f"/repos/{encoded_repo}/actions/artifacts?per_page=100&page={page}"
            )
            batch = payload.get("artifacts") or []
            if not batch:
                break
            artifacts.extend(batch)
            parsed = [_parse_time(item.get("created_at")) for item in batch if item.get("created_at")]
            if parsed and max(parsed) < cutoff:
                break
        return [
            item for item in artifacts
            if not item.get("expired") and _parse_time(item.get("created_at")) >= cutoff
        ]

    def download_artifact(self, artifact_id: int) -> bytes:
        """Download an Actions artifact without leaking the GitHub bearer token to storage.

        GitHub answers the artifact ZIP endpoint with a redirect to a signed object-store
        URL. urllib's default redirect handler can carry request headers across that hop;
        the object store must receive only its signed URL, not the GitHub Authorization
        header.
        """
        encoded_repo = "/".join(urllib.parse.quote(part, safe="") for part in self.repository.split("/"))
        url = f"{self.api_base}/repos/{encoded_repo}/actions/artifacts/{artifact_id}/zip"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "go-ai-production-quality-monitor",
            },
        )
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in (301, 302, 303, 307, 308):
                detail = error.read().decode("utf-8", "replace")[:500]
                raise RuntimeError(
                    f"GitHub artifact download failed: HTTP {error.code}: {detail}"
                ) from error
            location = error.headers.get("Location")
            if not location:
                raise RuntimeError("GitHub artifact redirect did not provide Location") from error

        storage_request = urllib.request.Request(
            location,
            method="GET",
            headers={"User-Agent": "go-ai-production-quality-monitor"},
        )
        with urllib.request.urlopen(storage_request, timeout=60) as response:
            return response.read()

    def get_workflow_run(self, run_id: int) -> dict:
        encoded_repo = "/".join(urllib.parse.quote(part, safe="") for part in self.repository.split("/"))
        return self.get_json(f"/repos/{encoded_repo}/actions/runs/{run_id}")

    def get_issue(self, issue_number: int) -> dict:
        encoded_repo = "/".join(urllib.parse.quote(part, safe="") for part in self.repository.split("/"))
        return self.get_json(f"/repos/{encoded_repo}/issues/{issue_number}")

    def update_issue_body(self, issue_number: int, body: str) -> dict:
        encoded_repo = "/".join(urllib.parse.quote(part, safe="") for part in self.repository.split("/"))
        return self.patch_json(f"/repos/{encoded_repo}/issues/{issue_number}", {"body": body})

    def list_issues_since(self, since: datetime, max_pages: int = 10) -> list[dict]:
        encoded_repo = "/".join(urllib.parse.quote(part, safe="") for part in self.repository.split("/"))
        query = urllib.parse.urlencode({
            "state": "all",
            "since": since.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "per_page": 100,
        })
        out: list[dict] = []
        for page in range(1, max_pages + 1):
            batch = self.get_json(f"/repos/{encoded_repo}/issues?{query}&page={page}")
            if not batch:
                break
            out.extend(item for item in batch if "pull_request" not in item)
            if len(batch) < 100:
                break
        return out

    def list_recent_pulls(self, cutoff: datetime, max_pages: int = 10) -> list[dict]:
        encoded_repo = "/".join(urllib.parse.quote(part, safe="") for part in self.repository.split("/"))
        out: list[dict] = []
        for page in range(1, max_pages + 1):
            batch = self.get_json(
                f"/repos/{encoded_repo}/pulls?state=all&sort=updated&direction=desc&per_page=100&page={page}"
            )
            if not batch:
                break
            recent = [
                item for item in batch
                if _parse_time(item.get("updated_at")) >= cutoff.astimezone(timezone.utc)
            ]
            out.extend(recent)
            if len(batch) < 100 or len(recent) < len(batch):
                break
        return out


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bundle_from_zip(raw: bytes, role: str) -> dict:
    expected = f"{role}_bundle.json"
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        archive_names = archive.namelist()
        names = [name for name in archive_names if name.rsplit("/", 1)[-1] == expected]
        if len(names) != 1:
            poc_markers = {"poc.json", "logs/poc.spec.json", "logs/poc.contract.json"}
            if poc_markers.intersection(archive_names):
                raise NonProductionArtifact("POC_ONLY artifact")
            raise ValueError(f"artifact must contain exactly one {expected}; found={names}")
        return json.loads(archive.read(names[0]).decode("utf-8"))


def collect_records(api: GitHubAPI, cutoff: datetime) -> tuple[list[ReviewRecord], list[str]]:
    records: list[ReviewRecord] = []
    warnings: list[str] = []
    artifacts = api.list_recent_artifacts(cutoff)
    for artifact in artifacts:
        name = str(artifact.get("name") or "")
        match = C14_ARTIFACT.fullmatch(name)
        role = "c14" if match else None
        if not match:
            match = C13_ARTIFACT.fullmatch(name)
            role = "c13" if match else None
        if not match or role is None:
            continue
        expected_sha = match.group(1)
        artifact_id = artifact.get("id")
        workflow_run = artifact.get("workflow_run") or {}
        run_id = workflow_run.get("id")
        if run_id is None:
            warnings.append(
                f"artifact {artifact_id} ({name}): workflow run identity missing; excluded"
            )
            continue
        try:
            run = api.get_workflow_run(int(run_id))
            if (
                run.get("head_branch") != PRODUCTION_REVIEW_BRANCH
                or run.get("event") != PRODUCTION_REVIEW_EVENT
            ):
                continue
            bundle = _bundle_from_zip(api.download_artifact(int(artifact_id)), role)
            candidate_sha = str(bundle.get("candidate_sha") or "")
            if candidate_sha != expected_sha:
                raise ValueError(f"candidate mismatch artifact={expected_sha} bundle={candidate_sha}")
            expected_cell = role.upper()
            if bundle.get("cell_id") != expected_cell:
                raise ValueError(f"cell mismatch expected={expected_cell} got={bundle.get('cell_id')}")
            verdict = str(bundle.get("verdict") or "UNKNOWN")
            records.append(ReviewRecord(
                role=role,
                candidate_sha=candidate_sha,
                verdict=verdict,
                issued_at=_parse_time(bundle.get("issued_at")),
                run_id=int(bundle["github_run_id"]) if bundle.get("github_run_id") else None,
                artifact_id=int(artifact_id) if artifact_id is not None else None,
                failure_class=bundle.get("failure_class"),
            ))
        except NonProductionArtifact:
            continue
        except Exception as error:
            warnings.append(f"artifact {artifact_id} ({name}): {type(error).__name__}: {error}")
    records.sort(key=lambda item: item.issued_at)
    return records, warnings


def _within(record: ReviewRecord, label: str, now: datetime, tz: ZoneInfo) -> bool:
    if label == "Today":
        return record.issued_at.astimezone(tz).date() == now.astimezone(tz).date()
    days = 7 if label == "7 days" else 30
    return record.issued_at >= now.astimezone(timezone.utc) - timedelta(days=days)


def _local_day_start(now: datetime, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _pull_matches_task(pull: dict, issue_number: int, task_id: str) -> bool:
    body = str(pull.get("body") or "")
    issue_ref = re.search(rf"\bIssue\s*:?[ \t]*#{issue_number}\b", body, re.I)
    return bool(issue_ref or (task_id and task_id in body))


def _latest_verdict(records: list[ReviewRecord], role: str, candidate_sha: str | None) -> str | None:
    if not candidate_sha:
        return None
    matched = [
        record for record in records
        if record.role == role and record.candidate_sha == candidate_sha
    ]
    if not matched:
        return None
    return max(matched, key=lambda record: record.issued_at).verdict


def build_boss_activity(
    issues: list[dict],
    pulls: list[dict],
    records: list[ReviewRecord],
    now: datetime,
    tz_name: str,
    boss_login: str,
) -> list[dict]:
    tz = ZoneInfo(tz_name)
    today = now.astimezone(tz).date()
    pulls_by_number = {int(item["number"]): item for item in pulls if item.get("number") is not None}
    activity: list[dict] = []

    for issue in issues:
        creator = str((issue.get("user") or {}).get("login") or "")
        if creator != boss_login:
            continue
        created_at = _parse_time(issue.get("created_at"))
        if created_at.astimezone(tz).date() != today:
            continue

        title = str(issue.get("title") or "")
        task_match = FORMAL_TASK_RE.fullmatch(title)
        review_match = FORMAL_REVIEW_RE.fullmatch(title)
        if not task_match and not review_match:
            continue

        issue_number = int(issue["number"])
        body = str(issue.get("body") or "")
        candidate = None
        if task_match:
            cell = f"C{task_match.group('cell')}"
            task_id = task_match.group("task_id")
            scope = task_match.group("scope")
            candidates = [
                pull for pull in pulls
                if _pull_matches_task(pull, issue_number, task_id)
            ]
            if candidates:
                candidate = max(candidates, key=lambda item: _parse_time(item.get("updated_at")))
        else:
            cell = "C14"
            task_id = "REVIEW"
            scope = review_match.group("scope")
            candidate_match = CANDIDATE_PR_RE.search(body)
            if candidate_match:
                candidate = pulls_by_number.get(int(candidate_match.group("number")))

        candidate_number = int(candidate["number"]) if candidate and candidate.get("number") is not None else None
        candidate_sha = str((candidate or {}).get("head", {}).get("sha") or "") or None
        c14 = _latest_verdict(records, "c14", candidate_sha)
        c13 = _latest_verdict(records, "c13", candidate_sha)

        if candidate is None:
            status = "TASK_CREATED"
        elif c14 in {"FAIL", "BLOCKED"} or c13 in {"FAIL", "BLOCKED"}:
            status = "PRODUCT_OR_REVIEW_BLOCKED"
        elif c13 in PASSLIKE_C13:
            status = "REVIEW_ACCEPTED"
        elif c14 in PASSLIKE_C14:
            status = "C14_PASS_WAIT_C13"
        else:
            status = "BUILDER_PR_WAIT_REVIEW"

        activity.append({
            "issue_number": issue_number,
            "cell": cell,
            "task_id": task_id,
            "scope": scope,
            "candidate_number": candidate_number,
            "candidate_sha": candidate_sha,
            "c14": c14,
            "c13": c13,
            "status": status,
            "created_at": created_at,
        })

    activity.sort(key=lambda item: item["created_at"])
    return activity


def render_boss_activity(activity: list[dict], boss_login: str, warnings: list[str]) -> list[str]:
    lines = [
        "### Boss 14-Cell 今日工作",
        "",
        f"> Boss identity: `{boss_login}`.  ",
        "> Scope: today\'s Formal C01-C12 Task Issues plus manual C14 Review Issues; C13 activity is shown from sealed review evidence.",
        "",
    ]
    if not activity:
        lines.extend([
            "今天尚未发现 Boss 创建的正式 C01-C12 / C14 Review 工作项。",
            "",
        ])
    else:
        lines.extend([
            "| Cell | Work item | Boss asked | Builder / candidate | C14 | C13 | Work status |",
            "|---|---|---|---|---|---|---|",
        ])
        for item in activity:
            scope = str(item["scope"]).replace("|", "\\|").replace("\n", " ").strip()
            candidate = f"#{item['candidate_number']}" if item["candidate_number"] else "—"
            lines.append(
                f"| {item['cell']} | #{item['issue_number']} / {item['task_id']} | {scope} | "
                f"{candidate} | {item['c14'] or '—'} | {item['c13'] or '—'} | {item['status']} |"
            )
        lines.append("")

    lines.extend([
        "### Runtime / 工具判断",
        "",
        "```text",
        "RUNTIME_ACTION_REQUIRED = NO_PROVEN_GENERIC_FAILURE",
        f"MONITOR_EVIDENCE_WARNINGS = {len(warnings)}",
        "AUTO_REPAIR_RUNTIME = NO",
        "```",
        "",
        "- C14/C13 的 `FAIL` / `BLOCKED` 默认表示候选或审核结果，**不等于 Runtime 故障**。",
        "- 单条日志、旧文件 SHA 差异、历史 task 状态、监控读取 warning 默认记作 `NON_BLOCKING_OBSERVATION`，不得自动开 Runtime 修复。",
        "- 只有证实存在通用执行链故障才重新打开 Runtime：任务丢失、重复付费派发、lease/attempt fencing 失效、错误 candidate/result adoption、Generic Builder 普遍无法产出 Draft PR、C14→C13 通用链断裂或 recovery 无法恢复真实在途任务。",
        "- 本监控只汇总和分层，不 merge、不 deploy、不修改 verdict，也不创建 Runtime 修复任务。",
        "",
    ])
    return lines

def summarize(records: list[ReviewRecord], now: datetime, tz_name: str = DEFAULT_TZ) -> dict:
    tz = ZoneInfo(tz_name)
    out: dict[str, dict] = {}
    for label in ("Today", "7 days", "30 days"):
        subset = [record for record in records if _within(record, label, now, tz)]
        c14 = [record for record in subset if record.role == "c14"]
        c13 = [record for record in subset if record.role == "c13"]
        candidate_shas = {record.candidate_sha for record in c14}
        c14_by_sha: dict[str, list[ReviewRecord]] = {}
        c13_by_sha: dict[str, list[ReviewRecord]] = {}
        for record in c14:
            c14_by_sha.setdefault(record.candidate_sha, []).append(record)
        for record in c13:
            c13_by_sha.setdefault(record.candidate_sha, []).append(record)
        full_pass = {
            sha for sha in candidate_shas
            if any(r.verdict in PASSLIKE_C14 for r in c14_by_sha.get(sha, []))
            and any(r.verdict in PASSLIKE_C13 for r in c13_by_sha.get(sha, []))
        }
        out[label] = {
            "candidate_count": len(candidate_shas),
            "full_pass_candidates": len(full_pass),
            "c14_attempts": len(c14),
            "c14_pass": sum(r.verdict == "PASS_SCOPED" for r in c14),
            "c14_na": sum(r.verdict == "NOT_APPLICABLE" for r in c14),
            "c14_fail": sum(r.verdict == "FAIL" for r in c14),
            "c14_blocked": sum(r.verdict == "BLOCKED" for r in c14),
            "c13_attempts": len(c13),
            "c13_pass": sum(r.verdict == "PASS_SCOPED" for r in c13),
            "c13_fail": sum(r.verdict == "FAIL" for r in c13),
            "c13_blocked": sum(r.verdict == "BLOCKED" for r in c13),
        }
    return out


def render_live_metrics(summary: dict, generated_at: datetime, tz_name: str, warnings: list[str]) -> str:
    tz = ZoneInfo(tz_name)
    local = generated_at.astimezone(tz)
    lines = [
        START_MARKER,
        "## Live Metrics",
        "",
        f"> Last refreshed: **{local:%Y-%m-%d %H:%M:%S %Z}**  ",
        "> Source: existing sealed C13/C14 GitHub Actions artifacts.  ",
        "> Mode: **OBSERVATION_ONLY** — no thresholds, no automatic judgement.",
        "",
        "| Window | Candidates* | Full C14→C13 pass** | C14 PASS | C14 N/A | C14 FAIL | C14 BLOCK | C13 PASS | C13 FAIL | C13 BLOCK |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label in ("Today", "7 days", "30 days"):
        item = summary[label]
        lines.append(
            f"| {label} | {item['candidate_count']} | {item['full_pass_candidates']} | "
            f"{item['c14_pass']} | {item['c14_na']} | {item['c14_fail']} | {item['c14_blocked']} | "
            f"{item['c13_pass']} | {item['c13_fail']} | {item['c13_blocked']} |"
        )
    lines.extend([
        "",
        "* `Candidates` = unique candidate SHA with a sealed C14 review in the window.",
        "",
        "** `Full C14→C13 pass` means the same candidate SHA has a pass-like C14 result (`PASS_SCOPED` or `NOT_APPLICABLE`) and a `PASS_SCOPED` C13 result inside the window. It is **not** yet the true first-pass rate.",
        "",
        "```text",
        "FIRST_PASS_RATE = NOT_YET_AVAILABLE",
        "REWORK_DEPTH = NOT_YET_AVAILABLE",
        "OPEN_BLOCKED_CANDIDATES = NOT_YET_AVAILABLE",
        "ALERTING = OFF",
        "```",
        "",
        "The unavailable metrics require a stable origin work-item/task identity across candidate revisions. Until that binding exists, the monitor will not infer rework lineage from SHA or task-name patterns.",
    ])
    if warnings:
        lines.extend([
            "",
            f"Evidence warnings: **{len(warnings)}** artifact(s) could not be read. They are excluded rather than guessed.",
        ])
    lines.extend(["", END_MARKER])
    return "\n".join(lines)


def replace_marked_section(body: str, replacement: str) -> str:
    if START_MARKER in body and END_MARKER in body:
        pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.S)
        return pattern.sub(replacement, body, count=1)
    anchor = "## 目标"
    if anchor in body:
        return body.replace(anchor, f"{replacement}\n\n{anchor}", 1)
    return replacement + "\n\n" + body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--issue-number", type=int, default=DEFAULT_ISSUE)
    parser.add_argument("--timezone", default=DEFAULT_TZ)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.repository:
        parser.error("--repository or GITHUB_REPOSITORY is required")
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        parser.error("GITHUB_TOKEN is required")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)
    api = GitHubAPI(args.repository, token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    records, warnings = collect_records(api, cutoff)
    summary = summarize(records, now, args.timezone)
    live = render_live_metrics(summary, now, args.timezone, warnings)

    if warnings:
        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)

    if args.dry_run:
        print(live)
        return 0

    issue = api.get_issue(args.issue_number)
    new_body = replace_marked_section(str(issue.get("body") or ""), live)
    api.update_issue_body(args.issue_number, new_body)
    print(json.dumps({
        "issue": args.issue_number,
        "records": len(records),
        "warnings": len(warnings),
        "mode": "OBSERVATION_ONLY",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
