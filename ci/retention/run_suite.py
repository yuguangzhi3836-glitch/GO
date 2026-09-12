"""Run all Python test files exactly once across deterministic isolated shards."""
import argparse
import json
import os
import pathlib
import subprocess
import sys

p=argparse.ArgumentParser()
p.add_argument('--shard',type=int,required=True)
p.add_argument('--count',type=int,default=4)
p.add_argument('--evidence',type=pathlib.Path,required=True)
a=p.parse_args()
assert 0 <= a.shard < a.count
root=pathlib.Path(__file__).resolve().parents[2]
app=root/'application'
files=sorted(str(x.relative_to(app)) for x in (app/'tests').rglob('test*.py'))
selected=files[a.shard::a.count]
assert selected
a.evidence=a.evidence.resolve();a.evidence.mkdir(parents=True,exist_ok=True)
(a.evidence/'TEST_FILE_INVENTORY.json').write_text(json.dumps({'all':files,'selected':selected,'shard':a.shard,'count':a.count},indent=2)+'\n')
env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TZ','GO_NATIVE_NODE')}
env.update({'PYTHONPATH':str(root/'ci/retention/guard')+os.pathsep+str(app)+os.pathsep+str(app/'src'),
            'PYTHONDONTWRITEBYTECODE':'1','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1',
            'APP_ENV':'test','MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED':'false'})
cmd=[sys.executable,'-m','pytest','-p','pytest_asyncio.plugin','-p','no:cacheprovider','-q',*selected,'--junitxml='+str(a.evidence/'junit.xml')]
with (a.evidence/'pytest.log').open('w') as log:
    r=subprocess.run(cmd,cwd=app,env=env,stdout=log,stderr=subprocess.STDOUT)
(a.evidence/'RESULT.json').write_text(json.dumps({'exit_code':r.returncode,'selected_files':len(selected),'shard':a.shard,'real_providers':'NOT_RUN','hong_kong':'NOT_ACCESSED'})+'\n')
print((a.evidence/'pytest.log').read_text()[-14000:])
raise SystemExit(r.returncode)
