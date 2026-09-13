from pathlib import Path
import ast
import re

ROOT=Path(__file__).resolve().parents[1]

# Alembic revision identifiers: deployed RDS version table uses VARCHAR(32).
# Historical over-length revisions are immutable migration history: never rename/delete them.
legacy_file=ROOT/'staging'/'alembic_revision_legacy_overlength.txt'
legacy_overlength={x.strip() for x in legacy_file.read_text(encoding='utf-8').splitlines() if x.strip()} if legacy_file.exists() else set()
seen_legacy=set()
for p in (ROOT/'alembic'/'versions').glob('*.py'):
    tree=ast.parse(p.read_text(encoding='utf-8'))
    vals={}
    for n in tree.body:
        if isinstance(n,ast.Assign):
            for t in n.targets:
                if isinstance(t,ast.Name) and t.id in {'revision','down_revision'}:
                    try: vals[t.id]=ast.literal_eval(n.value)
                    except Exception: pass
    rev=vals.get('revision')
    if isinstance(rev,str) and len(rev)>32:
        if rev not in legacy_overlength:
            raise SystemExit(f'ALEMBIC_NEW_REVISION_TOO_LONG:{p.name}:{rev}')
        seen_legacy.add(rev)
if seen_legacy != legacy_overlength:
    missing=sorted(legacy_overlength-seen_legacy)
    raise SystemExit('ALEMBIC_APPLIED_HISTORY_REMOVED_OR_RENAMED:'+','.join(missing))

# Conservative explicit SQLAlchemy object-name scan. PostgreSQL max identifier is 63 bytes.
legacy_obj_file=ROOT/'staging'/'postgres_object_legacy_overlength.txt'
legacy_objects={x.strip() for x in legacy_obj_file.read_text(encoding='utf-8').splitlines() if x.strip()} if legacy_obj_file.exists() else set()
seen_objects=set()
patterns=[r"name=['\"]([^'\"]+)['\"]",r"op\.create_index\(['\"]([^'\"]+)['\"]",r"op\.create_unique_constraint\(['\"]([^'\"]+)['\"]",r"op\.create_foreign_key\(['\"]([^'\"]+)['\"]"]
for p in (ROOT/'alembic'/'versions').glob('*.py'):
    txt=p.read_text(encoding='utf-8')
    for pat in patterns:
        for name in re.findall(pat,txt):
            if len(name.encode('utf-8'))>63:
                if name not in legacy_objects:
                    raise SystemExit(f'POSTGRES_NEW_OBJECT_NAME_TOO_LONG:{p.name}:{name}')
                seen_objects.add(name)
if seen_objects != legacy_objects:
    missing=sorted(legacy_objects-seen_objects)
    raise SystemExit('POSTGRES_APPLIED_OBJECT_HISTORY_REMOVED_OR_RENAMED:'+','.join(missing))

# Container must contain every static frontend.
docker=(ROOT/'Dockerfile').read_text(encoding='utf-8')
if 'COPY frontend ./frontend' not in docker:
    raise SystemExit('DOCKER_FRONTEND_STATIC_MISSING')

print('R8.1_STAGING_STATIC_GATE: PASS')
