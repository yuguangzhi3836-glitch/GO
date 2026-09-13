from __future__ import annotations
from collections import defaultdict, deque

class DependencyGraphError(ValueError):
    pass

class DependencyGraph:
    def __init__(self):
        self._edges = defaultdict(set)
        self._nodes = set()

    def add_node(self, node: str) -> None:
        self._nodes.add(node)

    def add_dependency(self, item: str, depends_on: str) -> None:
        if item == depends_on:
            raise DependencyGraphError("SELF_DEPENDENCY")
        self._nodes.update((item, depends_on))
        self._edges[depends_on].add(item)
        self.topological_order()  # fail fast on cycle

    def topological_order(self) -> tuple[str, ...]:
        indeg = {n: 0 for n in self._nodes}
        for src, targets in self._edges.items():
            for t in targets:
                indeg[t] += 1
        q = deque(sorted(n for n,d in indeg.items() if d == 0))
        out = []
        while q:
            n = q.popleft()
            out.append(n)
            for t in sorted(self._edges.get(n, ())):
                indeg[t] -= 1
                if indeg[t] == 0:
                    q.append(t)
        if len(out) != len(self._nodes):
            raise DependencyGraphError("DEPENDENCY_CYCLE")
        return tuple(out)
