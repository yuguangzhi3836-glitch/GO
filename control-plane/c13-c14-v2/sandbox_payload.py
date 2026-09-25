"""Fixed suite entrypoint inside the disposable container; no host credentials."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import resource
import subprocess
import sys
import tarfile

CANDIDATE = "d4376d6ae9a58eca3c7c32968ec96dffc5574122"
TREE = "bee89f356a43bf3445d2da3f60f64f7db02a28cd"
MAX_SOURCE = 64_000_000
MAX_LOGS = 2_000_000


def git_object(kind, raw):
    return hashlib.sha1(kind + b" " + str(len(raw)).encode() + b"\0" + raw).digest()


def unpack_source(raw, destination, expected_tree=TREE):
    """Verify Git tree from archive bytes before extracting any source file."""
    if not 0 < len(raw) <= MAX_SOURCE:
        raise ValueError("source_size")
    files, nodes, total = {}, {}, 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for item in archive:
            path = PurePosixPath(item.name)
            if (path.is_absolute() or ".." in path.parts or not path.parts or
                    str(path) != item.name.rstrip("/") or "\\" in item.name):
                raise ValueError("source_path")
            if item.isdir():
                continue
            if not item.isfile() or item.name in files or item.size < 0:
                raise ValueError("source_type")
            total += item.size
            if total > MAX_SOURCE or len(files) >= 10000:
                raise ValueError("source_size")
            blob = archive.extractfile(item).read()
            if len(blob) != item.size:
                raise ValueError("source_size")
            mode = b"100755" if item.mode & 0o111 else b"100644"
            files[item.name] = (blob, mode)
            node = nodes
            for part in path.parts[:-1]:
                child = node.setdefault(part, {})
                if not isinstance(child, dict):
                    raise ValueError("source_collision")
                node = child
            if path.name in node:
                raise ValueError("source_collision")
            node[path.name] = (blob, mode)

    def tree_digest(node):
        chunks = []
        for name, value in sorted(node.items(), key=lambda p: p[0].encode() + (b"/" if isinstance(p[1], dict) else b"")):
            if isinstance(value, dict):
                mode, oid = b"40000", tree_digest(value)
            else:
                blob, mode = value
                oid = git_object(b"blob", blob)
            chunks.append(mode + b" " + name.encode() + b"\0" + oid)
        return git_object(b"tree", b"".join(chunks))

    if tree_digest(nodes).hex() != expected_tree:
        raise ValueError("source_tree")
    destination.mkdir()
    for name, (blob, mode) in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        target.chmod(0o555 if mode == b"100755" else 0o444)
    return expected_tree


def suite_environment(source):
    # Match the frozen developer CI's PYTHONPATH=src:. for cross-test imports.
    return {"PATH": "/opt/venv/bin:/usr/lib/postgresql/18/bin:/usr/bin:/bin",
           "HOME": "/work", "TMPDIR": "/tmp", "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(source / "src") + ":" + str(source),
           "APP_ENV": "test", "GO_C11_SOURCE_COMMIT": CANDIDATE,
           "GO_TEST_DB_PATH": "/work/pytest.db",
           "GO_C11_RUNTIME_DATABASE_URL": "postgresql+psycopg://c14@127.0.0.1:5432/go_c11_isolated"}


def main():
    # Bound each child-written file too; total tmpfs size is enforced by Docker.
    # PostgreSQL's default WAL segment is 16 MiB; allow it within bounded tmpfs.
    resource.setrlimit(resource.RLIMIT_FSIZE, (64_000_000, 64_000_000))
    work = Path("/work")
    source = work / "application"
    unpack_source(sys.stdin.buffer.read(MAX_SOURCE + 1), source)
    out = work / "evidence"
    out.mkdir()
    env = suite_environment(source)

    def run(argv, logfile, cwd=work, check=True):
        with (out / logfile).open("ab") as stream:
            result = subprocess.run(argv, cwd=cwd, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=3000)
        if check and result.returncode:
            raise RuntimeError("sandbox_process_failed:" + logfile)
        return result.returncode

    run(["initdb", "-D", "/work/pg", "--auth=trust", "--no-locale", "--encoding=UTF8"], "setup.log")
    run(["pg_ctl", "-D", "/work/pg", "-l", str(out / "postgres.log"), "-o",
         "-h 127.0.0.1 -k /tmp -p 5432", "-w", "start"], "setup.log")
    try:
        run(["createdb", "-h", "127.0.0.1", "go_c11_isolated"], "setup.log")
        version = subprocess.check_output(["psql", "-h", "127.0.0.1", "-d", "go_c11_isolated",
                                          "-Atc", "SHOW server_version"], env=env, timeout=15).decode().strip()
        if version.split()[0] != "18.4":
            raise RuntimeError("postgres_version")
        pytest_rc = run(["pytest", "-q", "--junitxml=" + str(out / "pytest.xml"),
                         "tests/payments/test_c11_flight_idempotency_recovery.py",
                         "tests/test_depth48_flight_changes.py"], "pytest.log", source, False)
        pg_rc = run(["python", "-B", "ci/next_depth/c11_postgres.py", "--evidence-dir", str(out)],
                    "suite.log", source, False)
    finally:
        run(["pg_ctl", "-D", "/work/pg", "-m", "immediate", "-w", "stop"], "setup.log")
    files, total = {}, 0
    for path in sorted(out.iterdir()):
        if path.is_symlink() or not path.is_file():
            raise ValueError("output_type")
        total += path.stat().st_size
        if total > MAX_LOGS:
            raise ValueError("output_size")
        files[path.name] = base64.b64encode(path.read_bytes()).decode()
    result = {"contract": "GO_C14_SANDBOX_OUTPUT_V1", "candidate_sha": CANDIDATE,
              "application_tree": TREE, "postgres_version": version,
              "pytest_exit": pytest_rc, "postgres_exit": pg_rc, "files": files}
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
