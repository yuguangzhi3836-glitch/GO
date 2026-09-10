"""Build checksums for the evidence archive, excluding reconstructed ZIPs/caches."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PREFIX='deliverables/CP11_DEPTH36R3_INDEPENDENT_CI_20260910/'

def files():
    return sorted(p for p in ROOT.rglob('*') if p.is_file()
                  and '__pycache__' not in p.parts and p.suffix not in {'.zip','.pyc'}
                  and p.name!='SHA256SUMS')

def main():
    paths=files()
    checks=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(ROOT).as_posix()+'\n' for p in paths)
    (ROOT/'SHA256SUMS').write_text(checks)
    paths.append(ROOT/'SHA256SUMS')
    entries=[]
    for p in paths:
        data=p.read_bytes()
        relative=p.relative_to(ROOT).as_posix()
        gitsha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        entries.append({'local':str(p),'path':PREFIX+relative,'bytes':len(data),
                        'sha256':hashlib.sha256(data).hexdigest(),'git_blob_sha':gitsha})
        if relative.startswith('handoff/'):
            entries.append({**entries[-1],'path':'docs/acceptance/'+p.name})
    print(json.dumps({'entries':entries,'repository_paths':len(entries),
                      'unique_blobs':len({x['git_blob_sha'] for x in entries}),
                      'archive_files':len(paths)},indent=2))

if __name__=='__main__':
    main()
