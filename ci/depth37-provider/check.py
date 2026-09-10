import base64,hashlib,json,os,subprocess,sys
from pathlib import Path
root=Path.cwd();out=root/'evidence';out.mkdir(exist_ok=True);repo=root/'candidate';package=repo/'deliverables/CP11_DEPTH37_NODE_NATIVE_PROVIDER_20260910';current=repo/'deliverables/CP11_DEPTH37R2_NATIVE_MODULE_LINKING_20260910';name='scripts/provider_certification_preflight.py'
commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip();assert commit=='da6897706793fafd73d09cb56013586089733f4d'
raw=base64.b64decode(json.loads((package/'DELTA.json').read_text())[name],validate=True);expected=json.loads((current/'SOURCE_FINGERPRINT.json').read_text())[name];assert hashlib.sha256(raw).hexdigest()==expected
script=root/'provider-preflight.py';script.write_bytes(raw)
# The reviewed preflight reads environment inputs locally and emits only names/error codes.
p=subprocess.run([sys.executable,str(script),'--evidence',str(out/'provider-inputs.json')],capture_output=True,text=True,timeout=30)
assert p.returncode in (0,2),'PREFLIGHT_EXECUTION_ERROR'
(out/'provider-preflight.log').write_text(p.stdout+p.stderr)
result=json.loads((out/'provider-inputs.json').read_text());assert result['external_calls']==0 and result['credential_values_recorded'] is False
(out/'source-binding.json').write_text(json.dumps({'candidate':commit,'script_sha256':expected,'source_tree_sha256':'cf3f13960effa346337ed549cfb58ed6bae7aec94d05aba2e3b2f00d0b9df84c','scope':'Existing repository/organization secrets referenced by canonical name; no environment selected; no secrets enumeration','external_calls':0},indent=2)+'\n')
(out/'commands.json').write_text(json.dumps([{'name':'provider-config-preflight','exit_code':p.returncode,'pass':result['ready'],'meaning':'Structural readiness only; genuine certification NOT RUN'}],indent=2)+'\n')
print(json.dumps(result,indent=2))
raise SystemExit(p.returncode)
