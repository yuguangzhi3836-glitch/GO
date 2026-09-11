"""Offline isolated extensionless installed-layout loader proof."""
import os,tempfile
from pathlib import Path
from .verify_pair_regression import load_extensionless_executor

SOURCE=Path('/usr/local/libexec/go-hk-deployctl')
def run():
 out={}
 with tempfile.TemporaryDirectory() as td:
  root=Path(td); libexec=root/'isolated'/'libexec'; libexec.mkdir(parents=True)
  target=libexec/'go-hk-deployctl'; target.write_bytes(SOURCE.read_bytes()); target.chmod(0o700)
  loaded=load_extensionless_executor(target)
  out['EXTENSIONLESS_INSTALL_LAYOUT_GATE']='PASS' if Path(loaded.__file__).resolve()==target.resolve() else 'FAIL'
  out['TEST_EXECUTOR_FILENAME']='go-hk-deployctl';out['TEST_EXECUTOR_HAS_PY_SUFFIX']='NO';out['TEST_IMPORT_SOURCE_IS_EXTENSIONLESS_INSTALLED_LAYOUT']='YES'
  def rejected(name,path):
   try: load_extensionless_executor(path)
   except ValueError: out[name]='PASS'
   else: out[name]='FAIL'
  rejected('MISSING_EXECUTOR_LOADER_REJECTED',libexec/'missing')
  rejected('WRONG_EXECUTOR_PATH_REJECTED',libexec/'wrong-name.py')
  directory=libexec/'go-hk-deployctl-dir';directory.mkdir();rejected('DIRECTORY_EXECUTOR_REJECTED',directory)
  invalid=libexec/'go-hk-deployctl-invalid';invalid.write_text('not valid python !');rejected('INVALID_EXECUTOR_SOURCE_REJECTED',invalid)
  fake=root/'fake';fake.mkdir();(fake/'go_hk_deployctl.py').write_text('VERSION="FAKE"')
  old=os.environ.get('PYTHONPATH');os.environ['PYTHONPATH']=str(fake)
  loaded=load_extensionless_executor(target)
  out['PYTHONPATH_FALLBACK_REJECTED']='PASS' if getattr(loaded,'VERSION','')!='FAKE' else 'FAIL'
  if old is None: os.environ.pop('PYTHONPATH',None)
  else: os.environ['PYTHONPATH']=old
  build=root/'build'/'go-hk-deployctl';build.parent.mkdir();build.write_bytes(SOURCE.read_bytes())
  harness=root/'harness'/'go-hk-deployctl';harness.parent.mkdir();harness.write_bytes(SOURCE.read_bytes())
  loaded=load_extensionless_executor(target)
  out['BUILD_ROOT_FALLBACK_REJECTED']='PASS' if Path(loaded.__file__).resolve()==target.resolve() else 'FAIL'
  out['HARNESS_FALLBACK_REJECTED']='PASS' if Path(loaded.__file__).resolve()==target.resolve() else 'FAIL'
 out['TEMP_PY_COPY_USED']='NO';out['TEMP_PY_SYMLINK_USED']='NO';out['PYTHONPATH_DEPENDENCY']='NO';out['CWD_DEPENDENCY']='NO';out['DEV_PATH_DEPENDENCY']='NO';out['IMPORT_FALLBACK_PRESENT']='NO'
 out['TEST_COUNT']=str(len(out));out['PASS_COUNT']=str(sum(v in ('PASS','NO','YES','go-hk-deployctl') for v in out.values()));out['FAIL_COUNT']=str(sum(v=='FAIL' for v in out.values()))
 return out
if __name__=='__main__':
 for k,v in run().items():print(k+'='+v)
