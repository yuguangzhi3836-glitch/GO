"""GitHub CI only: load exact archived base; build a new, offline compatibility image."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PARENT = 'sha256:9ec6ebaf962b6f5e880ecaa2e878a2ec1e51bfd0f1f4012b90aa709692d5057b'
ZIP_SHA = '715b939feb5529fcd97860ed921e5b292a874a2cbfacae0706a4da39023aad4f'
ARCHIVE_SHA = '68291f358733f4aabf87902e14771baf4a467b2346bc49c4a4701be9d39cd9a0'
TREE = '64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667'


def run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs).stdout.strip()


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'yuguangzhi3836-glitch/GO':
        raise RuntimeError('ISOLATED_GO_CI_ONLY')
    out = Path('compat-delivery'); out.mkdir()
    request = urllib.request.Request('https://api.github.com/repos/yuguangzhi3836-glitch/GO/actions/artifacts/10186084217/zip',
        headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'], 'Accept':'application/vnd.github+json'})
    try:
        response = urllib.request.build_opener(NoRedirect).open(request, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code not in (301,302,303,307,308):
            raise RuntimeError('PARENT_ARTIFACT_UNAVAILABLE') from None
        # The storage redirect receives no GitHub Authorization header.
        location = exc.headers['Location']
        if not location.startswith('https://'): raise RuntimeError('ARTIFACT_REDIRECT_SCHEME')
        response = urllib.request.urlopen(location, timeout=60)
    archive = Path('parent.zip')
    with response, archive.open('wb') as f: shutil.copyfileobj(response, f)
    if sha(archive) != ZIP_SHA: raise RuntimeError('PARENT_ZIP_HASH')
    parent = Path('compat-parent'); parent.mkdir()
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            path = Path(item.filename)
            if path.is_absolute() or '..' in path.parts or stat.S_ISLNK(item.external_attr >> 16):
                raise RuntimeError('UNSAFE_PARENT_MEMBER')
        z.extractall(parent)
    manifests = list(parent.rglob('RUNTIME_MANIFEST.json'))
    if len(manifests) != 1: raise RuntimeError('PARENT_LAYOUT')
    parent = manifests[0].parent
    original = run(sys.executable, '-B', str(parent/'verify_delivery.py'), '--directory', str(parent))
    (out/'PARENT_INTEGRITY.json').write_text(original+'\n')
    meta = json.loads((parent/'RUNTIME_PARTS.json').read_text())
    image_tar = Path('parent-image.tar.gz')
    with image_tar.open('wb') as f:
        for part in meta['parts']:
            with (parent/part['name']).open('rb') as source: shutil.copyfileobj(source,f)
    if sha(image_tar) != ARCHIVE_SHA: raise RuntimeError('PARENT_IMAGE_ARCHIVE_HASH')
    with gzip.open(image_tar,'rb') as stream:
        subprocess.run(['docker','load'],stdin=stream,check=True,stdout=subprocess.PIPE)
    if run('docker','image','inspect','go-depth40-staging:ci-34565938702','--format','{{.Id}}') != PARENT:
        raise RuntimeError('PARENT_CONFIG_ID')
    image = 'go-depth40-staging:compat-'+os.environ['GITHUB_RUN_ID']
    build = run('docker','build','--network','none','--pull=false','--tag',image,str(ROOT/'image'))
    (out/'BUILD.log').write_text(build+'\n')
    image_id = run('docker','image','inspect',image,'--format','{{.Id}}')
    if image_id == PARENT: raise RuntimeError('NEW_IMAGE_ID_REQUIRED')
    source_check = json.loads(run('docker','run','--rm','--network','none','--read-only',image,'source-check'))
    (out/'SOURCE_CHECK.json').write_text(json.dumps(source_check,indent=2)+'\n')
    if TREE not in json.dumps(source_check): raise RuntimeError('SOURCE_LINEAGE')
    content_sha = run('docker','run','--rm','--network','none','--read-only','--entrypoint','/opt/go/python/bin/python3.13',image,
        '-c',"import hashlib;print(hashlib.sha256(open('/opt/go/staging/preflight.py','rb').read()).hexdigest())")
    if content_sha != sha(ROOT/'image/preflight.py'): raise RuntimeError('PREFLIGHT_BINDING')
    # Export the new image under a new name. The frozen parent is never replaced.
    tar = out/'GO_DEPTH40_COMPAT_IMAGE.tar.gz'
    with tar.open('wb') as f:
        save = subprocess.Popen(['docker','save',image],stdout=subprocess.PIPE)
        with gzip.GzipFile(fileobj=f,mode='wb',mtime=0) as dest: shutil.copyfileobj(save.stdout,dest)
        if save.wait() != 0: raise RuntimeError('IMAGE_SAVE')
    # Offline reload proves the exported archive resolves to the new config ID.
    run('docker','image','rm',image)
    with gzip.open(tar,'rb') as stream: subprocess.run(['docker','load'],stdin=stream,check=True,stdout=subprocess.PIPE)
    if run('docker','image','inspect',image,'--format','{{.Id}}') != image_id: raise RuntimeError('RELOAD_BINDING')
    result = {'schema_version':'1','revision':'DEPTH40_COMPAT_V2','parent_candidate':'CP11_DEPTH40_P03_PARENT_20260911',
        'parent_image_id':PARENT,'parent_zip_sha256':ZIP_SHA,'source_tree_sha256':TREE,'source_files':1271,
        'image_tag':image,'image_config_id':image_id,'image_archive_sha256':sha(tar),'image_archive_bytes':tar.stat().st_size,
        'preflight_sha256':content_sha,'registry_repo_digest':None,'tooling_commit':os.environ['GO_TOOLING_SHA'],
        'ci_run_id':os.environ['GITHUB_RUN_ID'],'image_build':'PASS','offline_reload':'PASS',
        'hk_execution':'NOT_RUN','site_binding':'UNBOUND','deployment_authorized':False,'final_release':'HOLD'}
    (out/'RUNTIME_MANIFEST.json').write_text(json.dumps(result,indent=2)+'\n')
    Path(os.environ['GITHUB_ENV']).open('a').write('COMPAT_IMAGE='+image+'\n')
    print(json.dumps(result))


if __name__ == '__main__': main()
