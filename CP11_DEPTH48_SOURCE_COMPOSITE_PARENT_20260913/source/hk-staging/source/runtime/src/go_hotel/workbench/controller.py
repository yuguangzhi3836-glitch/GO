from __future__ import annotations
from .definitions import WORKSPACE_BY_ID
from .graph import DependencyGraph
from .types import WorkDirective, WorkItem

class WorkbenchViolation(ValueError):
    pass

class ParallelWorkbench:
    def __init__(self):
        self.graph = DependencyGraph()

    def decompose(self, directive: WorkDirective, scopes: dict[str, tuple[str, ...]], dependencies: dict[str, tuple[str, ...]] | None = None) -> tuple[WorkItem, ...]:
        dependencies = dependencies or {}
        items = []
        for cell_id in directive.requested_cells:
            if cell_id not in WORKSPACE_BY_ID:
                raise WorkbenchViolation(f"UNKNOWN_CELL:{cell_id}")
            workspace = WORKSPACE_BY_ID[cell_id]
            change_scope = tuple(scopes.get(cell_id, ()))
            if not change_scope:
                raise WorkbenchViolation(f"EMPTY_SCOPE:{cell_id}")
            for path in change_scope:
                if workspace.forbidden(path):
                    raise WorkbenchViolation(f"FORBIDDEN_PATH:{cell_id}:{path}")
                if not workspace.owns(path):
                    raise WorkbenchViolation(f"PATH_NOT_OWNED:{cell_id}:{path}")
            item_id = f"{directive.directive_id}:{cell_id}"
            self.graph.add_node(item_id)
            items.append(WorkItem(
                work_item_id=item_id,
                directive_id=directive.directive_id,
                cell_id=cell_id,
                branch=f"{workspace.branch_prefix}/{directive.directive_id.lower()}",
                worktree=f"{workspace.worktree_prefix}/{directive.directive_id.lower()}",
                change_scope=change_scope,
                contract_dependencies=tuple(dependencies.get(cell_id, ())),
            ))
        by_cell = {i.cell_id: i.work_item_id for i in items}
        for cell_id, deps in dependencies.items():
            if cell_id not in by_cell:
                continue
            for dep_cell in deps:
                if dep_cell not in by_cell:
                    raise WorkbenchViolation(f"DEPENDENCY_CELL_NOT_ASSIGNED:{cell_id}:{dep_cell}")
                self.graph.add_dependency(by_cell[cell_id], by_cell[dep_cell])
        return tuple(items)
