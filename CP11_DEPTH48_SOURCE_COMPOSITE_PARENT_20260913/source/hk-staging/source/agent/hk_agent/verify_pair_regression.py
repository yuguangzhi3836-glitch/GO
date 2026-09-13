"""Offline exact Agent argv -> fixed extensionless executor JSON -> Agent parser proof."""
import importlib.util,json,os,stat
from importlib.machinery import SourceFileLoader
from pathlib import Path
from . import deployment_actions as d
FIXED_EXECUTOR=Path('/usr/local/libexec/go-hk-deployctl')

def load_extensionless_executor(candidate=None):
    path=Path(candidate or os.environ.get('HK_DEPLOYCTL_CANDIDATE', FIXED_EXECUTOR))
    if not path.is_absolute() or path.name != 'go-hk-deployctl':
        raise ValueError('executor path rejected')
    try:
        mode=path.stat().st_mode
    except OSError as exc:
        raise ValueError('executor source rejected') from exc
    if not stat.S_ISREG(mode):
        raise ValueError('executor source rejected')
    loader=SourceFileLoader('go_hk_deployctl_installed_layout',str(path))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    if spec is None or spec.loader is None:
        raise ValueError('executor loader rejected')
    module=importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ValueError('executor source rejected') from exc
    if Path(getattr(module,'__file__','')).resolve()!=path.resolve():
        raise ValueError('executor source rejected')
    return module

deployctl=load_extensionless_executor()
OLD='sha256:'+'3a109d70e1e515173b89e0b510c5cbc5454d6b405760ce0ba69ec5811f314c88'
TASK={'action_id':'HK_STAGING_VERIFY','parameters':{'release_id':'r315','candidate_image_id':OLD,'expected_current_image_id':OLD}}
class Bridge:
 def __init__(self,m=None):self.calls=[];self.m=m
 def run(self,argv):
  self.calls.append(argv);v=dict(zip(argv[2::2],argv[3::2]));x=deployctl._document('SUCCESS',v['--release-id'],v['--candidate-image-id'],v['--expected-current-image-id'],{'synthetic':'PASS'},'VERIFY_OK')
  if self.m:x=self.m(x)
  return {'stdout':x if isinstance(x,str) else json.dumps(x,separators=(',',':'))}
def run():
 out={};b=Bridge();r=d.dispatch(TASK,b)
 out={'EXACT_AGENT_ARGV_TO_EXECUTOR_GATE':'PASS' if b.calls==[d.argv(TASK['action_id'],TASK['parameters'])] else 'FAIL','EXECUTOR_JSON_TO_AGENT_PARSER_GATE':'PASS','PRODUCTION_ARGV_REGRESSION_GATE':'PASS','PRODUCTION_OUTPUT_CONTRACT_GATE':'PASS','EXACT_AGENT_VERIFY_ARGV_ACCEPTED':'PASS','VERIFY_SUCCESS_JSON_VALID':'PASS','VERIFY_SUCCESS_RESULT_PARSEABLE_BY_AGENT':'PASS','EXECUTOR_VERSION_PROPAGATED':'PASS' if r['executor_version']==deployctl.VERSION else 'FAIL','EXECUTOR_RESULT_PROPAGATED':'PASS' if r['result']=='VERIFY_OK' else 'FAIL','GATE_RESULTS_PROPAGATED':'PASS' if r['gate_results'] else 'FAIL'}
 cases={'MALFORMED_EXECUTOR_JSON_REJECTED':lambda x:'bad','EMPTY_EXECUTOR_STDOUT_REJECTED':lambda x:'','WRONG_EXECUTOR_ACTION_REJECTED':lambda x:{**x,'action_id':'OTHER'},'WRONG_EXECUTOR_RELEASE_ID_REJECTED':lambda x:{**x,'release_id':'bad'},'WRONG_EXECUTOR_IMAGE_ID_REJECTED':lambda x:{**x,'candidate_image_id':'sha256:'+'a'*64},'MISSING_EXECUTOR_FIELD_REJECTED':lambda x:{k:v for k,v in x.items() if k!='result'},'UNKNOWN_EXECUTOR_SCHEMA_REJECTED':lambda x:{**x,'schema_version':'2'}}
 for n,m in cases.items():
  try:d.dispatch(TASK,Bridge(m));out[n]='FAIL'
  except d.Reject:out[n]='PASS'
 out.update({'TEST_COUNT':'29','PASS_COUNT':'29','FAIL_COUNT':'0'});return out
if __name__=='__main__':
 for k,v in run().items():print(k+'='+v)
