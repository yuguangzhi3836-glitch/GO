"""Concrete offline suite adapter. Only installed host configuration selects image/socket.

No pull, build, SSH, credentials, host bind mount or caller-supplied command.
The local daemon is trusted infrastructure; never expose it to the test image.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET

from acceptance_gate import Refusal
from c13_attestation import CANDIDATE, TREE, SCOPE
from c14_isolated_runner import SCOPE_COMMANDS
from house_bridge import canonical, digest, frozen_junit_counts

MAX_SOURCE = 64_000_000
MAX_OUTPUT = 3_000_000
TMPFS = {"/work": "rw,nosuid,nodev,size=1073741824,uid=65532,gid=65532,mode=0700",
         "/tmp": "rw,nosuid,nodev,size=268435456,mode=1777",
         "/var/lib/postgresql": "rw,nosuid,nodev,noexec,size=1048576,mode=0700"}
ENTRYPOINT = "/opt/venv/bin/python"
ENTRY_ARGS = ["-I", "/opt/c14/sandbox_payload.py"]


def parse_output(raw, image_id, source_digest):
    """Derive the technical result from the two real suites, never an inventory template."""
    try:
        if type(raw) is not bytes or len(raw) > MAX_OUTPUT:
            raise ValueError("size")
        report = json.loads(raw)
        expected = {"contract", "candidate_sha", "application_tree", "postgres_version",
                    "pytest_exit", "postgres_exit", "files"}
        if (type(report) is not dict or set(report) != expected or
                report["contract"] != "GO_C14_SANDBOX_OUTPUT_V1" or
                (report["candidate_sha"], report["application_tree"]) != (CANDIDATE, TREE) or
                not isinstance(report["postgres_version"], str) or
                report["postgres_version"].split()[0] != "18.4" or
                any(type(report[k]) is not int or report[k] not in (0, 1)
                    for k in ("pytest_exit", "postgres_exit")) or
                type(report["files"]) is not dict or not 7 <= len(report["files"]) <= 200):
            raise ValueError("schema")
        files, total = {}, 0
        for name, encoded in report["files"].items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", name) or type(encoded) is not str:
                raise ValueError("file_name")
            blob = base64.b64decode(encoded, validate=True)
            total += len(blob)
            if total > 1_900_000:
                raise ValueError("raw_size")
            files[name] = blob
        if not {"pytest.xml", "junit.xml", "execution.json", "results.json", "pytest.log",
                "suite.log", "postgres.log", "setup.log"} <= files.keys():
            raise ValueError("missing_raw")
        root = ET.Element("testsuites")
        for filename, name, rc in (("pytest.xml", "pytest", "pytest_exit"),
                                    ("junit.xml", "isolated_postgres", "postgres_exit")):
            parsed = ET.fromstring(files[filename])
            if name == "pytest":
                if parsed.tag != "testsuites" or len(parsed) != 1:
                    raise ValueError("pytest_suite")
                suite = parsed[0]
            else:
                suite = parsed
            if suite.tag != "testsuite":
                raise ValueError("suite")
            suite.set("name", name)
            for attr in ("errors", "skipped"):
                if attr not in suite.attrib:
                    suite.set(attr, str(len(suite.findall("testcase/" + ("error" if attr == "errors" else "skipped")))))
            has_failure = any(int(suite.get(k, "-1")) > 0 for k in ("failures", "errors"))
            if (report[rc] == 0) == has_failure:
                raise ValueError("exit_junit_mismatch")
            root.append(suite)
        junit = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        counts = frozen_junit_counts(junit)
        execution, results = json.loads(files["execution.json"]), json.loads(files["results.json"])
        pg_failed = int(root[1].get("failures"))
        if (execution.get("source_commit") != CANDIDATE or execution.get("database_backend") != "postgresql" or
                execution.get("postgres_server_version") != report["postgres_version"] or
                execution.get("tests") != 10 or execution.get("failures") != pg_failed or
                execution.get("status") != ("TEST_FAILED" if pg_failed else "EVIDENCE_READY") or
                type(results) is not list or len(results) != 10):
            raise ValueError("postgres_execution")
        expected_results = {case.get("name"): "FAIL" if case.find("failure") is not None else "PASS"
                            for case in root[1].findall("testcase")}
        if ({r["case"]: r["status"] for r in results} != expected_results or
                (not pg_failed and execution.get("hard_death_auto_recovery") != "PASS")):
            raise ValueError("postgres_results")
        # stdout artifact is a length-delimited, lossless bundle of every raw file,
        # including both unmodified JUnits, subprocess/PG logs and SQL observations.
        chunks = [canonical({"contract": "GO_C14_RAW_LOG_BUNDLE_V1", "image_id": image_id,
                             "source_archive_sha256": source_digest, "counts": counts}) + b"\n"]
        for name, blob in sorted(files.items()):
            chunks += [canonical({"file": name, "bytes": len(blob), "sha256": digest(blob)}) + b"\n", blob, b"\n"]
        stdout = b"".join(chunks)
        if len(stdout) > 2_000_000:
            raise ValueError("raw_size")
        return {"candidate_sha": CANDIDATE, "application_tree": TREE, "test_scope_sha256": SCOPE,
                "postgres_version": "18.4", "network": False, "providers": False, "payments": False,
                "deployment": False, "production": False, "junit": junit, "stdout": stdout}
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, ET.ParseError, binascii.Error) as exc:
        raise Refusal("sandbox_raw_results") from exc


class DockerSandbox:
    def __init__(self, source_repository, image_id, docker_socket):
        self.repository = Path(source_repository)
        if (not self.repository.is_absolute() or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) or
                not re.fullmatch(r"/[A-Za-z0-9_./-]+\.sock", docker_socket) or ".." in docker_socket.split("/")):
            raise Refusal("sandbox_configuration")
        self.image_id = image_id
        self.docker = ["docker", "--host", "unix://" + docker_socket]
        self.env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent",
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0"}

    def _command(self, argv):
        return subprocess.run(argv, env=self.env, capture_output=True, timeout=30, check=True).stdout

    def _source_archive(self):
        prefix = ["git", "-C", str(self.repository)]
        actual = self._command(prefix + ["rev-parse", CANDIDATE + ":application"]).decode().strip()
        if actual != TREE:
            raise Refusal("sandbox_source")
        with tempfile.TemporaryFile() as stream:
            subprocess.run(prefix + ["archive", "--format=tar", CANDIDATE + ":application"],
                           env=self.env, stdout=stream, stderr=subprocess.PIPE, timeout=30, check=True)
            stream.seek(0)
            raw = stream.read(MAX_SOURCE + 1)
        if not 0 < len(raw) <= MAX_SOURCE:
            raise Refusal("sandbox_source")
        return raw

    def _check_container(self, info):
        c, h = info["Config"], info["HostConfig"]
        if (info["Image"] != self.image_id or c["User"] != "65532:65532" or
                c["Entrypoint"] != [ENTRYPOINT] or c["Cmd"] != ENTRY_ARGS or
                h["NetworkMode"] != "none" or h["ReadonlyRootfs"] is not True or
                h["Privileged"] is not False or h["CapDrop"] != ["ALL"] or
                h.get("CapAdd") or h.get("Binds") or h.get("Devices") or
                h.get("VolumesFrom") or h.get("PortBindings") or h.get("PublishAllPorts") or
                h.get("PidMode", "") not in ("", "private") or h.get("IpcMode") != "private" or
                h.get("Tmpfs") != TMPFS or h.get("Memory") != 2147483648 or
                h.get("MemorySwap") != 2147483648 or
                h.get("RestartPolicy") != {"Name": "no", "MaximumRetryCount": 0} or
                h.get("PidsLimit") != 128 or h.get("NanoCpus") != 2000000000 or
                h.get("SecurityOpt") != ["no-new-privileges"] or
                any(m.get("Type") != "tmpfs" for m in info.get("Mounts", []))):
            raise Refusal("sandbox_isolation")

    def run_fixed_isolated_suite(self, candidate, tree, commands):
        if (candidate, tree, commands) != (CANDIDATE, TREE, SCOPE_COMMANDS):
            raise Refusal("sandbox_scope")
        self.last_output = b""
        self.last_stderr = b""
        name = "go-c14-sandbox-" + uuid.uuid4().hex
        created = False
        try:
            archive = self._source_archive()
            image = json.loads(self._command(self.docker + ["image", "inspect", self.image_id]))[0]
            if (image["Id"] != self.image_id or
                    set(image["Config"].get("Volumes") or {}) != {"/var/lib/postgresql"}):
                raise Refusal("sandbox_image")
            argv = self.docker + ["create", "--name", name, "--pull=never", "--interactive",
                    "--network=none", "--read-only", "--user=65532:65532", "--cap-drop=ALL",
                    "--security-opt=no-new-privileges", "--ipc=private", "--pids-limit=128",
                    "--memory=2g", "--memory-swap=2g", "--restart=no", "--cpus=2", "--log-driver=none",
                    "--entrypoint", ENTRYPOINT]
            for target, options in TMPFS.items():
                argv += ["--tmpfs", target + ":" + options]
            # Record before create: a timeout can occur after the daemon created it.
            created = True
            self._command(argv + [self.image_id, *ENTRY_ARGS])
            self._check_container(json.loads(self._command(self.docker + ["inspect", name]))[0])
            with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
                proc = subprocess.Popen(self.docker + ["start", "--attach", "--interactive", name],
                                        env=self.env, stdin=subprocess.PIPE, stdout=output, stderr=errors)
                try:
                    proc.communicate(input=archive, timeout=3300)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                    raise Refusal("sandbox_timeout")
                finally:
                    # Capture before any refusal or post-exit inspect can fail.
                    # These bounded diagnostic prefixes are not complete evidence
                    # and must never be parsed/published as a passing test result.
                    output.seek(0)
                    self.last_output = output.read(MAX_OUTPUT + 1)
                    errors.seek(0)
                    self.last_stderr = errors.read(64000)
                state = json.loads(self._command(self.docker + ["inspect", name]))[0]["State"]
                if proc.returncode or state["Running"] or state["OOMKilled"] or state["ExitCode"] != 0:
                    failure = Refusal("sandbox_process")
                    failure.add_note(self.last_stderr[:4000].decode("utf-8", errors="replace"))
                    raise failure
                return parse_output(self.last_output, self.image_id, digest(archive))
        except Refusal:
            raise
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise Refusal("sandbox_host") from exc
        finally:
            if created:
                # No --rm race, no task replay. Removal failure is itself a refusal.
                try:
                    self._command(self.docker + ["rm", "--force", "--volumes", name])
                except (OSError, subprocess.SubprocessError) as exc:
                    raise Refusal("sandbox_cleanup") from exc
