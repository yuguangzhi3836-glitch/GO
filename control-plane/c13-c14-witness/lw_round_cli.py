"""Local driver for one full-chain round.

The local side does three things and nothing else: freeze a round for a real
candidate, aggregate the two witnesses the hosts signed, and print the answer. It
never signs anything and never holds a private key.

    prepare   --repo <worktree> --rev origin/main --out <dir>/task_package.json
    finalise  --package <dir>/task_package.json --cc-witness <file> [--hk-witness <file>]
              --out <dir>/round.json

``finalise`` re-derives the verification locally from the same package, so the
aggregation compares the witnesses against a verification this process computed
rather than one it was handed.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import lw_paths  # noqa: E402

lw_paths.install()

import lw_chain  # noqa: E402
import lw_witness  # noqa: E402


def cmd_prepare(args) -> int:
    package = lw_chain.prepare_task_package(repo_root=args.repo, rev=args.rev, now=args.now)
    lw_chain.dump_package(package, args.out)
    print(json.dumps({
        "task": package["task"],
        "candidate_sha": package["candidate"]["sha"],
        "application_tree": package["candidate"]["application_tree"],
        "candidate_source": package["candidate"]["source"],
        "execution_carrier": package["execution_carrier"],
        "artifact_binding": package["artifact_binding"],
        "artifacts": package["artifact_names"],
        "now": package["now"],
        "package": str(args.out),
    }, ensure_ascii=False))
    return 0


def cmd_finalise(args) -> int:
    package = lw_chain.load_package(args.package)
    verification = lw_chain.verify_from_package(package)
    cc_witness = json.loads(pathlib.Path(args.cc_witness).read_text(encoding="utf-8"))
    hk_witness = None
    if args.hk_witness:
        hk_witness = json.loads(pathlib.Path(args.hk_witness).read_text(encoding="utf-8"))

    if not verification.get("ok") or cc_witness is None:
        summary = lw_chain.summary(package=package, verification=verification,
                                   cc_witness=cc_witness, hk_witness=hk_witness)
        summary["error"] = "round_not_accepted"
        lw_chain.dump_package(summary, args.out)
        print(json.dumps(summary, ensure_ascii=False))
        return 1

    record = lw_chain.finalise(verification=verification, cc_witness=cc_witness,
                               hk_witness=hk_witness)
    summary = lw_chain.summary(package=package, verification=verification,
                               cc_witness=cc_witness, hk_witness=hk_witness, record=record)
    summary["final_acceptance"] = record
    lw_chain.dump_package(summary, args.out)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def cmd_inspect_ledger(args) -> int:
    """Build the first-seen ledger entry over the package's own real digests."""
    package = lw_chain.load_package(args.package)
    ledger = lw_witness.FirstSeenLedger()
    first = package["first_seen"]
    outcome_first = ledger.observe(first)
    outcome_again = ledger.observe(dict(first))
    tampered = dict(first)
    tampered["c14_root"] = "0" * 64
    outcome_tampered = ledger.observe(tampered)
    print(json.dumps({
        "first": outcome_first,
        "again": outcome_again,
        "tampered": outcome_tampered,
        "entries": len(ledger.entries),
        "LEDGER_ROOT": ledger.root(),
    }, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--repo", required=True, help="a worktree of the repository")
    prepare.add_argument("--rev", default="origin/main")
    prepare.add_argument("--now", help="freeze the round at this instant instead of now")
    prepare.add_argument("--out", required=True)
    prepare.set_defaults(func=cmd_prepare)

    finalise = sub.add_parser("finalise")
    finalise.add_argument("--package", required=True)
    finalise.add_argument("--cc-witness", required=True)
    finalise.add_argument("--hk-witness")
    finalise.add_argument("--out", required=True)
    finalise.set_defaults(func=cmd_finalise)

    ledger = sub.add_parser("ledger")
    ledger.add_argument("--package", required=True)
    ledger.set_defaults(func=cmd_inspect_ledger)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
