"""Fixed read-only graph identity program: no SQL, no application imports."""
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path('/workspace')

def graph(directory):
    result={}
    for path in sorted(directory.glob('*.py')):
        if path.name=='__init__.py': continue
        if path.is_symlink() or not path.is_file(): raise ValueError('MIGRATION_SOURCE_TYPE')
        values={}
        for node in ast.parse(path.read_text()).body:
            names=([v.id for v in node.targets if isinstance(v,ast.Name)] if isinstance(node,ast.Assign)
                   else [node.target.id] if isinstance(node,ast.AnnAssign) and isinstance(node.target,ast.Name) else [])
            for name in names:
                if name in ('revision','down_revision','depends_on'):
                    if name in values: raise ValueError('MIGRATION_DUPLICATE_IDENTITY')
                    values[name]=ast.literal_eval(node.value)
        revision=values.get('revision'); parent=values.get('down_revision')
        parents=() if parent is None else (parent,) if isinstance(parent,str) else parent
        if not isinstance(revision,str) or not revision or revision in result:
            raise ValueError('MIGRATION_REVISION')
        if not isinstance(parents,tuple) or any(not isinstance(p,str) or not p for p in parents):
            raise ValueError('MIGRATION_PARENTS')
        if values.get('depends_on') is not None: raise ValueError('MIGRATION_DEPENDENCY')
        result[revision]={'parents':parents,'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    return result

def ancestors(data,revision):
    seen=set();active=set();ordered=[]
    def visit(node):
        if node not in data or node in active: raise ValueError('MIGRATION_LINEAGE')
        if node in seen: return
        active.add(node)
        for parent in sorted(data[node]['parents']): visit(parent)
        active.remove(node);seen.add(node);ordered.append(node)
    visit(revision)
    return ordered

def check_source(spec,root=ROOT):
    if not isinstance(spec,dict) or set(spec)!={'revision','graph_sha256'}: raise ValueError('SAME_SOURCE_SPEC')
    data=graph(root/'alembic/versions')
    referenced={p for row in data.values() for p in row['parents']}
    if sorted(set(data)-referenced)!=[spec['revision']]: raise ValueError('SAME_SOURCE_HEAD')
    if set(ancestors(data,spec['revision']))!=set(data): raise ValueError('SAME_SOURCE_LINEAGE')
    auxiliary={}
    names={'alembic.ini','alembic/env.py'} | {str(p.relative_to(root)) for p in (root/'alembic').rglob('*.py')}
    for name in sorted(names):
        path=root/name
        if path.is_symlink() or not path.is_file(): raise ValueError('SAME_SOURCE_FILE')
        auxiliary[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    proof={'schema':'go.hk-migration-graph.v1','revision':spec['revision'],'graph':data,'auxiliary':auxiliary}
    digest=hashlib.sha256((json.dumps(proof,sort_keys=True,indent=2)+'\n').encode()).hexdigest()
    if digest!=spec['graph_sha256']: raise ValueError('SAME_SOURCE_DIGEST')
    return {'source':'PASS','revision':spec['revision'],'graph_sha256':digest,'migration_required':False}

def entry():
    try:
        if len(sys.argv)!=3 or sys.argv[1]!='source': raise ValueError('SAME_SOURCE_MODE')
        result=check_source(json.loads(sys.argv[2]))
        print(json.dumps(result,sort_keys=True,separators=(',',':')))
    except Exception:
        print('{"error":"SAME_SOURCE_REJECTED"}')
        raise SystemExit(2)
