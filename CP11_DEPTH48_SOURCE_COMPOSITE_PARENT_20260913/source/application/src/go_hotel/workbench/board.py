from __future__ import annotations
from dataclasses import dataclass
from .definitions import WORKBENCH_POLICY, WORKSPACES
from .types import GateStatus, WorkItem

@dataclass(frozen=True)
class BoardSnapshot:
    master_version: str
    build: str
    cell_states: dict[str, str]
    gate_states: dict[str, str]
    merge_ready: tuple[str, ...]

def snapshot(items: tuple[WorkItem, ...] = (), gate_states: dict[str, GateStatus] | None = None, merge_ready: tuple[str, ...] = ()) -> BoardSnapshot:
    states = {w.cell_id: "IDLE" for w in WORKSPACES}
    for item in items:
        states[item.cell_id] = item.status.value
    return BoardSnapshot(
        master_version=WORKBENCH_POLICY["master_version"],
        build=WORKBENCH_POLICY["build"],
        cell_states=states,
        gate_states={k:v.value for k,v in (gate_states or {}).items()},
        merge_ready=merge_ready,
    )
