"""C2-C14 service configuration. No caller-selected paths, providers or workflow.

The installed service chooses its cell. Tasks cannot select a service's identity.
C1 continues using its existing services and outbox, preventing a second C1 owner.
"""
import argparse
import os

from c1_execution_contract import Refused, canonical_cell_id


def cell_config(cell, environ=None):
    env = os.environ if environ is None else environ
    cell = canonical_cell_id(cell)
    if cell == "C1":
        raise Refused("C1_USE_EXISTING_SERVICE")
    prefix = "C%02d" % int(cell[1:])
    enabled = str(env.get(prefix + "_RUNTIME_INGRESS_ENABLED", "")).strip().lower() == "true"
    authors = tuple(a.strip() for a in env.get("CELL_TASK_AUTHORS", "").split(",") if a.strip())
    return {"cell": cell, "enabled": enabled, "authors": authors,
            "worker_id": "go-runtime-host-cell-%s-worker" % cell.lower(),
            "outbox": "/var/lib/go-runtime-cells/%s/outbox.db" % cell.lower()}


def arguments(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cell", required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--once", action="store_true")
    modes.add_argument("--check", action="store_true")
    return parser.parse_args(argv)
