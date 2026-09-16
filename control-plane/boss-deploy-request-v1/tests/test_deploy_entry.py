"""Real signatures, durable queue/replay and archived HK adapter; no live endpoints."""
import base64
import copy
import datetime as dt
import importlib.machinery
import importlib.util
import json
import multiprocessing
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import go_deploy_request as gate
loader = importlib.machinery.SourceFileLoader('deploy_bridge', str(ROOT / 'go-boss-request-bridge'))
spec = importlib.util.spec_from_loader(loader.name, loader)
bridge = importlib.util.module_from_spec(spec)
loader.exec_module(bridge)
sys.path.insert(0, str(ROOT.parents[1] / 'hk-staging/source/agent'))
from hk_agent import transport, deployment_actions


def signed(value, key, encoding='hex'):
    value = {k: v for k, v in value.items() if k != 'signature'}
    sig = key.sign(gate.canonical(value))
    return {**value, 'signature': sig.hex() if encoding == 'hex' else base64.b64encode(sig).decode()}


class Fixture:
    def __init__(self):
        self.at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        self.authority = Ed25519PrivateKey.generate()
        self.hk = Ed25519PrivateKey.generate()
        # The Human Approval authority is an authenticated GitHub identity, not a
        # key. The 2026-09-16 scope reset cancelled the dedicated approval signer so
        # that the Boss never has to generate or handle a key to authorise a deploy.
        self.approval_identity = gate.APPROVAL_IDENTITIES[0]
        self.candidate = 'sha256:' + 'a' * 64
        self.package = 'f' * 64   # the sealed package content address
        self.current = 'sha256:' + 'b' * 64
        canary = self.proof('HK_STAGING_CANARY', 120)
        verify = self.proof('HK_STAGING_VERIFY', 30)
        self.bundle = {'canary_task': canary[0], 'canary_evidence': canary[1],
                       'preflight_task': verify[0], 'preflight_evidence': verify[1]}
        self.bundle['plan'] = {
            'schema_version': '1', 'plan_id': 'synthetic-plan-001', 'environment': gate.ENVIRONMENT,
            'action_id': gate.ACTION, 'candidate': {'repository': 'yuguangzhi3836-glitch/GO',
                'source_commit': 'c'*40, 'application_git_tree': 'd'*40, 'source_tree_sha256': 'e'*64,
                'package_sha256': self.package, 'image_id': self.candidate},
            'expected_current_image_id': self.current, 'target_services': gate.SERVICES.copy(),
            'protected_non_targets': ['redis', 'caddy'], 'migration': False, 'production': False,
            'automatic_rollback': False, 'gates': {k: 'PASS' for k in gate.RELEASE_GATES}}
        self.bundle['approval'] = {'schema_version': '1', 'approval_id': 'synthetic-approval-001',
            'approved_by': 'synthetic-reviewer', 'approved_at': bridge.iso(self.at - dt.timedelta(seconds=10)),
            'expires_at': bridge.iso(self.at + dt.timedelta(minutes=10)), 'scope': 'HK_STAGING_DEPLOY_FIXED_EIGHT'}
        self.seal()

    def proof(self, action, age):
        completed = self.at - dt.timedelta(seconds=age)
        params = {'release_id': 'synthetic-' + action.lower(),
                  'candidate_image_id': self.candidate if action.endswith('CANARY') else self.current,
                  'expected_current_image_id': self.current}
        if action.endswith('CANARY'): params['candidate_package_sha256'] = self.package
        task = signed({'schema_version': '1', 'task_id': params['release_id'], 'nonce': 'synthetic-nonce-'+str(age),
            'issued_at': bridge.iso(completed - dt.timedelta(seconds=20)), 'expires_at': bridge.iso(completed + dt.timedelta(minutes=10)),
            'authority': 'GO-COMMAND-CENTER', 'environment': gate.ENVIRONMENT, 'action_id': action, 'parameters': params}, self.authority)
        gates = gate.CANARY_GATES if action.endswith('CANARY') else gate.VERIFY_GATES
        result = {'schema_version': '1', 'executor_version': 'synthetic-only', 'action_id': action,
            'status': 'SUCCESS', 'release_id': params['release_id'], 'candidate_image_id': params['candidate_image_id'],
            'expected_current_image_id': self.current, 'result': 'CANARY_OK' if action.endswith('CANARY') else 'VERIFY_OK',
            'gate_results': {**{k:'PASS' for k in gates}, 'application_health_proven': False}}
        with patch.object(transport, 'utcnow', return_value=bridge.iso(completed)):
            evidence = transport.evidence(task, result)
        return task, signed(evidence, self.hk, 'base64')

    def seal(self):
        for k in ('canary_task', 'canary_evidence', 'preflight_task', 'preflight_evidence'):
            key = self.hk if k.endswith('evidence') else self.authority
            self.bundle[k] = signed(self.bundle[k], key, 'base64' if k.endswith('evidence') else 'hex')
            self.bundle['plan'][k+'_sha256'] = gate.digest(self.bundle[k])
        self.bundle['approval']['plan_sha256'] = gate.digest(self.bundle['plan'])
        self.bundle['approval']['approved_by'] = self.approval_identity

    def validate(self):
        return gate.validate_bundle(self.bundle, self.bundle['plan']['plan_id'],
                                    self.authority.public_key(), self.hk.public_key(),
                                    self.at, self.approval_identity)

    def request(self, number='001', **overrides):
        return {'schema_version':'1', 'request_id':'synthetic-request-'+str(number), 'action_id':gate.ACTION,
                'environment':gate.ENVIRONMENT, 'requested_at':bridge.iso(self.at), 'plan_id':self.bundle['plan']['plan_id'], **overrides}

    def install_synthetic(self, root):
        store = root / 'plans'; store.mkdir(mode=0o700)
        for name, key in [('authority', self.authority), ('hk-evidence', self.hk)]:
            (store/(name+'.pub')).write_bytes(key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH))
        (store/(self.bundle['plan']['plan_id']+'.json')).write_bytes(gate.canonical(self.bundle))
        keypath = root / 'synthetic.pem'
        keypath.write_bytes(self.authority.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        keypath.chmod(0o600)
        config = json.loads((ROOT/'config.json').read_text()); config['deployment_requests_enabled'] = True
        channel = root/'channel.json'; channel.write_bytes(gate.canonical(config))
        return store, keypath, channel


class RequestTests(unittest.TestCase):
    def setUp(self): self.f = Fixture()
    def test_deploy_shape(self):
        self.assertEqual(bridge.validate_request(gate.canonical(self.f.request()), self.f.at)['plan_id'], 'synthetic-plan-001')
    def test_no_caller_runtime_or_approval_override(self):
        for field in ('image_id','candidate_image_id','candidate_package_sha256','source_commit','package_sha256','services',
                      'compose_path','command','signature','approval_id','task_id','nonce','force_recreate','deployment_requests_enabled'):
            with self.subTest(field=field), self.assertRaises(gate.Reject):
                bridge.validate_request(gate.canonical(self.f.request(**{field:'override'})), self.f.at)
    def test_invalid_scope_and_plan(self):
        for update in ({'environment':'PRODUCTION'}, {'plan_id':'../plan'}, {'plan_id':True}, {'plan_id':'a/b'},
                       {'action_id':[]}, {'schema_version':True}, {'requested_at':'2020-01-01T00:00:00Z'}):
            with self.subTest(update=update), self.assertRaises(gate.Reject):
                bridge.validate_request(gate.canonical(self.f.request(**update)), self.f.at)
    def test_duplicate_keys_and_nonfinite_json(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'\xff'):
            with self.assertRaises(gate.Reject): gate.parse_json(raw)
    def test_deploy_cannot_enter_legacy_derivation(self):
        with self.assertRaises(gate.Reject): bridge.derive_formal_task(self.f.request())
    def test_legacy_modes_cannot_downgrade_deploy_to_verify(self):
        with tempfile.TemporaryDirectory() as raw:
            root=pathlib.Path(raw); arm=root/'arm.json'
            arm.write_bytes(gate.canonical({'version':1,'state':'ARMED','expected_request_id':self.f.request()['request_id'],
                'max_formal_task_issuances':1,'publish_enabled':True}))
            reader=lambda *a: {'path':'requests/'+self.f.request()['request_id']+'.json','raw':gate.canonical(self.f.request())}
            with patch.object(bridge,'read_pr',reader), patch.object(bridge,'sign') as signer:
                with self.assertRaises(gate.Reject): bridge.armed_process('2','a'*40,root/'armed','unavailable',arm)
                with self.assertRaises(gate.Reject): bridge.process('2','a'*40,root/'dry','unavailable',reader)
                signer.assert_not_called()


class ProofTests(unittest.TestCase):
    def setUp(self): self.f = Fixture()
    def test_valid_plan_and_hk_wire_contract(self):
        context = self.f.validate()
        with tempfile.TemporaryDirectory() as raw:
            root=pathlib.Path(raw); _,key,_ = self.f.install_synthetic(root)
            task=bridge.sign(bridge.derive_deployment(self.f.request(), context, self.f.at),key)
            ledger=transport.Ledger(str(root/'agent.sqlite3'))
            transport.validate(task, {'environment':gate.ENVIRONMENT,'authority':'GO-COMMAND-CENTER',
                'task_verify_key':str(root/'plans/authority.pub')},ledger)
            fake=deployment_actions.FakeExecutor()
            out=transport.dispatch_action(task,fake)
            evidence=transport.evidence(task,out)
            self.assertEqual(evidence['executor_result'],'DEPLOY_OK')
            self.assertEqual(evidence['deploy_record_schema_version'],'2')
            self.assertEqual(evidence['nonce'],task['nonce'])
            self.assertEqual(fake.calls[0][0:2],['/usr/local/libexec/go-hk-deployctl','deploy'])
            args=dict(zip(fake.calls[0][2::2],fake.calls[0][3::2]))
            self.assertEqual(args['--task-canonical-sha256'],gate.digest({k:v for k,v in task.items() if k!='signature'}))
            self.assertEqual(args['--canary-evidence-id'],self.f.bundle['canary_task']['parameters']['release_id'])
            self.assertEqual(set(task['parameters']),{'release_id','candidate_image_id','candidate_package_sha256','expected_current_image_id','canary_evidence_id','approval_id'})
            self.assertNotEqual(task['parameters']['candidate_image_id'],task['parameters']['expected_current_image_id'])
            self.assertLessEqual(gate.timestamp(task['expires_at']),self.f.at+dt.timedelta(seconds=270))
    def test_wrong_keys_and_unsigned_approval(self):
        for key in ('canary_task','canary_evidence','preflight_evidence'):
            with self.subTest(key=key):
                self.f=Fixture(); self.f.bundle[key]['signature']='00'*64
                with self.assertRaises(gate.Reject): self.f.validate()
    def test_rejected_signed_plan_fields(self):
        edits=[('gates', {**{k:'PASS' for k in gate.RELEASE_GATES}, 'final_release':'HOLD'}),
            ('target_services',['api']),('protected_non_targets',[]),('production',True),('migration',True),
            ('automatic_rollback',True),('environment','PRODUCTION')]
        for key,value in edits:
            with self.subTest(key=key):
                self.f=Fixture(); self.f.bundle['plan'][key]=value; self.f.seal()
                with self.assertRaises(gate.Reject): self.f.validate()
    def test_candidate_binding_and_package_compatibility(self):
        # A registry digest is no longer part of the candidate at all: it could not
        # be satisfied by a host-built image, and the sealed package replaced it.
        for key,value in [('source_commit','main'),('package_sha256','old.zip'),('repository','other/repo'),
                          ('image_id','sha256:'+'c'*64)]:
            with self.subTest(key=key):
                self.f=Fixture(); self.f.bundle['plan']['candidate'][key]=value; self.f.seal()
                with self.assertRaises(gate.Reject): self.f.validate()
    def test_the_approval_is_authorised_by_an_authenticated_identity(self):
        """The V1 authority, asserted directly: the login GitHub reports is what counts."""
        self.assertEqual(self.f.validate()['plan_id'], self.f.bundle['plan']['plan_id'])

    def test_no_authenticated_identity_is_refused(self):
        with self.assertRaises(gate.Reject) as caught:
            gate.validate_bundle(self.f.bundle, self.f.bundle['plan']['plan_id'],
                                 self.f.authority.public_key(), self.f.hk.public_key(), self.f.at)
        self.assertEqual(str(caught.exception), 'approval_identity_missing')

    def test_an_unauthorised_github_identity_is_refused(self):
        with self.assertRaises(gate.Reject) as caught:
            gate.validate_bundle(self.f.bundle, self.f.bundle['plan']['plan_id'],
                                 self.f.authority.public_key(), self.f.hk.public_key(),
                                 self.f.at, 'someone-else')
        self.assertEqual(str(caught.exception), 'approval_identity_not_authorised')

    def test_the_approval_cannot_borrow_another_authorised_name(self):
        """The name the approval carries must be the identity that authenticated."""
        self.f.bundle['approval']['approved_by'] = gate.APPROVAL_IDENTITIES[1]
        with self.assertRaises(gate.Reject) as caught:
            self.f.validate()
        self.assertEqual(str(caught.exception), 'approval_identity_mismatch')

    def test_the_approval_carries_no_signature_field(self):
        self.assertEqual(set(self.f.bundle['approval']), set(gate.APPROVAL_FIELDS))
        self.assertNotIn('signature', gate.APPROVAL_FIELDS)

    def test_the_authorised_identities_are_named_in_one_place(self):
        self.assertEqual(gate.APPROVAL_IDENTITIES,
                         ('yuguangzhi3836-glitch', 'chenzhenxi1-sudo'))

    def test_approval_hash_and_snapshot_hash(self):
        self.f.bundle['plan']['candidate']['source_commit']='a'*40
        with self.assertRaises(gate.Reject): self.f.validate()
        self.f=Fixture(); self.f.bundle['preflight_evidence']['agent_version']='changed'
        self.f.bundle['preflight_evidence']=signed(self.f.bundle['preflight_evidence'],self.f.hk,'base64')
        with self.assertRaises(gate.Reject): self.f.validate()
    def test_approval_expiry_and_postdated_evidence(self):
        for field,seconds in [('expires_at',30),('approved_at',10),('approved_at',-60),('expires_at',3600)]:
            with self.subTest(field=field,seconds=seconds):
                self.f=Fixture(); self.f.bundle['approval'][field]=bridge.iso(self.f.at+dt.timedelta(seconds=seconds)); self.f.seal()
                with self.assertRaises(gate.Reject): self.f.validate()
    def test_stale_or_failed_signed_evidence(self):
        mutations=[('status','FAIL'),('executor_result','DEPLOY_OK'),('nonce','different-nonce'),
                   ('candidate_image_id','sha256:'+'d'*64),('completed_at',bridge.iso(self.f.at-dt.timedelta(minutes=10))),
                   ('gate_results',{k:'PASS' for k in gate.VERIFY_GATES if k!='api_health'})]
        for field,value in mutations:
            with self.subTest(field=field):
                self.f=Fixture(); self.f.bundle['preflight_evidence'][field]=value; self.f.seal()
                with self.assertRaises(gate.Reject): self.f.validate()
    def test_numeric_false_is_not_a_signed_gate(self):
        self.f.bundle['preflight_evidence']['gate_results']['application_health_proven']=0; self.f.seal()
        with self.assertRaises(gate.Reject): self.f.validate()
    def test_executor_identifier_compatibility(self):
        self.f.bundle['approval']['approval_id']='bad.dot'; self.f.seal()
        with self.assertRaises(gate.Reject): self.f.validate()
    def test_signed_canary_must_match_candidate(self):
        self.f.bundle['canary_task']['parameters']['candidate_package_sha256']='0'*64; self.f.seal()
        with self.assertRaises(gate.Reject): self.f.validate()


class StorageTests(unittest.TestCase):
    def test_secure_plan_load_and_absence(self):
        f=Fixture()
        with tempfile.TemporaryDirectory() as raw:
            root=pathlib.Path(raw); store,_,_=f.install_synthetic(root)
            with patch.object(gate,'STORE',store),patch.object(gate,'TRUSTED_UID',os.getuid()):
                self.assertEqual(gate.load_context('synthetic-plan-001',f.at,
                                                gate.APPROVAL_IDENTITIES[0])['plan_id'],
                                 'synthetic-plan-001')
                with self.assertRaises(gate.Reject): gate.load_context('missing-plan',f.at)
    def test_symlink_writable_oversized_and_bad_owner(self):
        with tempfile.TemporaryDirectory() as raw:
            root=pathlib.Path(raw); target=root/'record'; target.write_text('hello')
            alias=root/'alias'; alias.symlink_to(target)
            with patch.object(gate,'TRUSTED_UID',os.getuid()):
                with self.assertRaises(gate.Reject): gate.read_secure(alias)
                with self.assertRaises(gate.Reject): gate.read_secure(target,2)
                target.chmod(0o666)
                with self.assertRaises(gate.Reject): gate.read_secure(target)
                target.chmod(0o600); root.chmod(0o777)
                with self.assertRaises(gate.Reject): gate.read_secure(target)
                root.chmod(0o700)
            with patch.object(gate,'TRUSTED_UID',os.getuid()+1):
                with self.assertRaises(gate.Reject): gate.read_secure(target)
            with self.assertRaises(gate.Reject): gate.read_secure(root/'missing/record')
    def test_default_activation_off_and_malformed_channel(self):
        self.assertIs(json.loads((ROOT/'config.json').read_text())['deployment_requests_enabled'],False)
        with tempfile.TemporaryDirectory() as raw:
            p=pathlib.Path(raw)/'config'; p.write_text('[]')
            with self.assertRaises(gate.Reject): bridge.load_channel(p)


class MetadataTests(unittest.TestCase):
    def test_pr_metadata_open_base_same_repo_exact_head(self):
        good={'state':'open','draft':False,'merged':False,
            'base':{'ref':'main','repo':{'full_name':'chenzhenxi1-sudo/go-control-tasks'}},
            'user':{'login':gate.APPROVAL_IDENTITIES[0]},
            'head':{'sha':'a'*40,'repo':{'full_name':'chenzhenxi1-sudo/go-control-tasks'}}}
        import urllib.request
        class Response:
            def __init__(self,v): self.v=v
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def read(self,n): return gate.canonical(self.v)
        with patch.object(gate,'read_secure',return_value=b'synthetic-test-token'),patch.object(urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=Response(good)
            value,login=bridge.check_deploy_pr('2','a'*40)
            self.assertEqual(value,good)
            self.assertEqual(login,gate.APPROVAL_IDENTITIES[0])
            bads=[[],{'base':None},{**good,'state':'closed'},{**good,'draft':True},{**good,'merged':True},
                  {**good,'head':{**good['head'],'sha':'b'*40}}, {**good,'base':{**good['base'],'ref':'other'}},
                  {**good,'head':{**good['head'],'repo':{'full_name':'fork/tasks'}}}]
            for bad in bads:
                opener.return_value.open.return_value=Response(bad)
                with self.subTest(bad=bad), self.assertRaises(gate.Reject): bridge.check_deploy_pr('2','a'*40)
    def test_missing_metadata_credentials_fails_closed(self):
        with patch.object(gate,'read_secure',side_effect=gate.Reject('missing')):
            with self.assertRaises(gate.Reject): bridge.check_deploy_pr('2','a'*40)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture(); self.tmp=tempfile.TemporaryDirectory(); self.root=pathlib.Path(self.tmp.name)
        self.store,self.key,self.channel=self.f.install_synthetic(self.root)
        self.stack=ExitStack(); self.addCleanup(self.stack.close); self.addCleanup(self.tmp.cleanup)
        self.stack.enter_context(patch.object(gate,'STORE',self.store))
        self.stack.enter_context(patch.object(gate,'TRUSTED_UID',os.getuid()))
        self.stack.enter_context(patch.object(bridge,'now',return_value=self.f.at))
        self.stack.enter_context(patch.object(bridge,'check_deploy_pr',
            return_value=({},gate.APPROVAL_IDENTITIES[0])))
        def reader(n,h):
            r=self.f.request(n)
            return {'path':'requests/'+r['request_id']+'.json','raw':gate.canonical(r)}
        self.stack.enter_context(patch.object(bridge,'read_pr',side_effect=reader))
        self.remote=self.root/'remote'; self.remote.mkdir()
        def publish(task):
            # The claim must already survive a process restart before publication.
            record=json.loads((self.root/'ledger/ledger.json').read_text())['requests']
            self.assertTrue(any(r.get('status')=='publishing' and r['task']==task for r in record.values()))
            path=self.remote/(task['task_id']+'.json')
            with path.open('xb') as stream: stream.write(gate.canonical(task)+b'\n')
            return 'e'*40
        def fetch(identity):
            p=self.remote/(identity+'.json')
            return p.read_bytes() if p.exists() else None
        self.publisher=self.stack.enter_context(patch.object(bridge,'publish_task',side_effect=publish))
        self.stack.enter_context(patch.object(bridge,'remote_task',side_effect=fetch))
    def run_request(self,n='2'):
        return bridge.persistent_process(n,'a'*40,self.root/'ledger',self.key,self.channel)
    def config(self,**edits):
        value=json.loads(self.channel.read_text()); value.update(edits); self.channel.write_bytes(gate.canonical(value))
    def test_publish_replay_and_duplicate_plan(self):
        self.assertEqual(self.run_request()['status'],'published')
        self.assertEqual(self.run_request()['status'],'already_seen')
        with self.assertRaisesRegex(gate.Reject,'already_consumed'): self.run_request('3')
        self.assertEqual(len(list(self.remote.glob('*.json'))),1)
    def test_reused_approval_with_new_plan_rejected(self):
        self.run_request(); self.f.bundle['plan']['plan_id']='synthetic-plan-002'; self.f.seal()
        (self.store/'synthetic-plan-002.json').write_bytes(gate.canonical(self.f.bundle))
        with self.assertRaisesRegex(gate.Reject,'already_consumed'): self.run_request('3')
        self.assertEqual(self.publisher.call_count,1)
    def test_switch_disabled_no_sign_or_publish(self):
        self.config(deployment_requests_enabled=False)
        with patch.object(bridge,'sign') as signer:
            with self.assertRaisesRegex(gate.Reject,'disabled'): self.run_request()
            signer.assert_not_called(); self.publisher.assert_not_called()
    def test_request_filename_binding(self):
        with patch.object(bridge,'read_pr',return_value={'path':'requests/wrong.json','raw':gate.canonical(self.f.request())}):
            with self.assertRaisesRegex(gate.Reject,'filename'): self.run_request()
        self.publisher.assert_not_called()
    def test_midflight_head_change_consumes_claim_without_publish(self):
        with patch.object(bridge,'check_deploy_pr',
                side_effect=[({},gate.APPROVAL_IDENTITIES[0]),gate.Reject('changed')]):
            with self.assertRaisesRegex(gate.Reject,'changed'): self.run_request()
        with self.assertRaisesRegex(gate.Reject,'ambiguous'): self.run_request()
        self.publisher.assert_not_called()
    def test_midflight_switch_revocation(self):
        original=bridge.sign
        def revoke(*a):
            result=original(*a); self.config(deployment_requests_enabled=False); return result
        with patch.object(bridge,'sign',side_effect=revoke):
            with self.assertRaisesRegex(gate.Reject,'disabled'): self.run_request()
        self.publisher.assert_not_called()
    def test_midflight_plan_replacement(self):
        original=bridge.sign
        def change(*a):
            result=original(*a); self.f.bundle['plan']['candidate']['source_commit']='0'*40; self.f.seal()
            (self.store/'synthetic-plan-001.json').write_bytes(gate.canonical(self.f.bundle)); return result
        with patch.object(bridge,'sign',side_effect=change):
            with self.assertRaisesRegex(gate.Reject,'changed'): self.run_request()
        self.publisher.assert_not_called()
    def test_ambiguous_publish_no_second_attempt(self):
        self.publisher.side_effect=OSError('synthetic network ambiguity')
        with self.assertRaisesRegex(gate.Reject,'ambiguous'): self.run_request()
        with self.assertRaisesRegex(gate.Reject,'ambiguous'): self.run_request()
        self.assertEqual(self.publisher.call_count,1)
    def test_published_before_lost_ack_is_reconciled(self):
        real=self.publisher.side_effect
        def lost_ack(task): real(task); raise OSError('synthetic lost ack')
        self.publisher.side_effect=lost_ack
        self.assertEqual(self.run_request()['status'],'published')
        self.assertEqual(self.run_request()['status'],'already_seen')
        self.assertEqual(self.publisher.call_count,1)
    def test_prepared_published_bytes_reconciled_after_restart(self):
        self.run_request(); path=self.root/'ledger/ledger.json'; data=json.loads(path.read_text())
        next(iter(data['requests'].values()))['status']='publishing'; path.write_bytes(gate.canonical(data))
        self.assertEqual(self.run_request()['status'],'published_reconciled')
        self.assertEqual(self.publisher.call_count,1)
    def test_two_processes_one_plan_one_publication(self):
        def child(n):
            try: self.run_request(n)
            except gate.Reject: pass
        ctx=multiprocessing.get_context('fork')
        children=[ctx.Process(target=child,args=(str(n),)) for n in (2,3)]
        for p in children: p.start()
        for p in children:
            p.join(15)
            if p.is_alive(): p.terminate(); self.fail('queue lock did not release')
            self.assertEqual(p.exitcode,0)
        self.assertEqual(len(list(self.remote.glob('*.json'))),1)
        records=json.loads((self.root/'ledger/ledger.json').read_text())['requests']
        self.assertEqual(len(records),1)
    def test_test_pr_preserved_with_exact_resolved_source(self):
        request=self.f.request(); request.pop('plan_id'); request.update(action_id=bridge.TEST_ACTION,pr_number='47')
        task=bridge.derive_test_pr(bridge.validate_request(gate.canonical(request),self.f.at),self.f.at,lambda n:'c'*40)
        with patch.object(bridge,'read_pr',return_value={'path':'requests/'+request['request_id']+'.json','raw':gate.canonical(request)}),\
             patch.object(bridge,'derive_formal_task',return_value=task):
            self.assertEqual(self.run_request()['status'],'published')
        published=json.loads(next(self.remote.glob('*.json')).read_text())
        self.f.authority.public_key().verify(bytes.fromhex(published['signature']),gate.canonical(task))
        self.assertEqual(published['parameters'],{'builder_profile':'go-application-python-v1','source':{
            'repository':'git@github.com:yuguangzhi3836-glitch/GO.git','pr_number':'47','commit_sha':'c'*40}})
    def test_v2_cannot_enable_new_actions(self):
        self.channel.write_bytes(gate.canonical({'version':2,'mode':'PERSISTENT','publish_enabled':True,
            'allowed_action_id':'HK_STAGING_VERIFY','allowed_environment':gate.ENVIRONMENT}))
        with self.assertRaisesRegex(gate.Reject,'action_not_enabled'): self.run_request()
        self.publisher.assert_not_called()


class GitDiffTests(unittest.TestCase):
    def test_advanced_main_does_not_inject_unrelated_task_deletions(self):
        with tempfile.TemporaryDirectory() as raw:
            repo=pathlib.Path(raw)/'repo'; repo.mkdir()
            env={'PATH':'/usr/bin:/bin','HOME':raw,'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_ALLOW_PROTOCOL':'file'}
            def git(*a): return subprocess.run(['/usr/bin/git',*a],cwd=repo,env=env,check=True,capture_output=True,text=True).stdout.strip()
            git('init','-q','-b','main'); git('config','user.name','Synthetic'); git('config','user.email','synthetic@localhost')
            (repo/'README').write_text('fixture'); git('add','.'); git('commit','-qm','base')
            git('checkout','-qb','request'); (repo/'requests').mkdir(); (repo/'requests/synthetic-request.json').write_bytes(gate.canonical(Fixture().request()))
            git('add','.'); git('commit','-qm','request'); head=git('rev-parse','HEAD'); git('update-ref','refs/pull/2/head',head)
            git('checkout','-q','main'); (repo/'tasks').mkdir(); (repo/'tasks/unrelated.json').write_text('{}')
            git('add','.'); git('commit','-qm','unrelated task on main')
            with patch.object(bridge,'REPO',str(repo)),patch.object(bridge,'ssh_env',return_value=env),patch.object(bridge,'discover_heads',return_value={'2':head}):
                self.assertEqual(bridge.read_pr('2',head)['path'],'requests/synthetic-request.json')
                with self.assertRaisesRegex(gate.Reject,'head_changed'): bridge.read_pr('2','a'*40)
