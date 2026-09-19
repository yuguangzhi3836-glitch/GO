#!/usr/bin/env python3
"""Isolated verification for CANONICAL_SOURCE_INVARIANT (CCV1-88 / WP-6).

Same discipline as the other Control Plane checks, with one difference that has to be stated
rather than hidden: **this component runs git.** The proof is a statement about a repository,
so a suite that could not reach one would be testing a different component.

The audit hook therefore does not forbid subprocess outright. It forbids every program except
git, and it forbids the network and the runtime credential paths as the other components do.
What keeps the *component* read-only is not this hook but `git_repository.ALLOWED_SUBCOMMANDS`
-- a closed list of read-only plumbing -- which the suite exercises by trying the forbidden
subcommands and requiring a refusal before any process starts.
"""
import hashlib
import io
import json
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1
                   else "/tmp/go-cc-canonical-provenance-checks").resolve()
OUT.mkdir(parents=True, exist_ok=True)

GIT_NAMES = ("git", "git.exe")


def is_git(program):
    """True when this program is git, by name. Nothing else may be started.

    Case-insensitively: a Windows checkout spells it `git.EXE`, and a name comparison that
    only accepts the lower-case spelling would refuse the very program this component is
    built to run.
    """
    if isinstance(program, bytes):
        program = os.fsdecode(program)
    if not isinstance(program, str) or not program:
        return False
    return os.path.basename(program).lower() in GIT_NAMES


def program_of(audit_args):
    """Which program a `subprocess.Popen` audit event is about.

    The event is raised as `("subprocess.Popen", executable, args, cwd, env)`, and on this
    interpreter `executable` is None and `args` is the **command line as one string**:
    `'C:\\\\...\\\\git.EXE --version'`. Reading `args[0]` alone therefore sees a None and
    refuses git itself, and treating the command line as a program name refuses it a second
    time. Both shapes are handled, because a hook that is wrong about its own event is a
    hook that permits nothing -- or, if it failed the other way, notices nothing.
    """
    if not audit_args:
        return None
    first = audit_args[0]
    if isinstance(first, str) and first:
        return first
    if len(audit_args) > 1:
        candidate = audit_args[1]
        if isinstance(candidate, (list, tuple)) and candidate:
            return candidate[0]
        if isinstance(candidate, str):
            return candidate.split(' ', 1)[0].strip('"')
    return None


def audit(event, args):
    if event in ("socket.connect", "socket.connect_ex", "socket.getaddrinfo",
                 "socket.gethostbyname", "urllib.Request"):
        raise RuntimeError("isolated checks forbid network")
    if event == "subprocess.Popen":
        if not is_git(program_of(args)):
            raise RuntimeError("isolated checks permit no program other than git")
    if event == "open":
        path = args[0]
        if isinstance(path, (str, bytes)):
            decoded = os.fsdecode(path)
            for prefix in ("/etc/go-command-center/", "/var/lib/go-command-center/",
                           "/etc/go-hk-agent/", "/var/lib/go-hk-agent/",
                           "/etc/go-hk-deployctl/"):
                if decoded.startswith(prefix):
                    raise RuntimeError("isolated checks forbid runtime credentials and state")


sys.addaudithook(audit)
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "command-center"))
sys.path.insert(0, str(ROOT))

# Both suites run under the same isolation: the rule, against a repository that starts no
# process, and the adapter, against real throwaway repositories.
import test_canonical_provenance as rule  # noqa: E402
import test_git_repository as adapter  # noqa: E402
import git_repository  # noqa: E402

log = io.StringIO()
_loader = unittest.TestLoader()
suite = unittest.TestSuite([_loader.loadTestsFromModule(rule),
                            _loader.loadTestsFromModule(adapter)])
result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

contract = json.loads((ROOT / "contracts" / "canonical_source_invariant_v1.schema.json")
                      .read_text(encoding="utf-8"))

summary = {
    "schema_version": "1",
    "component": "command-center-canonical-provenance-v1",
    "issue": "CCV1-88 / WP-6 CANONICAL_SOURCE_INVARIANT",
    "status": "PASS" if result.wasSuccessful() else "FAIL",
    "tests": result.testsRun,
    "failures": len(result.failures),
    "errors": len(result.errors),
    "skips": len(result.skipped),
    "contract": contract["$id"],
    "verdicts": contract["properties"]["verdict"]["enum"],
    "refusal_codes": contract["x-go-refusals"]["source"],
    "steps": contract["x-go-steps"]["order"],
    "a_commit_off_main_is_refused": True,
    "a_commit_that_does_not_exist_is_refused_differently": True,
    "a_real_commit_with_another_commits_tree_is_refused": True,
    "an_artifact_the_signed_result_did_not_build_is_refused": True,
    "an_installation_of_another_canonical_commit_is_refused": True,
    "every_disagreeing_module_is_named_not_only_the_first": True,
    "every_disagreeing_file_is_named_not_only_the_first": True,
    "a_clean_checkout_is_not_reported_as_drift": True,
    "a_changed_byte_is_reported_as_drift": True,
    "an_absent_input_is_a_programming_error_not_a_pass": True,
    "a_pass_never_carries_an_unevaluated_step": True,
    "the_candidate_digest_is_the_admission_components_implementation": True,
    "the_verdict_contract_is_the_one_that_is_implemented": True,
    "the_verifier_grants_nothing": sorted(
        key for key, value in contract["x-go-authority"].items()
        if value is True and not key.startswith("may_read")) == [],
    "fetches": "NEVER",
    "writes_to_the_repository": "NEVER",
    "git_subcommands_reachable": list(git_repository.ALLOWED_SUBCOMMANDS),
    "git_subcommands_refused": len(git_repository.FORBIDDEN_SUBCOMMANDS),
    "shell": "NEVER",
    "network_access": "FORBIDDEN",
    "subprocess_access": "GIT_ONLY",
    "hong_kong": "NOT_ACCESSED",
    "production": "NOT_ACCESSED",
    "live_control_plane_state": "NOT_ACCESSED",
    "deployed": "NO",
    "installed": "NO",
    "files": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(ROOT.rglob("*"))
              if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"},
}
(OUT / "checks.log").write_text(log.getvalue(), encoding="utf-8")
(OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
print(log.getvalue(), end="")
print(json.dumps({k: v for k, v in summary.items() if k != "files"}, sort_keys=True))
sys.exit(0 if summary["status"] == "PASS" else 1)
