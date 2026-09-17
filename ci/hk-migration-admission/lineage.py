"""Inspect immutable Alembic source without importing migration code."""
import ast
import hashlib
import json
from pathlib import Path

class Refused(ValueError):
    pass

def read_graph(directory):
    graph = {}
    for path in sorted(Path(directory).glob('*.py')):
        if path.name == '__init__.py':
            continue
        values = {}
        for node in ast.parse(path.read_text(), filename=str(path)).body:
            if isinstance(node, ast.Assign):
                names = [n.id for n in node.targets if isinstance(n, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names = [node.target.id]
            else:
                continue
            for name in names:
                if name in {'revision', 'down_revision', 'depends_on'}:
                    try:
                        values[name] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        raise Refused('DYNAMIC_MIGRATION_IDENTITY') from None
        revision = values.get('revision')
        if not isinstance(revision, str) or not revision or revision in graph:
            raise Refused('MISSING_OR_DUPLICATE_REVISION')
        parent = values.get('down_revision')
        parents = () if parent is None else ((parent,) if isinstance(parent, str) else parent)
        if not isinstance(parents, tuple) or any(not isinstance(p, str) or not p for p in parents):
            raise Refused('INVALID_PARENTS')
        if values.get('depends_on') is not None:
            raise Refused('DEPENDENCY_LINEAGE_REQUIRES_REVIEW')
        graph[revision] = {'parents': parents, 'file': path.name,
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    if not graph:
        raise Refused('EMPTY_MIGRATION_GRAPH')
    return graph

def ordered_ancestors(graph, revision):
    visited, active, ordered = set(), set(), []
    def visit(node):
        if node not in graph:
            raise Refused('MISSING_PARENT')
        if node in active:
            raise Refused('MIGRATION_CYCLE')
        if node in visited:
            return
        active.add(node)
        for parent in sorted(graph[node]['parents']):
            visit(parent)
        active.remove(node); visited.add(node); ordered.append(node)
    visit(revision)
    return ordered

def forward_path(graph, baseline, target):
    referenced = {p for entry in graph.values() for p in entry['parents']}
    if sorted(set(graph) - referenced) != [target]:
        raise Refused('SINGLE_EXPECTED_HEAD_REQUIRED')
    before = ordered_ancestors(graph, baseline)
    after = ordered_ancestors(graph, target)
    if set(after) != set(graph):
        raise Refused('DISCONNECTED_MIGRATION_GRAPH')
    if baseline not in after:
        raise Refused('BASELINE_NOT_ANCESTOR')
    return [r for r in after if r not in set(before)]

def lineage_digest(graph):
    payload=[{'revision':revision,'parents':list(sorted(entry['parents'])),
              'sha256':entry['sha256']} for revision,entry in sorted(graph.items())]
    raw=json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(raw).hexdigest()
