"""Offline capacity arithmetic. Never opens a socket or sends test traffic."""
import argparse
import json
import math
from pathlib import Path


def number(value, name, minimum=0, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: expected number")
    if not math.isfinite(value) or value < minimum or (integer and int(value) != value):
        raise ValueError(f"{name}: invalid range")
    return value


def calculate(model):
    users = number(model["online_users"], "online_users", 1, True)
    interval = number(model["request_interval_seconds"], "request_interval_seconds", 0.001)
    peak = number(model["peak_multiplier"], "peak_multiplier", 1)
    reserve = number(model["capacity_reserve_fraction"], "capacity_reserve_fraction")
    if reserve >= 1:
        raise ValueError("capacity_reserve_fraction must be below 1")
    mix = model["request_mix"]
    if not mix or not math.isclose(sum(number(v, k) for k, v in mix.items()), 1.0, abs_tol=1e-9):
        raise ValueError("request_mix must sum to 1")
    steady = users / interval
    return {"status": "PLANNING_ONLY_NOT_BENCHMARK", "online_users": users,
            "steady_dynamic_rps": steady, "peak_dynamic_rps": steady * peak,
            "provisioned_rps_target": steady * peak / (1 - reserve),
            "peak_by_request_class": {k: steady * peak * v for k, v in mix.items()}}


def check_database_budget(budget):
    maximum = number(budget["server_max_connections"], "server_max_connections", 1, True)
    reserve = number(budget["reserved_connections"], "reserved_connections", 0, True)
    other = number(budget["other_connections"], "other_connections", 0, True)
    total = 0
    names = set()
    if not budget["services"]:
        raise ValueError("services must enumerate all pools sharing this database")
    for service in budget["services"]:
        name = service["name"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("service names must be nonempty and unique")
        names.add(name)
        replicas = number(service["max_replicas"], "max_replicas", 1, True)
        surge = number(service["rollout_surge_replicas"], "rollout_surge_replicas", 0, True)
        processes = number(service["processes_per_replica"], "processes_per_replica", 1, True)
        size = number(service["pool_size"], "pool_size", 1, True)
        overflow = number(service["max_overflow"], "max_overflow", 0, True)
        total += (replicas + surge) * processes * (size + overflow)
    available = maximum - reserve - other
    if available < 0 or total > available:
        raise ValueError(f"database budget exceeded: required={total}, available={available}")
    return {"status": "ARITHMETIC_PASS_NOT_RUNTIME_VERIFICATION", "required": total,
            "available": available, "headroom": available - total}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    args = parser.parse_args()
    source = json.loads(args.model.read_text())
    print(json.dumps({"traffic": calculate(source["traffic"]),
                      "database": check_database_budget(source["database"])}, indent=2))
