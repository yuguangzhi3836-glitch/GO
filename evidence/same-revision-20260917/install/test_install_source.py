"""Real temporary file replacement and injected rollback failures; no host calls."""
import contextlib
from contextlib import ExitStack
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('installer',Path(__file__).with_name('install_source.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class InstallTests(unittest.TestCase):
 def scenario(self,fail_restore=False,success=False):
  with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
   root=Path(tmp);backups=root/'backups';backups.mkdir()
   targets={};entries=[];contents={};before={}
   for i in range(2):
    p=root/('source'+str(i)+'.py');p.write_text('OLD = '+str(i)+'\n');p.chmod(0o640)
    name=p.name;targets[name]=str(p);old=m.info(str(p));before[str(p)]=old
    content='NEW = '+str(i)+'\n';contents[name]=content
    entries.append({'source':name,'target':str(p),'before':old,'sha256':m.digest(content.encode())})
   guard=root/'authority.json';guard.write_text('{}\n');guards={str(guard):m.info(str(guard))}
   ancestors={str(p):m.directory_info(p) for name in guards for p in Path(name).parents}
   manifest={'hosts':{'go-cc':{'files':entries,'guards':guards,'guard_ancestors':ancestors}}}
   package={'manifest':manifest,'files':contents}
   stack.enter_context(patch.object(m,'TARGETS',{'go-cc':targets}))
   stack.enter_context(patch.object(m,'MANIFEST_SHA256',m.digest(m.canonical(manifest))))
   stack.enter_context(patch.object(m,'safe_parent'))
   stack.enter_context(patch.object(m,'Path',side_effect=lambda v:backups if str(v)=='/var/backups' else Path(v)))
   actions=[];states={t:'active' for t in ['go-boss-request-bridge.timer','go-command-center-state-cycle.timer']}
   def state(unit):return states.get(unit,'inactive')
   def run(argv,check=True):
    actions.append(argv)
    if argv[:2]==['systemctl','stop']:states[argv[2]]='inactive'
    if argv[:2]==['systemctl','start']:states[argv[2]]='active'
    return NS(stdout='SMOKE_PASS',returncode=0)
   stack.enter_context(patch.object(m,'state',side_effect=state));stack.enter_context(patch.object(m,'run',side_effect=run))
   original_replace=os.replace;count=0
   def replace(src,dst):
    nonlocal count
    count+=1
    if not success and (count==2 or (fail_restore and count==3)):raise OSError('injected replace failure')
    return original_replace(src,dst)
   stack.enter_context(patch.object(m.os,'replace',side_effect=replace))
   with contextlib.redirect_stdout(io.StringIO()):
    if success:m.install(package,'go-cc',True)
    else:
     with self.assertRaises(OSError):m.install(package,'go-cc',True)
   receipt=json.loads(next(backups.glob('*/receipt.json')).read_text())
   starts=[a for a in actions if a[:2]==['systemctl','start']]
   if fail_restore:
    self.assertEqual(receipt['result'],'RECONCILIATION_REQUIRED');self.assertEqual(starts,[])
    self.assertTrue(receipt['timers_intentionally_held']);self.assertTrue(receipt['restore_errors'])
   elif success:
    self.assertEqual(receipt['result'],'SOURCE_INSTALLED_NO_ADMISSION_OR_DEPLOY');self.assertEqual(len(starts),2)
    for e in entries:self.assertEqual(m.info(e['target']),m.after_info(e))
   else:
    self.assertEqual(receipt['result'],'SOURCE_RESTORED');self.assertEqual(len(starts),2)
    self.assertEqual({p:m.info(p) for p in before},before)
   self.assertEqual({p:m.info(p) for p in guards},guards)
   self.assertTrue(next(backups.glob('*/BACKUP_MANIFEST.json')).is_file())

 def test_second_replace_failure_restores_all_before_images_and_permissions(self):self.scenario()
 def test_failed_restore_holds_timers_and_records_reconciliation(self):self.scenario(fail_restore=True)
 def test_success_restores_timer_state_and_preserves_permissions(self):self.scenario(success=True)
 def test_guard_ancestors_require_exact_metadata_without_requiring_root_owner(self):
  with tempfile.TemporaryDirectory() as tmp:
   f=Path(tmp)/'guard';f.write_text('{}');guards={str(f):m.info(str(f))}
   ancestors={str(p):m.directory_info(p) for p in f.parents}
   self.assertTrue(m.guard_check(guards,ancestors))
   changed={k:dict(v) for k,v in ancestors.items()};changed[str(f.parent)]['uid']+=1
   with self.assertRaises(ValueError):m.guard_check(guards,changed)
   changed={k:dict(v) for k,v in ancestors.items()};changed[str(f.parent)]['mode']^=0o020
   with self.assertRaises(ValueError):m.guard_check(guards,changed)
   changed=dict(ancestors);changed.pop('/')
   with self.assertRaises(ValueError):m.guard_check(guards,changed)
 def test_guard_ancestor_symlink_rejected_and_write_parent_remains_root_only(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);real=root/'real';real.mkdir();link=root/'link';link.symlink_to(real,target_is_directory=True)
   with self.assertRaises(ValueError):m.directory_info(link)
   real.chmod(0o777)
   with self.assertRaises(ValueError):m.safe_parent(real)


if __name__=='__main__':unittest.main()
