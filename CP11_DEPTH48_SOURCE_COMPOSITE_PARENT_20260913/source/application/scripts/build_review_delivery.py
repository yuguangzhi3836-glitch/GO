#!/usr/bin/env python3
"""Package a reproducible engineering review copy; never promote release status."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'deliverables'

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def allowed(path):
    rel=path.relative_to(ROOT)
    if any(part in {'__pycache__','.pytest_cache','.git','node_modules','deliverables','runtime_data'} for part in rel.parts):return False
    if path.is_symlink():raise ValueError(f'UNREVIEWED_SYMLINK:{rel}')
    if path.suffix in {'.pyc','.pyo','.db','.sqlite','.sqlite3'} or path.name.endswith(('-wal','-shm','.pristine')):return False
    if path.name in {'.env','official_rooms_source.html'}:return False
    return path.is_file()

def zip_files(destination,files):
    # Use a temporary file so an existing durable checkpoint stays readable while rebuilding.
    temp=destination.with_suffix('.building')
    manifest={'status':'ENGINEERING_REVIEW_NOT_RELEASE_ACCEPTED','files':[]}
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in files:
            name=path.relative_to(ROOT).as_posix()
            archive.write(path,name)
            manifest['files'].append({'path':name,'size':path.stat().st_size,'sha256':digest(path)})
        archive.writestr('DELIVERY_FILE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(temp) as archive:
        bad=archive.testzip()
        if bad:raise ValueError(f'ZIP_CRC_FAILED:{bad}')
    temp.replace(destination)
    return {'path':str(destination),'size':destination.stat().st_size,'sha256':digest(destination),'entries':len(manifest['files'])+1}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full',action='store_true')
    parser.add_argument('--parts',action='store_true')
    parser.add_argument('--iteration',choices=['03','04','05','06','07','08','09','10','11','12','13','14','15','16'],default='16')
    args=parser.parse_args();OUT.mkdir(exist_ok=True)
    label={'03':'MASTER_ALIGNMENT','04':'VAULT_HARDENING','05':'FLIGHT_PARTY_REFUND','06':'RENTAL_DIRECT_SETTLEMENT','07':'DIRECT_MONEY_LEDGER','08':'HOTEL_FARE','09':'HOTEL_STAY_CREDIT','10':'HOTEL_SUPPLIER_REMEDY','11':'CATALOG_SUPPLIER_REMEDY','12':'CATALOG_STAY_CREDIT','13':'CATALOG_FARE_SNAPSHOT','14':'CATALOG_CASH_FARE','15':'CREDIT_SOURCE_EXCLUSION','16':'CURRENT_AUTONOMY_AUTHORITY'}[args.iteration]
    stem=f'GO_CP11_DEPTH_{args.iteration}_{label}_20260907'
    prefix=f'GO_MASTER{args.iteration}'
    files=sorted(p for p in ROOT.rglob('*') if allowed(p))
    runtime_delta=json.loads((ROOT/'acceptance/RUNTIME_DELTA.json').read_text())
    runtime_paths={entry['path'] for entry in runtime_delta['changed']}
    wheel_paths={entry['path'] for entry in runtime_delta['wheelhouse_changed']}
    for entry in runtime_delta['changed']+runtime_delta['wheelhouse_changed']:
        if digest(ROOT/entry['path'])!=entry['sha256']:
            raise ValueError('RUNTIME_DELTA_INDEX_STALE:'+entry['path'])
    work=[]
    for path in files:
        rel=path.relative_to(ROOT)
        if any(x in rel.parts for x in {'depth07','depth08','depth09','depth10','depth11','depth12','depth13','depth14','depth15','depth16'}) and (path.name.startswith('first_') or path.suffix=='.log'):continue
        if rel.parts[0] in {'src','frontend','tests','tests_frontend','scripts','acceptance','alembic'}:
            work.append(path)
        elif rel.parts[0]=='verification' and any(p in rel.parts for p in {'recovered_03','depth04','depth05','depth06','depth07','depth08','depth09','depth10','depth11','depth12','depth13','depth14','depth15','depth16'}) and path.name!='full_regression.log':work.append(path)
        elif rel.parts[0]=='gate_runtime' and (len(rel.parts)==2 and path.suffix in {'.json','.txt','.lock','.md'} or rel.as_posix() in wheel_paths or rel.as_posix() in runtime_paths):work.append(path)
        elif len(rel.parts)==1 and (path.name in {'pyproject.toml','alembic.ini','GO_MASTER03_START_HERE.md','GO_DEPTH04_START_HERE.md','GO_DEPTH05_START_HERE.md','GO_DEPTH06_START_HERE.md','GO_DEPTH07_START_HERE.md','GO_DEPTH08_START_HERE.md','GO_DEPTH09_START_HERE.md','GO_DEPTH10_START_HERE.md','GO_DEPTH11_START_HERE.md','GO_DEPTH12_START_HERE.md','GO_DEPTH13_START_HERE.md','GO_DEPTH14_START_HERE.md','GO_DEPTH15_START_HERE.md','GO_DEPTH16_START_HERE.md'} or path.name.startswith('GO_ULTIMATE_MASTER_PLAN_V7.0_')):work.append(path)
    results=[zip_files(OUT/f'GO_CP11_DEPTH_{args.iteration}_{label}_WORK_20260907.zip',work)]
    if args.full:
        full=OUT/(stem+'_CANDIDATE.zip');results.append(zip_files(full,files))
        if args.parts:
            with full.open('rb') as stream:
                i=0
                while block:=stream.read(40*1024*1024):
                    part=OUT/f'{prefix}.part{i:02d}';part.write_bytes(block)
                    results.append({'path':str(part),'size':len(block),'sha256':digest(part)})
                    i+=1
            manifest={'filename':full.name,'size':full.stat().st_size,'sha256':digest(full),
                'parts':[{'filename':Path(r['path']).name,'size':r['size'],'sha256':r['sha256']} for r in results if '.part' in r['path']]}
            (OUT/f'{prefix}_PARTS.json').write_text(json.dumps(manifest,indent=2))
    (OUT/f'{prefix}_DELIVERY_SHA256.txt').write_text(''.join(f"{r['sha256']}  {Path(r['path']).name}\n" for r in results))
    print(json.dumps(results,indent=2))

if __name__=='__main__':main()
