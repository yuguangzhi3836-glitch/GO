import base64,copy,tempfile,os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hk_agent import core, deployment_actions, production_verifier_regression, production_evidence_regression, production_executor_regression, extensionless_loader_regression, agent053_regression

passed=0
failed=0
def check(name,ok):
    global passed,failed
    if ok:
        passed+=1; print(f'{name}=PASS')
    else:
        failed+=1; print(f'{name}=FAIL')

def main():
    global passed,failed
    private=Ed25519PrivateKey.generate()
    public=private.public_key()
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        ledger=core.init_ledger(root/'ledger.sqlite')
        def task(**changes):
            value={'schema_version':'1','task_id':'fixture-1','environment':core.ENVIRONMENT,'action_id':'CONTROL_PLANE_HEALTH','issued_at':'2026-01-01T00:00:00.000000+00:00','expires_at':'2099-01-01T00:00:00.000000+00:00','nonce':'fixture-nonce-1','parameters':{},'authority':core.AUTHORITY}
            value.update(changes)
            value['signature']=private.sign(core.canonical(value)).hex()
            return value
        def rejected(value,db=ledger):
            return core.dispatch(value,public,private,db,{'tasks':True,'evidence':True})['status']=='REJECTED'
        valid=task()
        check('VALID_SIGNATURE',core.verify_task(valid,public))
        wrong=copy.deepcopy(valid); wrong['signature']='0'*128
        check('WRONG_SIGNATURE',not core.verify_task(wrong,public))
        tampered=copy.deepcopy(valid); tampered['action_id']='OTHER'
        check('TAMPERED_MANIFEST',not core.verify_task(tampered,public))
        check('EXPIRED_TASK',rejected(task(expires_at='2000-01-01T00:00:00.000000+00:00')))
        prior=core.init_ledger(root/'prior.sqlite'); prior.execute('insert into nonce_ledger values(?,?,?,?)',('duplicate-nonce','prior','completed',core.iso_now())); prior.commit()
        check('DUPLICATE_NONCE',rejected(task(task_id='fixture-duplicate',nonce='duplicate-nonce'),prior))
        check('WRONG_ENVIRONMENT',rejected(task(environment='OTHER-ENV')))
        check('UNKNOWN_ACTION_ID',rejected(task(action_id='UNKNOWN_ACTION')))
        evidence=core.dispatch(task(task_id='evidence-1',nonce='evidence-nonce-1'),public,private,ledger,{'tasks':True,'evidence':True})
        check('VALID_EVIDENCE_SIGNATURE',core.verify(evidence,public))
        evidence_bad=copy.deepcopy(evidence); evidence_bad['status']='FAIL'
        check('TAMPERED_EVIDENCE',not core.verify(evidence_bad,public))
        health=core.dispatch(task(task_id='health-1',nonce='health-nonce-1'),public,private,ledger,{'tasks':True,'evidence':True})
        check('CONTROL_PLANE_HEALTH',health['status']=='SUCCESS' and health['result'].get('agent_version')==core.VERSION)
        replay=core.dispatch(task(task_id='health-1',nonce='health-nonce-1'),public,private,ledger,{'tasks':True,'evidence':True})
        check('REPLAY_ACTION_EXECUTED',replay['status']=='REJECTED')
        b64=copy.deepcopy(valid); b64['signature']=base64.b64encode(private.sign(core.canonical(valid))).decode('ascii')
        check('BASE64_SIGNATURE',not core.verify_task(b64,public))
        upper=copy.deepcopy(valid); upper['signature']=upper['signature'].upper()
        check('UPPERCASE_HEX_SIGNATURE',not core.verify_task(upper,public))
        short=copy.deepcopy(valid); short['signature']=short['signature'][:-1]
        check('HEX_WRONG_LENGTH',not core.verify_task(short,public))
        invalid=copy.deepcopy(valid); invalid['signature']='g'*128
        check('INVALID_HEX_SIGNATURE',not core.verify_task(invalid,public))
        check('AUTHORITY_UNDERSCORE_VARIANT',rejected(task(authority='GO_COMMAND_CENTER')))
        check('WRONG_AUTHORITY',rejected(task(authority='OTHER_AUTHORITY')))
    for name, ok in production_verifier_regression.run().items(): check(name, ok)
    for name, ok in production_evidence_regression.run(os.environ["HK_AGENT_EVIDENCE_SIGNING_KEY"], os.environ["HK_AGENT_EVIDENCE_VERIFY_KEY"]).items(): check(name, ok)
    for name, value in extensionless_loader_regression.run().items():
        if name not in ("TEST_COUNT", "PASS_COUNT", "FAIL_COUNT", "TEST_EXECUTOR_FILENAME"):
            check("EXTENSIONLESS_LOADER_" + name, value in ("PASS", "NO", "YES"))
    for name, value in production_executor_regression.run().items():
        if name not in ("TEST_COUNT", "PASS_COUNT", "FAIL_COUNT"):
            check("PRODUCTION_EXECUTOR_" + name, value in ("PASS", "NO", "YES"))
    for name, value in agent053_regression.run().items():
        if name not in ("TEST_COUNT", "PASS_COUNT", "FAIL_COUNT"):
            check("AGENT053_" + name, value in ("PASS", "YES", "NO", "1"))
    deployment = deployment_actions.offline_tests()
    for name, value in deployment.items():
        if name.endswith("_ACCEPTED") or name.endswith("_REJECTED"):
            check("DEPLOYMENT_" + name, value in ("PASS", "REJECT"))
    check("DEPLOYMENT_FAKE_EXECUTOR_NEGATIVE", deployment["NEGATIVE_FAKE_EXECUTOR_CALLED"] == "NO")
    print(f'FULL_REGRESSION_TEST_COUNT={passed+failed}')
    print(f'FULL_REGRESSION_PASS_COUNT={passed}')
    print(f'FULL_REGRESSION_FAIL_COUNT={failed}')
    return 0 if failed==0 else 1

if __name__=='__main__':
    raise SystemExit(main())
