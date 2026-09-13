from __future__ import annotations
import pathlib, re
ROOT=pathlib.Path(__file__).resolve().parents[1]
bad=[]
for base in (ROOT/'deploy', ROOT/'scripts'):
    for path in base.rglob('*') if base.exists() else []:
        if not path.is_file() or path.name == pathlib.Path(__file__).name:
            continue
        if path.suffix not in {'.sh','.py'}:
            continue
        try: lines=path.read_text(encoding='utf-8').splitlines()
        except UnicodeDecodeError: continue
        for n,line in enumerate(lines,1):
            stripped=line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            # Ignore scanners/documentation strings; detect executable invocations only.
            if 'grep ' in stripped or 're.search' in stripped or 'pattern' in stripped.lower():
                continue
            if re.search(r'(^|[;&|]\s*)alembic\s+stamp\b', stripped) or re.search(r'\bcommand\.stamp\s*\(', stripped):
                bad.append(f'{path.relative_to(ROOT)}:{n}:{stripped}')
if bad:
    print('R8.2_NO_STAMP_GATE: BLOCK')
    print('\n'.join(bad))
    raise SystemExit(1)
print('R8.2_NO_STAMP_GATE: PASS')
