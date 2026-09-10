"""Preserve exact CI ZIPs as deduplicated Base64 parts and verify them offline.

Run verify_archive.py first, then this file. No network, installation or application execution.
The compressed source-bundle payload is shared by all four ZIPs. Splitting at its
byte boundaries preserves each original ZIP exactly without four duplicate copies.
"""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import struct
import zipfile

from verify_archive import ROOT, TREE, CANDIDATE, NAMES, require, sha, save, save_json

SOURCE_NAME = 'GO_DEPTH36R3_SOURCE_20260910.zip'
SOURCE_SHA = 'b4634f9da515a22f95fb740b979c2f77fdce29342eabbb9c54e5c666976f5b86'
CHUNK_SIZE = 1024 * 1024
SHARD_IDS = [10142597133,10142653019,10142752623,10142609313]

def pack(raw, start=None, end=None):
    ranges = [(0,len(raw))] if start is None else [(0,start),(start,end),(end,len(raw))]
    parts = []
    for first,last in ranges:
        for pos in range(first,last,CHUNK_SIZE):
            data = raw[pos:min(pos+CHUNK_SIZE,last)]
            digest = sha(data)
            relative = 'artifact-parts/'+digest+'.b64'
            save(relative, base64.b64encode(data)+b'\n')
            parts.append({'path':relative,'bytes':len(data),'sha256':digest})
    return parts

def unpack(item):
    chunks=[]
    for part in item['parts']:
        path = PurePosixPath(part['path'])
        require(not path.is_absolute() and '..' not in path.parts and path.parts[0]=='artifact-parts', 'Unsafe part path')
        raw=base64.b64decode((ROOT/path).read_bytes().strip(),validate=True)
        require(len(raw)==part['bytes'] and sha(raw)==part['sha256'],'Part mismatch')
        chunks.append(raw)
    raw=b''.join(chunks)
    require(len(raw)==item['bytes'] and sha(raw)==item['sha256'],'ZIP reconstruction mismatch')
    save(item['local_zip'],raw)
    return raw

def audit_artifacts():
    artifacts=json.loads((ROOT/'binding/artifacts.json').read_text())['artifacts']
    api={a['id']:a for a in artifacts}
    fp=json.loads((ROOT/'binding/SOURCE_FINGERPRINT.json').read_bytes())
    fp_tree=sha(''.join(f'{k}\0{v}\n' for k,v in sorted(fp.items())).encode())
    require(fp_tree==TREE and len(fp)==1267,'Fingerprint binding mismatch')
    sources=json.loads((ROOT/'binding/github-snapshot.json').read_text())['files']
    for source in sources:
        data=(ROOT/source['archive_path']).read_bytes()
        gitsha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        require(gitsha==source['git_blob_sha'],'Pinned Git blob mismatch')
    manifest_path=ROOT/'verification/artifact-parts.json'
    previous=json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    entries=[]
    for index,aid in enumerate(SHARD_IDS+[10142767710]):
        is_coverage=index==4
        relative='coverage/coverage.artifact.zip' if is_coverage else f'shards/{index}/artifact.zip'
        if (ROOT/relative).exists():
            raw=(ROOT/relative).read_bytes()
        else:
            require(previous is not None,'Missing ZIP and part manifest')
            raw=unpack(next(a for a in previous['artifacts'] if a['artifact_id']==aid))
        require(len(raw)==api[aid]['size_in_bytes'] and 'sha256:'+sha(raw)==api[aid]['digest'],'GitHub artifact digest mismatch')
        member_records=[]
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names=z.namelist()
            require(len(names)==len(set(names)),'Duplicate ZIP members')
            require(z.testzip() is None,'ZIP CRC mismatch')
            for name in names:
                p=PurePosixPath(name)
                require(not p.is_absolute() and len(p.parts)==1 and '..' not in p.parts,'Unsafe member')
                data=z.read(name)
                member_records.append({'name':name,'bytes':len(data),'sha256':sha(data)})
                if is_coverage:
                    require(name=='coverage.json','Unexpected coverage member')
                    save('coverage/coverage.original.json',data)
                    require(data==(ROOT/'coverage/coverage.from-log.json').read_bytes(),'Coverage artifact/log disagreement')
                elif name != SOURCE_NAME:
                    # All 10 framed files must match the downloaded originals byte-for-byte.
                    if name in NAMES:
                        require((ROOT/f'shards/{index}'/name).read_bytes()==data,'Artifact/frame disagreement')
                    save(f'shards/{index}/{name}',data)
                else:
                    require(sha(data)==SOURCE_SHA,'Source bundle SHA mismatch')
                    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
                        require(len(bundle.namelist())==1269 and len(set(bundle.namelist()))==1269,'Source bundle scope mismatch')
                        require(json.loads(bundle.read('SOURCE_FINGERPRINT.json'))==fp,'Bundle fingerprint mismatch')
                        require(set(bundle.namelist())=={'BUNDLE_MANIFEST.json','SOURCE_FINGERPRINT.json'}|{'source/'+n for n in fp},'Unexpected bundle files')
                        for path,expected in fp.items():
                            require(sha(bundle.read('source/'+path))==expected,'Source content mismatch: '+path)
            if is_coverage:
                parts=pack(raw)
            else:
                info=z.getinfo(SOURCE_NAME)
                n,e=struct.unpack_from('<HH',raw,info.header_offset+26)
                start=info.header_offset+30+n+e
                parts=pack(raw,start,start+info.compress_size)
        entry={'artifact_id':aid,'name':api[aid]['name'],'local_zip':relative,'bytes':len(raw),'sha256':sha(raw),
               'parts':parts,'members':member_records}
        require(unpack(entry)==raw,'Exact ZIP recovery failed')
        entries.append(entry)
    manifest={'schema':'go.ci-exact-artifact-parts.v1','run_id':34453179558,'chunk_size_max':CHUNK_SIZE,
              'encoding':'base64; concatenate decoded parts in listed order; verify SHA256 before opening',
              'artifacts':entries}
    save_json('verification/artifact-parts.json',manifest)
    result={'audit':'PASS','run_id':34453179558,'candidate':CANDIDATE,'source_tree_sha256':TREE,
            'artifact_zip_bytes_locally_verified':True,'artifacts_verified':5,
            'original_shard_member_count':27,'frame_files_compared_byte_for_byte':40,
            'coverage_artifact_equals_log_bytes':True,'source_bundle_sha256':SOURCE_SHA,
            'source_bundle_files_independently_hashed':1267,
            'exact_zip_reconstruction':'PASS','unique_base64_parts':len({p['path'] for a in entries for p in a['parts']}),
            'scope':'Offline artifact CRC/SHA256, original record comparison, source bundle content hashing; no application test, browser, Hong Kong connection or deployment',
            'three_end_real_ux_login':'HOLD','six_vertical_real_e2e':'HOLD','sealed_node_gate':'HOLD','final_release':'HOLD'}
    save_json('verification/artifact-audit.json',result)
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    audit_artifacts()
