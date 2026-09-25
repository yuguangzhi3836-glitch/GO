"""Development-only real container integration. Does not issue a Task or AI review."""
import argparse
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
    result = sandbox.run_fixed_isolated_suite(CANDIDATE, TREE, SCOPE_COMMANDS)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
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
