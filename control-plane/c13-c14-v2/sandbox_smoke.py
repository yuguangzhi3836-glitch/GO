"""Development-only real container integration. Does not issue a Task or AI review."""
import argparse
import base64
import json
from pathlib import Path

from c13_attestation import CANDIDATE, TREE
from c14_isolated_runner import SCOPE_COMMANDS
from docker_sandbox import DockerSandbox
from house_bridge import canonical, digest, frozen_junit_counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--image-id-file", required=True)
    parser.add_argument("--docker-socket", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    image_id = Path(args.image_id_file).read_text().strip()
    sandbox = DockerSandbox(args.source_repository, image_id, args.docker_socket)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    try:
        result = sandbox.run_fixed_isolated_suite(CANDIDATE, TREE, SCOPE_COMMANDS)
    except Exception:
        raw = getattr(sandbox, "last_output", b"")
        (out / "rejected-output.json").write_bytes(raw)
        (out / "sandbox-stderr.log").write_bytes(getattr(sandbox, "last_stderr", b""))
        # Diagnostics remain rejected, never converted to passing evidence.
        try:
            rejected = json.loads(raw)
            print("Rejected sandbox result metadata:", {k: v for k, v in rejected.items() if k != "files"})
            for name in ("pytest.log", "suite.log", "execution.json"):
                blob = base64.b64decode(rejected.get("files", {}).get(name, ""), validate=True)
                print("Rejected raw diagnostic:", name, blob[-8000:].decode("utf-8", errors="replace"))
        except (ValueError, TypeError, AttributeError):
            pass
        raise
    for name in ("junit", "stdout"):
        (out / name).write_bytes(result[name])
    counts = frozen_junit_counts(result["junit"])
    record = {"development_integration_only": True, "C14": "NOT_EXECUTED", "AI_review": "NOT_CREATED",
              "image_id": image_id, "candidate_sha": CANDIDATE, "application_tree": TREE, "counts": counts,
              "junit_sha256": digest(result["junit"]), "stdout_sha256": digest(result["stdout"])}
    (out / "readback.json").write_bytes(canonical(record) + b"\n")
    print(canonical(record).decode())
    return 0 if counts == [71, 0, 0, 0] else 1


if __name__ == "__main__":
    raise SystemExit(main())
