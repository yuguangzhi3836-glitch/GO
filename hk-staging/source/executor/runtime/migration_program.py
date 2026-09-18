"""Trusted fixed program run inside the exact sealed candidate, never caller SQL."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path('/workspace')
LOCK_KEY=7150403103

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
    data=graph(root/'alembic/versions')
    referenced={p for row in data.values() for p in row['parents']}
    if sorted(set(data)-referenced)!=[spec['target_revision']]: raise ValueError('MIGRATION_HEAD')
    old=ancestors(data,spec['baseline_revision']);new=ancestors(data,spec['target_revision'])
    if set(new)!=set(data) or spec['baseline_revision'] not in new: raise ValueError('MIGRATION_NOT_FORWARD')
    path=[r for r in new if r not in set(old)]
    if not path: raise ValueError('MIGRATION_EMPTY_PATH')
    proof={'baseline':{r:data[r] for r in old},'candidate':data,'forward_revisions':path,
           'historical_migration_retention':'PASS','migration_required':True,
           'atomic_transaction_claim':False,'concurrent_index_migration':'0135_journey_search_trigram'}
    digest=hashlib.sha256((json.dumps(proof,sort_keys=True,indent=2)+'\n').encode()).hexdigest()
    if digest!=spec['lineage_sha256']: raise ValueError('MIGRATION_SOURCE_DIGEST')
    return digest

def migrate(spec):
    from sqlalchemy import create_engine,text
    from go_hotel.core.config import settings
    import go_hotel
    if not all(str(Path(p).resolve()).startswith('/workspace/src/') for p in go_hotel.__path__):
        raise ValueError('MIGRATION_IMPORT_SOURCE')
    engine=create_engine(settings.database_url)
    if engine.url.get_backend_name()!='postgresql': raise ValueError('MIGRATION_DATABASE_KIND')
    # The fixed host-side env-file and Compose digests identify the HK DB. The
    # URL is never accepted as an argument, printed, or included in Evidence.
    with engine.connect() as connection:
        if not connection.execute(text('SELECT pg_try_advisory_lock(:key)'),{'key':LOCK_KEY}).scalar_one():
            raise ValueError('MIGRATION_BUSY')
        try:
            current=list(connection.execute(text('SELECT version_num FROM alembic_version')).scalars())
            if current!=[spec['baseline_revision']]: raise ValueError('RDS_PRESTATE_MISMATCH')
            connection.rollback()  # Session lock deliberately survives this.
            env=dict(os.environ,PGOPTIONS='-c statement_timeout=240000 -c lock_timeout=5000',
                     PYTHONPATH='/workspace/src',PYTHONDONTWRITEBYTECODE='1')
            result=subprocess.run(['/usr/local/bin/python','-m','alembic','upgrade',spec['target_revision']],
                                  cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                  timeout=240,check=False)
            # Do not emit SQL errors: drivers may echo URL/query/business data.
            if result.returncode: raise ValueError('ALEMBIC_FORWARD_FAILED')
            post=list(connection.execute(text('SELECT version_num FROM alembic_version')).scalars())
            if post!=[spec['target_revision']]: raise ValueError('RDS_POSTSTATE_MISMATCH')
        finally:
            connection.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':LOCK_KEY})
    return {'prestate':spec['baseline_revision'],'poststate':spec['target_revision']}

def entry():
    try:
        if len(sys.argv)!=3 or sys.argv[1] not in ('source','migrate'): raise ValueError('MIGRATION_MODE')
        spec=json.loads(sys.argv[2]);lineage=check_source(spec)
        result={'source':'PASS','lineage_sha256':lineage}
        if sys.argv[1]=='migrate': result.update(migrate(spec))
        print(json.dumps(result,sort_keys=True,separators=(',',':')))
    except Exception as exc:
        known={'MIGRATION_IMPORT_SOURCE','MIGRATION_DATABASE_KIND','MIGRATION_BUSY',
               'RDS_PRESTATE_MISMATCH','ALEMBIC_FORWARD_FAILED','RDS_POSTSTATE_MISMATCH',
               'MIGRATION_MODE','MIGRATION_SOURCE_DIGEST','MIGRATION_HEAD','MIGRATION_NOT_FORWARD'}
        reason=str(exc) if isinstance(exc,ValueError) and str(exc) in known else 'MIGRATION_PROGRAM_FAILED'
        print(json.dumps({'error':reason},separators=(',',':')))
        raise SystemExit(2)
