"""Real signatures, durable queue/replay and archived HK adapter; no live endpoints."""
import base64
import copy
import datetime as dt
import hashlib
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
import plan_derivation as derivation


def _mode_bits_deny_writes():
    """Whether `chmod` can deny this process a write.

    It cannot for uid 0: root holds CAP_DAC_OVERRIDE, so an 0500 directory stays
    writable and a test that relies on the mode bits would pass without exercising
    the refusal branch at all.  Windows has no equivalent, and the suite runs the
    store checks anyway, so it is reported as "cannot rely on it" there too.
    """
    if os.name == 'nt': return False
    try: return os.getuid() != 0
    except AttributeError: return False


MODE_BITS_DENY_WRITES=_mode_bits_deny_writes()
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
    def __init__(self, test_pr_age=3600):
        self.at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        self.test_pr_age = test_pr_age
        self.authority = Ed25519PrivateKey.generate()
        self.hk = Ed25519PrivateKey.generate()
        # The Human Approval authority is an authenticated GitHub identity, not a
        # key. The 2026-09-16 scope reset cancelled the dedicated approval signer so
        # that the Boss never has to generate or handle a key to authorise a deploy.
        self.approval_identity = gate.APPROVAL_IDENTITIES[0]
        self.source = 'c' * 40
        self.tree = 'd' * 40
        self.fingerprint = 'e' * 64
        self.test_pr_number = '52'
        self.candidate = 'sha256:' + 'a' * 64
        self.package = 'f' * 64   # the sealed package content address
        self.current = 'sha256:' + 'b' * 64
        # The approval is the DEPLOY Request itself: who GitHub says wrote it, when, and
        # the digest of its canonical content. Every deployment assertion is therefore
        # about one exact Request.
        self.request_sha256 = gate.request_digest(self.request())
        test_pr = self.test_pr_proof()
        canary = self.proof('HK_STAGING_CANARY', 120)
        verify = self.proof('HK_STAGING_VERIFY', 30)
        self.bundle = {'test_pr_task': test_pr[0], 'test_pr_evidence': test_pr[1],
                       'canary_task': canary[0], 'canary_evidence': canary[1],
                       'preflight_task': verify[0], 'preflight_evidence': verify[1]}
        self.bundle['plan'] = {
            'schema_version': '1', 'plan_id': 'synthetic-plan-001', 'environment': gate.ENVIRONMENT,
            'action_id': gate.ACTION, 'candidate': {'repository': 'yuguangzhi3836-glitch/GO',
                'source_commit': self.source, 'application_git_tree': self.tree,
                'source_tree_sha256': self.fingerprint,
                'package_sha256': self.package, 'image_id': self.candidate},
            'expected_current_image_id': self.current, 'target_services': gate.SERVICES.copy(),
            'protected_non_targets': ['redis', 'caddy'], 'migration': False, 'production': False,
            'automatic_rollback': False}
        self.bundle['approval'] = {'schema_version': '1', 'approval_id': 'synthetic-approval-001',
            'approved_by': 'synthetic-reviewer', 'approved_at': bridge.iso(self.at - dt.timedelta(seconds=10)),
            # The approval's life is the contract's, not the fixture's: the Bridge derives
            # it as approved_at + APPROVAL_MAX_LIFE, so a fixture that picked its own would
            # be describing a plan no derivation produces.
            'expires_at': bridge.iso(self.at - dt.timedelta(seconds=10) + gate.APPROVAL_MAX_LIFE),
            'scope': 'HK_STAGING_DEPLOY_FIXED_EIGHT'}
        # The rollback source: the deployment this same Bridge would have published a
        # moment ago. It is built here rather than written by hand because a rollback is
        # only ever a function of it.
        self.deploys = {}
        self.deploy_source()
        self.seal()

    def deploy_source(self, task_id='go-boss-deploy-synthetic-source', age=90,
                      nonce='synthetic-deploy-nonce', gates=None):
        """A signed DEPLOY Task and its signed Evidence -- the pair a rollback undoes.

        The Evidence is produced by the Hong Kong agent's own `evidence()` builder rather
        than assembled here, so the fixture carries the field names and the field *set* the
        producer writes; a gate that read a name the agent never writes would fail here
        instead of only against a live deployment.
        """
        completed = self.at - dt.timedelta(seconds=age)
        parameters = {'release_id': task_id.replace('go-', '', 1),
                      'candidate_image_id': self.candidate,
                      'candidate_package_sha256': self.package,
                      'expected_current_image_id': self.current,
                      'canary_evidence_id': self.bundle['canary_task']['parameters']['release_id'],
                      'approval_id': 'approval-' + 'a' * 16}
        record_id = hashlib.sha256(task_id.encode()).hexdigest()
        task = signed({'schema_version': '1', 'task_id': task_id, 'nonce': nonce,
            'issued_at': bridge.iso(completed - dt.timedelta(seconds=20)),
            'expires_at': bridge.iso(completed + dt.timedelta(minutes=10)),
            'authority': 'GO-COMMAND-CENTER', 'environment': gate.ENVIRONMENT,
            'action_id': gate.ACTION, 'parameters': parameters}, self.authority)
        result = {'schema_version': '1', 'executor_version': '0.4.3-rollback-runtime',
            'action_id': gate.ACTION, 'status': 'SUCCESS', 'release_id': parameters['release_id'],
            'candidate_image_id': self.candidate, 'expected_current_image_id': self.current,
            'result': 'DEPLOY_OK',
            # The real deploy runtime writes `record_path` beside its gates -- it is the
            # path of the immutable record it just wrote, not a verdict. It is carried
            # here so a gate that demanded "every value in gate_results is PASS" would
            # fail on the fixture, which is where that mistake is cheapest to find.
            'gate_results': {**(gates if gates is not None else {k: 'PASS' for k in gate.DEPLOY_GATES}),
                             'record_path': '/var/lib/go-hk-deployctl/deploy-records/' + record_id + '.json'},
            'deploy_record_schema_version': '2', 'deploy_record_id': record_id,
            'deploy_record_sha256': 'f' * 64}
        with patch.object(transport, 'utcnow', return_value=bridge.iso(completed)):
            evidence = transport.evidence(task, result)
        evidence = signed(evidence, self.hk, 'base64')
        self.deploys[task_id] = (task, evidence)
        if task_id == 'go-boss-deploy-synthetic-source':
            self.deploy_task, self.deploy_evidence = task, evidence
        return task, evidence

    def resign(self, value, key, encoding='base64'):
        """Re-sign a value after an edit, so the refusal under test is the gate's own.

        A tampered object that is left unsigned would be refused by the verifier first,
        and the test would prove nothing about the rule it names.
        """
        return signed({k: v for k, v in value.items() if k != 'signature'}, key, encoding)

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

    def test_pr_proof(self):
        """The signed sealed TEST_PR of this exact candidate.

        This is the proof that replaced `sealed_node = PASS`: it names the pull request
        the artifact was built from, the commit it was built at, the artifact itself, the
        sealed package that artifact was written into, and that the sealing was proven.
        """
        completed = self.at - dt.timedelta(seconds=self.test_pr_age)
        params = {'builder_profile': 'go-application-python-v1',
                  'source': {'repository': 'git@github.com:yuguangzhi3836-glitch/GO.git',
                             'pr_number': self.test_pr_number, 'commit_sha': self.source}}
        task = signed({'schema_version': '1', 'task_id': 'go-boss-test-pr-52-synthetic',
            'nonce': 'synthetic-test-pr-nonce', 'issued_at': bridge.iso(completed - dt.timedelta(seconds=20)),
            'expires_at': bridge.iso(completed + dt.timedelta(minutes=10)),
            'authority': 'GO-COMMAND-CENTER', 'environment': gate.ENVIRONMENT,
            'action_id': gate.TEST_PR_ACTION, 'parameters': params}, self.authority)
        evidence = {'schema_version': '1', 'task_id': task['task_id'], 'nonce': task['nonce'],
            'action_id': gate.TEST_PR_ACTION, 'environment': gate.ENVIRONMENT, 'status': 'SUCCESS',
            'executor_result': 'TEST_PR_OK', 'executor_version': 'test-pr-v3',
            'started_at': bridge.iso(completed), 'completed_at': bridge.iso(completed),
            'task_canonical_sha256': gate.digest({k: v for k, v in task.items() if k != 'signature'}),
            'source_commit_sha': self.source, 'source_pr_number': self.test_pr_number,
            # A real TEST_PR Evidence carries built_image_id only; the HK contract at
            # hk_agent/transport.py:315 has no artifact_digest.  The fixture used to
            # carry both names, which is why it passed while the live gate could not.
            'built_image_id': self.candidate,
            'artifact_durability': 'PROVEN',
            'artifact_package': {'schema': 'go.sealed-artifact.v1', 'package_sha256': self.package,
                                 'image_id': self.candidate, 'store': 'go-hk-artifacts',
                                 'image_identity_role': 'root_descriptor'},
            'deployment_performed': False,
            'gate_results': {k: 'PASS' for k in gate.TEST_PR_GATES}}
        return task, signed(evidence, self.hk, 'base64')

    def admission_pointer(self):
        """The block candidate admission publishes, as the Bridge reads it."""
        return {'schema': derivation.ADMISSION_SCHEMA, 'release_candidate_v1': {
            'schema': derivation.CANDIDATE_SCHEMA,
            'source_repository': 'yuguangzhi3836-glitch/GO', 'source_commit': self.source,
            'application_tree': self.tree, 'source_fingerprint': self.fingerprint,
            'migration_head': '0133_flight_change_plan', 'migration_required': False,
            'artifact_digest': self.candidate,
            'artifact_package': {'durability': 'PROVEN', 'package_sha256': self.package},
            'test_result_identity': {'action_id': gate.TEST_PR_ACTION,
                                     'task_id': self.bundle['test_pr_task']['task_id']},
            'rollback_relation': {'relation': 'REPLACES_CURRENT_KNOWN_GOOD',
                                  'previous_known_good_image_id': self.current}}}

    def verify_baseline(self):
        return {'version': 1, 'environment': gate.ENVIRONMENT, 'image_id': self.current,
                'evidence_task_id': 'synthetic-liveness', 'evidence_commit': 'a' * 40,
                'evidence_path': 'evidence/synthetic-liveness.json'}

    def read_evidence(self, task):
        """The Evidence the evidence repository holds for one published Task."""
        pair = self.deploys.get(task.get('task_id'))
        if pair is not None: return pair[1]
        for name in ('test_pr_evidence', 'canary_evidence', 'preflight_evidence'):
            evidence = self.bundle[name]
            if evidence.get('task_id') == task.get('task_id'):
                return evidence
        raise gate.Reject('evidence_unreadable')

    def seed_ledger(self, root):
        """The published Tasks this Bridge signed earlier, as its ledger holds them.

        The plan is derived from the Bridge's own history, so a fixture that wants a plan
        has to give the Bridge that history: the sealed TEST_PR, the canary and the
        preflight were all published through this same channel.
        """
        root = pathlib.Path(root); root.mkdir(mode=0o700, parents=True, exist_ok=True)
        records = {}
        for label, task in (('test-pr', self.bundle['test_pr_task']),
                            ('canary', self.bundle['canary_task']),
                            ('preflight', self.bundle['preflight_task']),
                            # The deployment this Bridge published earlier, which is the
                            # one thing a rollback may undo.
                            ('deploy-source', self.deploy_task)):
            records['synthetic:' + label] = {'status': 'published', 'request_id': 'synthetic-' + label,
                                             'task': task}
        path = root / 'ledger.json'
        if path.exists():
            records = {**json.loads(path.read_text())['requests'], **records}
        path.write_bytes(gate.canonical({'version': 1, 'requests': records}))

    def seal(self):
        bundle = self.bundle
        bundle['test_pr_task'] = signed(bundle['test_pr_task'], self.authority)
        # The Evidence names the exact Task bytes it executed, so it is recomputed from
        # the signed Task rather than carried forward from whichever edit ran last.
        bundle['test_pr_evidence']['task_canonical_sha256'] = gate.digest(
            {k: v for k, v in bundle['test_pr_task'].items() if k != 'signature'})
        for name in ('canary_task', 'preflight_task'):
            bundle[name] = signed(bundle[name], self.authority)
        for name in ('test_pr_evidence', 'canary_evidence', 'preflight_evidence'):
            bundle[name] = signed(bundle[name], self.hk, 'base64')
        for name in ('test_pr_task', 'test_pr_evidence', 'canary_task', 'canary_evidence',
                     'preflight_task', 'preflight_evidence'):
            bundle['plan'][name + '_sha256'] = gate.digest(bundle[name])
        # The plan name and the approval id are derived, so the fixture derives them too:
        # a fixture that could choose them would be testing a gate this project no longer
        # has.
        bundle['plan']['plan_id'] = gate.plan_id_for(bundle['plan']['candidate'], bundle['canary_task'])
        bundle['approval']['plan_sha256'] = gate.digest(bundle['plan'])
        bundle['approval']['approved_by'] = self.approval_identity
        bundle['approval']['request_sha256'] = self.request_sha256
        bundle['approval']['approval_id'] = gate.approval_id_for(self.request_sha256)

    def validate(self):
        return gate.validate_bundle(self.bundle, self.bundle['plan']['plan_id'],
                                    self.authority.public_key(), self.hk.public_key(),
                                    self.at, self.approval_identity, self.request_sha256)

    def request(self, number='001', **overrides):
        # The five common fields and nothing else. A DEPLOY Request used to name a plan a
        # human had written; the plan is derived now, so there is no field left for a
        # caller to steer with -- not even the plan's name.
        return {'schema_version':'1', 'request_id':'synthetic-request-'+str(number), 'action_id':gate.ACTION,
                'environment':gate.ENVIRONMENT, 'requested_at':bridge.iso(self.at), **overrides}

    def install_synthetic(self, root):
        store = root / 'plans'; store.mkdir(mode=0o700)
        for name, key in [('authority', self.authority), ('hk-evidence', self.hk)]:
            (store/(name+'.pub')).write_bytes(key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH))
        (store/(self.bundle['plan']['plan_id']+'.json')).write_bytes(gate.canonical(self.bundle))
        keypath = root / 'synthetic.pem'
        keypath.write_bytes(self.authority.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        keypath.chmod(0o600)
        # The shipped configuration is used exactly as it ships. It declares how a
        # deployment is authorised and grants nothing itself, so a test that deploys has
        # to bring the authenticated Request, the fresh canary and the preflight -- which
        # is the property this revision is about. Nothing here turns anything on.
        config = json.loads((ROOT/'config.json').read_text())
        channel = root/'channel.json'; channel.write_bytes(gate.canonical(config))
        return store, keypath, channel


class RequestTests(unittest.TestCase):
    def setUp(self): self.f = Fixture()
    def test_deploy_shape(self):
        """A DEPLOY Request is the five common fields; it steers no deployment fact."""
        parsed = bridge.validate_request(gate.canonical(self.f.request()), self.f.at)
        self.assertEqual(sorted(parsed), ['action_id', 'environment', 'request_id', 'requested_at', 'schema_version'])
    def test_a_deploy_request_naming_a_plan_is_refused(self):
        """The shape this gate no longer accepts must fail rather than be read around it."""
        for plan_id in ('synthetic-plan-001', '../plan', True, 'a/b', ''):
            with self.subTest(plan_id=plan_id), self.assertRaises(gate.Reject):
                bridge.validate_request(gate.canonical(self.f.request(plan_id=plan_id)), self.f.at)
    def test_no_caller_runtime_or_approval_override(self):
        for field in ('image_id','candidate_image_id','candidate_package_sha256','source_commit','package_sha256','services',
                      'compose_path','command','signature','approval_id','plan_id','task_id','nonce','force_recreate','deployment_authorization'):
            with self.subTest(field=field), self.assertRaises(gate.Reject):
                bridge.validate_request(gate.canonical(self.f.request(**{field:'override'})), self.f.at)
    def test_invalid_scope(self):
        for update in ({'environment':'PRODUCTION'}, {'environment':'HK-STAGING-02'},
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
        edits=[('target_services',['api']),('protected_non_targets',[]),('production',True),('migration',True),
            ('automatic_rollback',True),('environment','PRODUCTION'),
            # The four product-release declarations this plan used to carry are gone. A
            # plan that still carries them is not "a plan with extra fields"; it is the
            # retired contract, and it is refused by the exact field set.
            ('gates', {name: 'PASS' for name in ('three_end_ux','six_vertical_closed_loop',
                                                 'sealed_node','final_release')})]
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
        self.f.bundle['approval']['approval_id']='bad.dot'   # planted after sealing
        with self.assertRaises(gate.Reject): self.f.validate()
    def test_signed_canary_must_match_candidate(self):
        self.f.bundle['canary_task']['parameters']['candidate_package_sha256']='0'*64; self.f.seal()
        with self.assertRaises(gate.Reject): self.f.validate()

    def test_executor_identifier_compatibility_is_kept_but_the_name_is_derived(self):
        """The id a Task carries must be a derived one; a chosen id is refused."""
        self.f.bundle['approval']['approval_id'] = 'chosen-approval-id'
        with self.assertRaises(gate.Reject) as caught: self.f.validate()
        self.assertEqual(str(caught.exception), 'approval_id_not_derived')

    def test_a_plan_name_that_was_not_derived_is_refused(self):
        """A plan is named by the facts, so a name that does not follow is refused.

        plan_id is left alone deliberately: seal() rewrites it from the candidate, so the
        only way to test an unrelated name is to rename the plan after sealing, exactly as
        an operator or a stray file would have to.
        """
        self.f.bundle['plan']['plan_id'] = 'synthetic-plan-renamed'
        self.f.bundle['approval']['plan_sha256'] = gate.digest(self.f.bundle['plan'])
        with self.assertRaises(gate.Reject) as caught:
            gate.validate_bundle(self.f.bundle, 'synthetic-plan-renamed',
                                 self.f.authority.public_key(), self.f.hk.public_key(),
                                 self.f.at, self.f.approval_identity, self.f.request_sha256)
        self.assertEqual(str(caught.exception), 'plan_id_not_derived')

    def test_the_approval_is_bound_to_the_request_it_is(self):
        """The approval is one exact Request, not a class of them."""
        with self.assertRaises(gate.Reject) as caught:
            gate.validate_bundle(self.f.bundle, self.f.bundle['plan']['plan_id'],
                                 self.f.authority.public_key(), self.f.hk.public_key(), self.f.at,
                                 self.f.approval_identity, gate.request_digest(self.f.request('999')))
        self.assertEqual(str(caught.exception), 'approval_request_mismatch')
        with self.assertRaises(gate.Reject) as missing:
            gate.validate_bundle(self.f.bundle, self.f.bundle['plan']['plan_id'],
                                 self.f.authority.public_key(), self.f.hk.public_key(), self.f.at,
                                 self.f.approval_identity)
        self.assertEqual(str(missing.exception), 'approval_request_digest_missing')

    def test_the_signed_test_pr_is_what_replaces_sealed_node(self):
        """Every binding sealed_node stood for, refused one at a time when broken."""
        edits=[('source_commit_sha', 'f'*40),          # a TEST_PR of a different commit
               ('built_image_id', 'sha256:'+'c'*64),   # a different artifact
               ('source_pr_number', '53'),             # a different pull request
               ('executor_result', 'VERIFY_OK'),       # not a build at all
               ('status', 'REJECTED'),
               ('deployment_performed', True),         # a build step must never deploy
               ('artifact_durability', 'NOT_PROVEN')]  # the bytes are not known to exist
        for field, value in edits:
            with self.subTest(field=field):
                self.f = Fixture(); self.f.bundle['test_pr_evidence'][field] = value; self.f.seal()
                with self.assertRaises(gate.Reject): self.f.validate()

    def test_evidence_for_another_task_is_refused(self):
        """The Evidence names the exact Task bytes it executed; a digest of some other
        Task is refused. Planted after sealing, because sealing is what computes it."""
        self.f = Fixture()
        self.f.bundle['test_pr_evidence']['task_canonical_sha256'] = '0'*64
        with self.assertRaises(gate.Reject): self.f.validate()

    def test_a_test_pr_package_that_is_not_the_candidates_is_refused(self):
        for mutation in ('package_sha256', 'image_id'):
            with self.subTest(mutation=mutation):
                self.f = Fixture()
                if mutation == 'package_sha256':
                    self.f.bundle['test_pr_evidence']['artifact_package']['package_sha256'] = '0'*64
                else:
                    self.f.bundle['test_pr_evidence']['artifact_package']['image_id'] = 'sha256:'+'9'*64
                self.f.seal()
                with self.assertRaises(gate.Reject): self.f.validate()

    def test_a_test_pr_gate_that_did_not_pass_is_refused(self):
        for name in gate.TEST_PR_GATES:
            with self.subTest(gate=name):
                self.f = Fixture()
                self.f.bundle['test_pr_evidence']['gate_results'][name] = 'FAIL'
                self.f.seal()
                with self.assertRaises(gate.Reject): self.f.validate()

    def test_an_old_test_pr_of_the_same_candidate_is_still_valid(self):
        """Content-bound proof, stated positively: the artifact never expires.

        The canary and the preflight do expire, because they describe a host state; the
        TEST_PR does not, because it describes an immutable candidate. A month-old
        TEST_PR of this exact candidate is exactly as valid as today's would be.
        """
        self.f = Fixture(test_pr_age=int(dt.timedelta(days=30).total_seconds()))
        self.assertEqual(self.f.validate()['source_commit'], self.f.source)


class RollbackProofTests(unittest.TestCase):
    """What may undo a deployment, and what may not.

    A rollback is the only other action that mutates the eight business services, so its
    gate is held to the deployment's standard: the authority is the exact authenticated
    Request, what it authorises is named by content, and nothing a caller writes can widen
    either.  The source is the newest deployment the Bridge itself published -- never a
    caller's choice -- and it is proved from the two signed objects that deployment left
    behind, not from a declaration about them.
    """

    def setUp(self):
        self.f = Fixture()
        self.source_task, self.source_evidence = self.f.deploy_task, self.f.deploy_evidence
        self.release_id = 'boss-rollback-synthetic'

    def records(self, *extra, deploy=None):
        records = {'synthetic:deploy-source': {'status': 'published',
                                               'request_id': 'synthetic-deploy-source',
                                               'task': self.source_task if deploy is None else deploy}}
        for label, task in extra:
            records['synthetic:' + label] = {'status': 'published', 'request_id': 'synthetic-' + label,
                                             'task': task}
        return records

    def authorization(self, source_task=None, source_evidence=None, **overrides):
        value = derivation.derive_rollback_authorization(
            self.f.request_sha256, self.f.approval_identity,
            self.f.at - dt.timedelta(seconds=10),
            self.f.at - dt.timedelta(seconds=10) + gate.APPROVAL_MAX_LIFE,
            source_task or self.source_task, source_evidence or self.source_evidence)
        value.update(overrides)
        return value

    def derive(self, records=None, at=None, **kw):
        return derivation.derive_rollback(self.release_id, self.f.request_sha256,
            self.f.approval_identity, self.f.at - dt.timedelta(seconds=10),
            self.records() if records is None else records, self.f.read_evidence,
            self.f.authority.public_key(), self.f.hk.public_key(), self.f.at if at is None else at, **kw)

    def validate(self, authorization, task=None, evidence=None, release_id=None,
                 approval_identity='default', request_sha256=None, at=None):
        task = self.source_task if task is None else task
        if evidence is None: evidence = self.f.deploys[task['task_id']][1]
        return gate.validate_rollback(self.release_id if release_id is None else release_id,
            authorization, task, evidence, self.f.authority.public_key(), self.f.hk.public_key(),
            self.f.at if at is None else at,
            self.f.approval_identity if approval_identity == 'default' else approval_identity,
            self.f.request_sha256 if request_sha256 is None else request_sha256)

    # -- the source is the Bridge's own newest deployment, by content -------- #
    def test_the_newest_published_deployment_is_the_source(self):
        context = self.derive()
        self.assertEqual(context['action_id'], gate.ROLLBACK_ACTION)
        self.assertEqual(context['source_deploy_task_id'], self.source_task['task_id'])
        self.assertEqual(context['source_candidate_image_id'], self.f.candidate)
        self.assertEqual(context['expected_current_image_id'], self.f.current)
        self.assertEqual(set(context['parameters']), set(gate.ROLLBACK_PARAMETERS))
        self.assertEqual(context['source_deploy_task_sha256'], gate.digest(self.source_task))
        self.assertEqual(context['source_deploy_evidence_sha256'], gate.digest(self.source_evidence))

    def test_the_deadline_never_outlives_the_authorisation(self):
        context = self.derive()
        self.assertLessEqual(context['deadline'],
                             self.f.at - dt.timedelta(seconds=10) + gate.APPROVAL_MAX_LIFE)
        self.assertLessEqual(context['deadline'], self.f.at + gate.ROLLBACK_TASK_WINDOW)

    def test_record_path_is_an_annotation_and_a_real_deployment_still_validates(self):
        """The mistake this guards: applying "every gate value is PASS" to a DEPLOY Evidence.

        The deploy runtime puts `record_path` -- a filesystem path -- beside the six gates,
        so the generic rule the canary and TEST_PR proofs use would refuse every real
        deployment.  The six named gates are asserted one by one instead.
        """
        self.assertIn('record_path', self.source_evidence['gate_results'])
        self.assertEqual(set(gate.DEPLOY_GATES) - set(self.source_evidence['gate_results']), set())
        self.derive()

    def test_no_published_deployment_means_nothing_to_roll_back(self):
        with self.assertRaisesRegex(gate.Reject, 'rollback_source_missing'):
            self.derive(records={})

    def test_a_ledger_holding_only_probes_has_nothing_to_roll_back(self):
        records = {'synthetic:canary': {'status': 'published', 'task': self.f.bundle['canary_task']},
                   'synthetic:preflight': {'status': 'published', 'task': self.f.bundle['preflight_task']},
                   'synthetic:test-pr': {'status': 'published', 'task': self.f.bundle['test_pr_task']}}
        with self.assertRaisesRegex(gate.Reject, 'rollback_source_missing'):
            self.derive(records=records)

    def test_an_unpublished_deployment_is_not_yet_a_source(self):
        records = {'synthetic:deploy-source': {'status': 'publishing', 'task': self.source_task}}
        with self.assertRaisesRegex(gate.Reject, 'rollback_source_missing'):
            self.derive(records=records)

    def test_the_newest_deployment_wins_and_there_is_no_fallback_to_an_older_one(self):
        """A newer deployment whose Evidence is missing stops the derivation.

        Falling back to the older one would describe a host state the newer deployment has
        already replaced, which is not the act anyone asked for -- and the Hong Kong
        executor refuses it from the other side for the same reason.
        """
        newer, _evidence = self.f.deploy_source(task_id='go-boss-deploy-synthetic-newer', age=30)
        self.f.deploys.pop('go-boss-deploy-synthetic-newer')
        with self.assertRaisesRegex(gate.Reject, 'rollback_source_evidence_unreadable'):
            self.derive(records=self.records(('newer', newer)))

    def test_a_deployment_whose_evidence_was_refused_is_not_a_source(self):
        self.f.deploys[self.source_task['task_id']] = (self.source_task, self.f.resign(
            {**self.source_evidence, 'status': 'REJECTED'}, self.f.hk))
        with self.assertRaisesRegex(gate.Reject, 'rollback_source_not_success'):
            self.derive()

    def test_a_deployment_that_did_not_report_deploy_ok_is_not_a_source(self):
        self.f.deploys[self.source_task['task_id']] = (self.source_task, self.f.resign(
            {**self.source_evidence, 'executor_result': 'DEPLOY_REJECTED'}, self.f.hk))
        with self.assertRaisesRegex(gate.Reject, 'rollback_source_result'):
            self.derive()

    def test_a_deployment_with_a_failed_gate_is_not_a_source(self):
        self.f.deploy_source(task_id='go-boss-deploy-synthetic-source',
                             gates={**{k: 'PASS' for k in gate.DEPLOY_GATES}, 'current_state': 'FAIL'})
        with self.assertRaisesRegex(gate.Reject, 'rollback_source_gate_failed'):
            self.derive()

    def test_a_record_that_is_not_schema_two_is_refused(self):
        self.f.deploys[self.source_task['task_id']] = (self.source_task, self.f.resign(
            {**self.source_evidence, 'deploy_record_schema_version': '1'}, self.f.hk))
        with self.assertRaisesRegex(gate.Reject, 'rollback_source_record_binding'):
            self.derive()

    def test_a_record_identity_that_is_not_a_digest_is_refused(self):
        for field in ('deploy_record_id', 'deploy_record_sha256'):
            with self.subTest(field=field):
                self.f.deploy_source()
                self.f.deploys[self.source_task['task_id']] = (self.source_task, self.f.resign(
                    {**self.source_evidence, field: 'not-a-digest'}, self.f.hk))
                with self.assertRaisesRegex(gate.Reject, 'rollback_source_record_binding'):
                    self.derive()

    def test_a_source_task_that_is_not_a_deployment_is_refused(self):
        other = self.f.bundle['canary_task']
        with self.assertRaisesRegex(gate.Reject, 'rollback_source_scope'):
            self.validate(self.authorization(), task=other,
                          evidence=self.f.bundle['canary_evidence'])

    def test_a_source_carrying_a_parameter_the_deployment_never_sends_is_refused(self):
        parameters = {**self.source_task['parameters'], 'rollback_image': self.f.current}
        task = self.f.resign({**self.source_task, 'parameters': parameters}, self.f.authority, 'hex')
        self.f.deploys[task['task_id']] = (task, self.source_evidence)
        with self.assertRaisesRegex(gate.Reject, 'rollback_source_parameters'):
            self.derive(records=self.records(deploy=task))

    def test_an_unsigned_or_foreign_source_task_is_refused(self):
        task = {k: v for k, v in self.source_task.items() if k != 'signature'}
        with self.assertRaisesRegex(gate.Reject, 'missing_signature'):
            self.validate(self.authorization(), task=task)
        other = Ed25519PrivateKey.generate()
        foreign = self.f.resign(task, other, 'hex')
        with self.assertRaisesRegex(gate.Reject, 'invalid_signature'):
            self.validate(self.authorization(), task=foreign)

    # -- the authorisation is the Request, bound to the pair ----------------- #
    def test_the_authorisation_is_bound_to_the_pair_it_undoes(self):
        for field in ('source_deploy_task_sha256', 'source_deploy_evidence_sha256'):
            with self.subTest(field=field):
                with self.assertRaisesRegex(gate.Reject, 'rollback_authorization_binding'):
                    self.validate(self.authorization(**{field: 'a' * 64}))

    def test_the_approval_id_is_derived_not_chosen(self):
        with self.assertRaisesRegex(gate.Reject, 'rollback_approval_id_not_derived'):
            self.validate(self.authorization(approval_id='approval-' + 'b' * 16))

    def test_a_rollback_approval_and_a_deploy_approval_are_not_interchangeable(self):
        self.assertNotEqual(gate.rollback_approval_id_for(self.f.request_sha256),
                            gate.approval_id_for(self.f.request_sha256))
        with self.assertRaisesRegex(gate.Reject, 'rollback_approval_id_not_derived'):
            self.validate(self.authorization(
                approval_id=gate.approval_id_for(self.f.request_sha256)))

    def test_the_authorisation_cannot_be_borrowed_for_another_request(self):
        with self.assertRaisesRegex(gate.Reject, 'approval_request_mismatch'):
            self.validate(self.authorization(), request_sha256='c' * 64)

    def test_the_authorisation_field_set_is_exact(self):
        value = self.authorization(); value['extra'] = 'x'
        with self.assertRaisesRegex(gate.Reject, 'rollback_authorization_fields'):
            self.validate(value)
        for field in gate.ROLLBACK_AUTHORIZATION_FIELDS:
            with self.subTest(field=field):
                value = self.authorization(); value.pop(field)
                with self.assertRaisesRegex(gate.Reject, 'rollback_authorization_fields'):
                    self.validate(value)

    def test_the_authorisation_scope_is_the_rollback_scope(self):
        with self.assertRaisesRegex(gate.Reject, 'rollback_scope'):
            self.validate(self.authorization(scope='HK_STAGING_DEPLOY_FIXED_EIGHT'))

    def test_a_release_id_that_is_not_an_identifier_is_refused(self):
        for value in ('../escape', 'x;id', '', 'a' * 81):
            with self.subTest(value=value):
                with self.assertRaisesRegex(gate.Reject, 'rollback_release_id'):
                    self.validate(self.authorization(), release_id=value)

    def test_the_authorisation_must_be_authorised_by_an_authenticated_identity(self):
        with self.assertRaisesRegex(gate.Reject, 'approval_identity_missing'):
            self.validate(self.authorization(), approval_identity=None)
        for value in ('someone-else', '', 'Yuguangzhi3836-Glitch'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(gate.Reject, 'approval_identity_not_authorised'):
                    self.validate(self.authorization(), approval_identity=value)

    def test_the_authorisation_cannot_borrow_another_authorised_name(self):
        other = gate.APPROVAL_IDENTITIES[1]
        with self.assertRaisesRegex(gate.Reject, 'approval_identity_mismatch'):
            self.validate(self.authorization(approved_by=other))

    def test_the_authorisation_expires(self):
        approved = self.f.at - dt.timedelta(seconds=10)
        for expires in (approved - dt.timedelta(seconds=1), approved + dt.timedelta(hours=1),
                        self.f.at + dt.timedelta(seconds=30)):
            with self.subTest(expires=expires):
                with self.assertRaisesRegex(gate.Reject, 'approval_expired_or_invalid'):
                    self.validate(self.authorization(expires_at=bridge.iso(expires)))

    def test_the_authorisation_must_postdate_the_source_evidence(self):
        """A rollback cannot be authorised before the deployment it undoes has finished."""
        completed = dt.datetime.fromisoformat(
            self.source_evidence['completed_at'].replace('Z', '+00:00'))
        approved = completed - dt.timedelta(seconds=1)
        # The life is shortened with the approval, so the refusal under test is the
        # ordering rule and not the lifetime rule.
        with self.assertRaisesRegex(gate.Reject, 'approval_predates_evidence'):
            self.validate(self.authorization(approved_at=bridge.iso(approved),
                expires_at=bridge.iso(approved + gate.APPROVAL_MAX_LIFE)))

    # -- one-time, and only one rollback per deployment ---------------------- #
    def test_a_source_is_spent_by_any_published_rollback_that_cites_it(self):
        source = self.source_task['task_id']
        published = {'1:' + 'a' * 40: {'status': 'published',
            'task': {'action_id': gate.ROLLBACK_ACTION,
                     'parameters': {'source_deploy_task_id': source}}}}
        with self.assertRaisesRegex(gate.Reject, 'rollback_source_already_rolled_back'):
            gate.ensure_rollback_unused(published, source)

    def test_an_unpublished_rollback_has_not_spent_its_source(self):
        source = self.source_task['task_id']
        gate.ensure_rollback_unused({}, source)
        for status in ('claiming', 'prepared', 'publishing'):
            gate.ensure_rollback_unused({'2:' + 'b' * 40: {'status': status,
                'task': {'action_id': gate.ROLLBACK_ACTION,
                         'parameters': {'source_deploy_task_id': source}}}}, source)
        gate.ensure_rollback_unused({'3:' + 'c' * 40: {'status': 'published',
            'task': {'action_id': gate.ACTION, 'parameters': {'source_deploy_task_id': source}}}}, source)
        gate.ensure_rollback_unused({'4:' + 'd' * 40: {'status': 'published',
            'task': {'action_id': gate.ROLLBACK_ACTION,
                     'parameters': {'source_deploy_task_id': 'go-boss-deploy-other'}}}}, source)

    # -- the cross-component contract, pinned against the consumer ---------- #
    def test_the_derived_parameters_are_exactly_what_the_hk_agent_accepts(self):
        """Our parameter contract is a claim about the agent; this checks it against it.

        `ROLLBACK_PARAMETERS` is three names because the Hong Kong agent's own validator
        refuses any other name and any missing one.  Rather than restating that here, the
        derived block is handed to the agent's validator and to its argv builder: a fourth
        parameter added on either side fails this test.
        """
        context = self.derive()
        parameters = context['parameters']
        self.assertEqual(deployment_actions.validate(gate.ROLLBACK_ACTION, parameters), parameters)
        command = deployment_actions.argv(gate.ROLLBACK_ACTION, parameters,
            {'task_id': 't', 'nonce': 'n', 'authority': 'GO-COMMAND-CENTER',
             'canonical_sha256': 'a' * 64})
        self.assertEqual(command[:6], [deployment_actions.EXECUTOR_PATH, 'rollback',
                                       '--release-id', parameters['release_id'],
                                       '--source-deploy-task-id', parameters['source_deploy_task_id']])
        self.assertIn('--approval-id', command)
        for extra in ('candidate_image_id', 'rollback_image', 'services', 'compose_file',
                      'env_file', 'target', 'command', 'executor_path'):
            with self.subTest(extra=extra):
                with self.assertRaises(deployment_actions.Reject):
                    deployment_actions.validate(gate.ROLLBACK_ACTION, {**parameters, extra: 'x'})

    def test_the_agent_accepts_the_rollback_evidence_shape_this_gate_expects(self):
        """The executor result the Bridge will read back, built by the agent's own builder.

        The rollback Evidence carries five record fields the deployment's does not.  They
        are asserted here through `transport.evidence`, so the names come from the producer
        rather than from this test's idea of them.
        """
        task = {'task_id': 'go-boss-rollback-synthetic', 'nonce': 'n',
                'action_id': gate.ROLLBACK_ACTION, 'environment': gate.ENVIRONMENT}
        result = {'schema_version': '1', 'executor_version': '0.4.3-rollback-runtime',
                  'action_id': gate.ROLLBACK_ACTION, 'status': 'SUCCESS',
                  'release_id': 'boss-rollback-synthetic', 'candidate_image_id': '',
                  'expected_current_image_id': '', 'result': 'ROLLBACK_OK', 'gate_results': {},
                  'source_deploy_task_id': self.source_task['task_id'],
                  'source_deploy_record_id': 'a' * 64, 'source_deploy_record_sha256': 'b' * 64,
                  'rollback_record_id': 'c' * 64, 'rollback_record_sha256': 'd' * 64}
        evidence = transport.evidence(task, result)
        self.assertEqual(evidence['executor_result'], 'ROLLBACK_OK')
        self.assertEqual(evidence['source_deploy_task_id'], self.source_task['task_id'])
        for field in ('source_deploy_record_id', 'source_deploy_record_sha256',
                      'rollback_record_id', 'rollback_record_sha256'):
            self.assertRegex(evidence[field], r'^[0-9a-f]{64}$')


class StorageTests(unittest.TestCase):
    def test_secure_plan_load_and_absence(self):
        f=Fixture()
        with tempfile.TemporaryDirectory() as raw:
            root=pathlib.Path(raw); store,_,_=f.install_synthetic(root)
            with patch.object(gate,'STORE',store),patch.object(gate,'TRUSTED_UID',os.getuid()):
                name=f.bundle['plan']['plan_id']
                self.assertEqual(gate.load_context(name,f.at,
                                                gate.APPROVAL_IDENTITIES[0],f.request_sha256)['plan_id'],name)
                with self.assertRaises(gate.Reject): gate.load_context('missing-plan',f.at)
    def test_symlink_writable_oversized_and_bad_owner(self):
        with tempfile.TemporaryDirectory() as raw:
            root=pathlib.Path(raw); target=root/'record'; target.write_text('hello')
            alias=root/'alias'
            try: alias.symlink_to(target)
            except OSError: self.skipTest('this platform cannot create a symlink here')
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
    def test_the_shipped_configuration_declares_the_mode_and_grants_nothing(self):
        """There is no switch to ship on, and none to ship off either.

        The file declares how deployments are authorised and carries no authorisation
        of its own, so no capability is inherited by whatever Request arrives next.
        """
        shipped=json.loads((ROOT/'config.json').read_text())
        self.assertEqual(shipped['deployment_authorization'],bridge.AUTHORIZATION_MODE)
        self.assertNotIn('deployment_requests_enabled',shipped)
        self.assertEqual(bridge.channel_v4(dict(shipped)),shipped)
    def test_a_channel_that_does_not_declare_the_mode_is_refused(self):
        shipped=json.loads((ROOT/'config.json').read_text())
        for value in ({k:v for k,v in shipped.items() if k!='deployment_authorization'},
                      {**shipped,'deployment_requests_enabled':True},
                      {**shipped,'deployment_authorization':None},
                      {**shipped,'deployment_authorization':''}):
            with self.subTest(field='deployment_authorization',value=value.get('deployment_authorization')), \
                 self.assertRaises(gate.Reject):
                bridge.channel_v4(value)
    def test_a_malformed_channel_is_refused(self):
        with tempfile.TemporaryDirectory() as raw:
            p=pathlib.Path(raw)/'config'; p.write_text('[]')
            with self.assertRaises(gate.Reject): bridge.load_channel(p)


class MetadataTests(unittest.TestCase):
    def test_pr_metadata_open_base_same_repo_exact_head(self):
        good={'state':'open','draft':False,'merged':False,
            'created_at':'2026-09-15T00:58:30Z',
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
                  {**good,'head':{**good['head'],'repo':{'full_name':'fork/tasks'}}},
                  # The moment the platform says the approval was given is what the
                  # approval window is measured from, so a metadata answer without one is
                  # not usable rather than defaulted to "now".
                  {k: v for k, v in good.items() if k != 'created_at'},
                  {**good,'created_at':'yesterday'}]
            for bad in bads:
                opener.return_value.open.return_value=Response(bad)
                with self.subTest(bad=bad), self.assertRaises(gate.Reject): bridge.check_deploy_pr('2','a'*40)
    def test_missing_metadata_credentials_fails_closed(self):
        with patch.object(gate,'read_secure',side_effect=gate.Reject('missing')):
            with self.assertRaises(gate.Reject): bridge.check_deploy_pr('2','a'*40)


OWNER = os.getuid() if hasattr(os, 'getuid') else 0


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture(); self.tmp=tempfile.TemporaryDirectory(); self.root=pathlib.Path(self.tmp.name)
        self.store,self.key,self.channel=self.f.install_synthetic(self.root)
        # The plan is derived now, so the queue starts without one: writing it from the
        # facts is the behaviour under test, not a precondition of the test.
        for leftover in self.store.glob('*.json'): leftover.unlink()
        # The Bridge publishes one Task per Request, so the records for the sealed
        # TEST_PR, the canary and the preflight are the history it derives a plan from.
        self.f.seed_ledger(self.root/'ledger')
        self.stack=ExitStack(); self.addCleanup(self.stack.close); self.addCleanup(self.tmp.cleanup)
        self.stack.enter_context(patch.object(gate,'STORE',self.store))
        self.stack.enter_context(patch.object(gate,'TRUSTED_UID',os.getuid()))
        self.stack.enter_context(patch.object(bridge,'now',return_value=self.f.at))
        self.stack.enter_context(patch.object(bridge,'check_deploy_pr',
            return_value=({'created_at':bridge.iso(self.f.at-dt.timedelta(seconds=10))},
                          gate.APPROVAL_IDENTITIES[0])))
        # The plan is derived, so these three readers are the seams: the GO repository
        # (candidate admission), the evidence repository (the signed TEST_PR, canary and
        # preflight Evidence) and the root-owned baseline the preflight was derived from.
        self.stack.enter_context(patch.object(bridge,'read_admission',side_effect=self.f.admission_pointer))
        self.stack.enter_context(patch.object(bridge,'read_evidence',side_effect=self.f.read_evidence))
        self.stack.enter_context(patch.object(bridge,'load_baseline',side_effect=self.f.verify_baseline))
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
    def test_the_authorization_is_the_request_and_is_recorded_as_such(self):
        """The one-time authorisation the Command Center establishes, and where it lives.

        Nothing in it was written by a human: the approval id is a function of the
        Request's canonical digest rather than a name anybody chose, the plan carries
        that same digest, and the ledger records both under the identity GitHub
        reported. That triple is what makes the authorisation both attributable and
        single-use -- the plan file is never overwritten and the ledger never re-issues
        an authorisation it has already recorded.
        """
        self.assertEqual(self.run_request()['status'],'published')
        digest_value=gate.request_digest(self.f.request('2'))
        records=json.loads((self.root/'ledger/ledger.json').read_text())['requests']
        mine=[r for r in records.values() if r.get('request_id')==self.f.request('2')['request_id']][0]
        self.assertEqual(mine['request_sha256'],digest_value)
        self.assertEqual(mine['approval_id'],gate.approval_id_for(digest_value))
        self.assertEqual(mine['approval_identity'],gate.APPROVAL_IDENTITIES[0])
        plan=json.loads((self.store/(mine['plan_id']+'.json')).read_text())
        self.assertEqual(plan['approval']['request_sha256'],digest_value)
        self.assertEqual(plan['approval']['approval_id'],gate.approval_id_for(digest_value))
        self.assertEqual(plan['approval']['approved_by'],gate.APPROVAL_IDENTITIES[0])
        # and the authorisation cannot outlive the deployment it authorises
        self.assertLessEqual(plan['approval']['expires_at'],
                             plan['approval']['approved_at'][:11]+'99')
    def test_a_consumed_plan_and_approval_are_never_reused(self):
        """Two Requests against the same facts give the same plan, and it is spent once.

        The name is a function of the candidate and the canary run, so a second Request
        cannot ask for a new plan by asking for a new name -- it lands on the same plan
        and the ledger refuses it. There is no name left for a caller to choose.
        """
        self.run_request()
        with self.assertRaisesRegex(gate.Reject,'already_consumed'): self.run_request('3')
        self.assertEqual(len(list(self.store.glob('*.json'))),1)
        self.assertEqual(self.publisher.call_count,1)
    def test_deploy_refused_while_the_authorization_mode_is_not_request(self):
        """The emergency stop: any mode but `request` silences deployments.

        It only ever stops. A channel whose mode does not accept cannot be turned into
        one that grants, because the mode is not where the authority lives.
        """
        self.config(deployment_authorization='suspended')
        with patch.object(bridge,'sign') as signer:
            with self.assertRaisesRegex(gate.Reject,'deployment_authorization_mode_unsupported'): self.run_request()
            signer.assert_not_called(); self.publisher.assert_not_called()
    def test_the_declared_mode_does_not_authorise_a_deployment_by_itself(self):
        """The property that replaces the switch.

        The shipped mode is the accepting one, and a deployment is refused anyway when
        the Request was not opened by an authorised identity. So there is no
        configuration state an operator could set that would deploy anything: the
        authority is the authenticated Request and nothing else.
        """
        self.stack.enter_context(patch.object(bridge,'check_deploy_pr',
            side_effect=gate.Reject('request_pr_author_not_authorised')))
        with patch.object(bridge,'sign') as signer:
            with self.assertRaisesRegex(gate.Reject,'not_authorised'): self.run_request()
            signer.assert_not_called(); self.publisher.assert_not_called()
    def test_an_unwritable_plan_store_is_a_refusal_not_a_crash(self):
        """The store's writability is the host's job; a failure here must not kill the tick.

        The Command Center unit sandboxes the service (`ProtectSystem=strict` with an
        explicit `ReadWritePaths` list), so "the plan store is not writable" is a
        configuration state that really occurs -- and when it does, refusing this one
        Request is required: an escaping error would end the tick and stop VERIFY,
        TEST_PR, CANARY and HEALTH from being served as well.

        The denial has to be a real one.  chmod alone does not produce it for uid 0:
        root holds CAP_DAC_OVERRIDE, so an 0500 store is still writable and the test
        would pass only by never exercising the branch.  So the write is attempted as
        an unprivileged identity, and where no such identity is available the test is
        skipped rather than left to pass vacuously.  (The live service runs as root, so
        on the real host a refused write comes from the unit's ProtectSystem /
        ReadWritePaths sandbox, not from the directory mode.)

        Two mechanisms can produce the denial and both are covered here, because which
        one is reachable depends on the identity the suite runs as:

          * an unprivileged process: the directory mode itself denies the write, so
            chmod 0500 is enough and the real PermissionError travels the real path.
          * uid 0 (this project's CI host, and the live service, which runs as root):
            root bypasses the mode bits, so the denial comes from the unit sandbox
            instead.  `os.open` is driven to raise the PermissionError that sandbox
            produces, and the same assertion runs on the same branch.

        A test that simply chmods and asserts would pass as root without ever entering
        the refusal branch -- it would be asserting nothing.  That is the specific
        failure this version replaces.
        """
        if MODE_BITS_DENY_WRITES:
            self.store.chmod(0o500)
            try:
                with self.assertRaisesRegex(gate.Reject,'plan_store_unwritable'):
                    self.run_request()
            finally:
                self.store.chmod(0o700)
        else:
            # The unit's sandbox denies writes to the plan store and leaves everything
            # else -- including the Bridge's own ledger -- writable.  Model exactly
            # that: deny O_CREAT/O_WRONLY paths that land inside the store, pass every
            # other call through untouched.
            real_open=os.open
            store=str(self.store)
            denied=[]
            def sandbox(path,mode,*rest,**kw):
                writing=bool(mode & (os.O_WRONLY|os.O_RDWR|os.O_CREAT))
                if writing and str(path).startswith(store):
                    denied.append(str(path))
                    raise PermissionError(13,'Permission denied')
                return real_open(path,mode,*rest,**kw)
            with patch.object(os,'open',side_effect=sandbox):
                with self.assertRaisesRegex(gate.Reject,'plan_store_unwritable'):
                    self.run_request()
            self.assertTrue(denied,
                            'no write inside the store was attempted, so nothing was denied')
        self.publisher.assert_not_called()
        self.assertEqual(list(self.store.glob('.*.tmp')),[])
    def test_request_filename_binding(self):
        with patch.object(bridge,'read_pr',return_value={'path':'requests/wrong.json','raw':gate.canonical(self.f.request())}):
            with self.assertRaisesRegex(gate.Reject,'filename'): self.run_request()
        self.publisher.assert_not_called()
    def test_midflight_head_change_consumes_claim_without_publish(self):
        with patch.object(bridge,'check_deploy_pr',
                side_effect=[({'created_at':bridge.iso(self.f.at-dt.timedelta(seconds=10))},
                              gate.APPROVAL_IDENTITIES[0]),gate.Reject('changed')]):
            with self.assertRaisesRegex(gate.Reject,'changed'): self.run_request()
        with self.assertRaisesRegex(gate.Reject,'ambiguous'): self.run_request()
        self.publisher.assert_not_called()
    def test_midflight_authorization_mode_suspension(self):
        """A deployment already claimed is stopped when the mode stops accepting."""
        original=bridge.sign
        def suspend(*a):
            result=original(*a); self.config(deployment_authorization='suspended'); return result
        with patch.object(bridge,'sign',side_effect=suspend):
            with self.assertRaisesRegex(gate.Reject,'deployment_authorization_mode_unsupported'): self.run_request()
        self.publisher.assert_not_called()
    def test_midflight_plan_replacement(self):
        """A plan that changes under a live claim is refused, not silently deployed.

        The change has to be one that leaves the bundle *valid*, or a smaller check would
        catch it first and this one would never be exercised: the plan is a deterministic
        function of the facts, so the only part of a valid bundle that can differ without
        changing the plan's name is the approval's own timing.
        """
        original=bridge.sign
        def change(*a):
            result=original(*a)
            path=next(self.store.glob('*.json'))     # the plan the Bridge just registered
            registered=json.loads(path.read_text())
            registered['approval']['expires_at']=bridge.iso(self.f.at+dt.timedelta(minutes=12))
            path.write_text(json.dumps(registered))
            return result
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
    @unittest.skipUnless(hasattr(os,'fork'),'this platform has no fork start method')
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
        # The ledger also holds the seeded TEST_PR / canary / preflight history the plan is
        # derived from, and the earlier deployment a rollback would undo, so what has to be
        # exactly one is the DEPLOY record *this run* published -- not the seeded history,
        # which the fixture writes under its own `synthetic:` prefix.
        deploys=[r for key,r in records.items() if not key.startswith('synthetic:')
                 and (r.get('task') or {}).get('action_id')==gate.ACTION]
        self.assertEqual(len(deploys),1)
    def test_test_pr_preserved_with_exact_resolved_source(self):
        request=self.f.request(); request.update(action_id=bridge.TEST_ACTION,pr_number='47')
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


    # ------------------------------------------------------------------ #
    # ROLLBACK through the channel
    # ------------------------------------------------------------------ #
    def rollback_request(self, n):
        return {'schema_version': '1', 'request_id': 'synthetic-rollback-' + str(n),
                'action_id': gate.ROLLBACK_ACTION, 'environment': gate.ENVIRONMENT,
                'requested_at': bridge.iso(self.f.at)}
    def run_rollback(self, n='9'):
        def reader(number, head):
            request = self.rollback_request(n)
            return {'path': 'requests/' + request['request_id'] + '.json',
                    'raw': gate.canonical(request)}
        with patch.object(bridge, 'read_pr', side_effect=reader):
            return bridge.persistent_process(n, 'f' * 40, self.root / 'ledger', self.key, self.channel)
    def rollback_record(self, n='9'):
        records = json.loads((self.root / 'ledger/ledger.json').read_text())['requests']
        return [r for r in records.values() if r.get('request_id') == 'synthetic-rollback-' + str(n)][0]
    def test_a_rollback_of_the_published_deployment_is_derived_signed_and_published(self):
        out = self.run_rollback()
        self.assertEqual(out['status'], 'published')
        task = json.loads((self.remote / (out['task_id'] + '.json')).read_text())
        self.assertEqual(task['action_id'], gate.ROLLBACK_ACTION)
        self.assertEqual(set(task['parameters']), set(gate.ROLLBACK_PARAMETERS))
        self.assertEqual(task['parameters']['source_deploy_task_id'], self.f.deploy_task['task_id'])
        self.assertEqual(task['task_id'], 'go-' + task['parameters']['release_id'])
        digest_value = gate.request_digest(self.rollback_request('9'))
        self.assertEqual(task['parameters']['approval_id'], gate.rollback_approval_id_for(digest_value))
        # The Task is the Command Center's own signature, and the agent's validator accepts
        # the published block exactly as written.
        unsigned = {k: v for k, v in task.items() if k != 'signature'}
        self.f.authority.public_key().verify(bytes.fromhex(task['signature']), gate.canonical(unsigned))
        self.assertEqual(deployment_actions.validate(gate.ROLLBACK_ACTION, task['parameters']),
                         task['parameters'])
    def test_a_rollback_registers_no_plan_and_records_no_plan_fields(self):
        before = set(self.store.glob('*.json'))
        out = self.run_rollback()
        self.assertEqual(set(self.store.glob('*.json')), before)
        record = self.rollback_record()
        for field in ('plan_id', 'plan_sha256', 'bundle_sha256'):
            self.assertNotIn(field, record)
        self.assertEqual(record['source_deploy_task_id'], self.f.deploy_task['task_id'])
        self.assertEqual(record['release_id'], 'boss-rollback-' + out['task_id'].split('boss-rollback-')[1])
    def test_a_second_rollback_of_the_same_deployment_is_refused(self):
        self.assertEqual(self.run_rollback('9')['status'], 'published')
        with self.assertRaisesRegex(gate.Reject, 'rollback_source_already_rolled_back'):
            self.run_rollback('10')
        self.assertEqual(len(list(self.remote.glob('*.json'))), 1)
    def test_a_rollback_is_silenced_by_the_same_emergency_stop_as_a_deployment(self):
        self.config(deployment_authorization='suspended')
        with patch.object(bridge, 'sign') as signer:
            with self.assertRaisesRegex(gate.Reject, 'deployment_authorization_mode_unsupported'):
                self.run_rollback()
            signer.assert_not_called(); self.publisher.assert_not_called()
    def test_a_newer_deployment_landing_before_publication_stops_the_rollback(self):
        """The source is re-derived from the durable ledger, not taken from the claim.

        A deployment that reaches the ledger between the claim and the publication changes
        which deployment is the newest, and a rollback of the older one would no longer be
        the act the identity authorised -- so nothing is published.
        """
        newer, _evidence = self.f.deploy_source(task_id='go-boss-deploy-synthetic-newer', age=30)
        calls = {'n': 0}
        def hook(number, head):
            calls['n'] += 1
            if calls['n'] == 2:
                path = self.root / 'ledger/ledger.json'
                data = json.loads(path.read_text())
                data['requests']['synthetic:newer-deploy'] = {'status': 'published',
                    'request_id': 'synthetic-newer-deploy', 'task': newer}
                path.write_bytes(gate.canonical(data))
            return ({'created_at': bridge.iso(self.f.at - dt.timedelta(seconds=10))},
                    gate.APPROVAL_IDENTITIES[0])
        self.stack.enter_context(patch.object(bridge, 'check_deploy_pr', side_effect=hook))
        with self.assertRaisesRegex(gate.Reject, 'rollback_source_changed'):
            self.run_rollback()
        self.assertEqual(list(self.remote.glob('*.json')), [])
    def test_a_source_evidence_that_changed_before_publication_stops_the_rollback(self):
        """The Evidence is re-read from the repository, so a replaced one is caught."""
        task_id = self.f.deploy_task['task_id']
        calls = {'n': 0}
        def hook(number, head):
            calls['n'] += 1
            if calls['n'] == 2:
                changed = {k: v for k, v in self.f.deploy_evidence.items() if k != 'signature'}
                changed['started_at'] = bridge.iso(self.f.at - dt.timedelta(seconds=91))
                self.f.deploys[task_id] = (self.f.deploy_task, signed(changed, self.f.hk, 'base64'))
            return ({'created_at': bridge.iso(self.f.at - dt.timedelta(seconds=10))},
                    gate.APPROVAL_IDENTITIES[0])
        self.stack.enter_context(patch.object(bridge, 'check_deploy_pr', side_effect=hook))
        with self.assertRaisesRegex(gate.Reject, 'rollback_source_changed'):
            self.run_rollback()
        self.assertEqual(list(self.remote.glob('*.json')), [])
    def test_a_rollback_cannot_deploy_and_a_deployment_cannot_undo(self):
        """The two actions stay separate: neither Request can produce the other's Task.

        The rollback runs first because a deployment published afterwards would become the
        newest deployment -- and therefore the only thing a further rollback could undo.
        """
        rollback = self.run_rollback('9')
        body = json.loads((self.remote / (rollback['task_id'] + '.json')).read_text())
        self.assertEqual(body['action_id'], gate.ROLLBACK_ACTION)
        deploy = self.run_request()
        self.assertEqual(deploy['status'], 'published')
        task = json.loads((self.remote / (deploy['task_id'] + '.json')).read_text())
        self.assertEqual(task['action_id'], gate.ACTION)
        self.assertNotEqual(task['task_id'], body['task_id'])
        self.assertEqual(set(task['parameters']) - set(body['parameters']),
                         {'candidate_image_id', 'candidate_package_sha256',
                          'expected_current_image_id', 'canary_evidence_id'})


class DerivationTests(unittest.TestCase):
    """The plan is derived, so what has to be proven is that it cannot be steered.

    Every test here drives the real derivation with injected readers: there is no plan
    to write, and no field in a Request that could reach any of these inputs.
    """

    def setUp(self):
        self.f=Fixture(); self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name); self.store=self.root/'plans'; self.store.mkdir(mode=0o700)
        for name,key in (('authority',self.f.authority),('hk-evidence',self.f.hk)):
            (self.store/(name+'.pub')).write_bytes(key.public_key().public_bytes(
                serialization.Encoding.OpenSSH,serialization.PublicFormat.OpenSSH))
        self.records={}
        for label,name in (('test-pr','test_pr_task'),('canary','canary_task'),('preflight','preflight_task')):
            self.records['synthetic:'+label]={'status':'published','request_id':'synthetic-'+label,'task':self.f.bundle[name]}
        self.stack=ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(gate,'TRUSTED_UID',OWNER))

    def derive(self,**over):
        kwargs=dict(at=self.f.at,approval_identity=self.f.approval_identity,
                    approved_at=self.f.at-dt.timedelta(seconds=10),request_sha256=self.f.request_sha256,
                    admission=self.f.admission_pointer(),verify_baseline=self.f.verify_baseline(),
                    ledger_records=self.records,read_evidence=self.f.read_evidence)
        kwargs.update(over)
        return derivation.derive(**kwargs)

    def validate(self,plan_id,bundle):
        return gate.validate_bundle(bundle,plan_id,self.f.authority.public_key(),
                                    self.f.hk.public_key(),self.f.at,self.f.approval_identity,
                                    self.f.request_sha256)

    def test_a_full_derivation_is_a_valid_plan(self):
        plan_id,bundle=self.derive()
        context=self.validate(plan_id,bundle)
        self.assertEqual(context['plan_id'],plan_id)
        self.assertEqual(sorted(bundle),sorted(gate.BUNDLE_FIELDS))
        self.assertEqual(sorted(bundle['plan']),sorted(gate.PLAN_FIELDS))
        self.assertEqual(self.admit(plan_id,bundle),'written')
        self.assertEqual(self.admit(plan_id,bundle),'unchanged')

    def admit(self,plan_id,bundle):
        return derivation.register(self.store,plan_id,bundle)

    def test_the_plan_name_is_a_function_of_the_candidate_and_the_canary(self):
        first,_=self.derive()
        self.assertEqual(first,self.derive()[0])
        # A fresh canary -- which a retry needs, because a spent plan is never reused --
        # legitimately yields a fresh name, and nothing else does.
        self.records['synthetic:canary']['task']=dict(self.records['synthetic:canary']['task'])
        second=gate.plan_id_for(self.f.bundle['plan']['candidate'],self.f.bundle['canary_task'])
        self.assertEqual(first,second)
        other=gate.plan_id_for({'source_commit':'0'*40,'image_id':'sha256:'+'0'*64},self.f.bundle['canary_task'])
        self.assertNotEqual(first,other)

    def test_register_never_overwrites_a_different_plan(self):
        plan_id,bundle=self.derive()
        self.admit(plan_id,bundle)
        with self.assertRaises(gate.Reject) as caught:
            derivation.register(self.store,plan_id,self.derive(approved_at=self.f.at-dt.timedelta(seconds=40))[1])
        self.assertEqual(str(caught.exception),'registered_plan_differs_from_derivation')

    def test_register_refuses_a_symlinked_plan_path(self):
        plan_id,bundle=self.derive()
        try: (self.store/(plan_id+'.json')).symlink_to(self.root/'elsewhere')
        except (OSError,NotImplementedError): self.skipTest('this platform cannot create a symlink here')
        with self.assertRaises(gate.Reject) as caught: derivation.register(self.store,plan_id,bundle)
        self.assertEqual(str(caught.exception),'plan_path_is_a_symlink')

    def test_no_canary_for_this_candidate_is_a_refusal(self):
        for binding in ({'candidate_image_id':'sha256:'+'9'*64},
                        {'candidate_package_sha256':'0'*64},
                        {'expected_current_image_id':'sha256:'+'9'*64}):
            with self.subTest(binding=binding):
                self.f=Fixture(); self.setUp_records()
                task=dict(self.records['synthetic:canary']['task'],
                          parameters={**self.records['synthetic:canary']['task']['parameters'],**binding})
                self.records['synthetic:canary']={**self.records['synthetic:canary'],'task':task}
                with self.assertRaises(gate.Reject): self.derive()

    def setUp_records(self):
        for label,name in (('test-pr','test_pr_task'),('canary','canary_task'),('preflight','preflight_task')):
            self.records['synthetic:'+label]={'status':'published','request_id':'synthetic-'+label,'task':self.f.bundle[name]}

    def test_a_stale_canary_or_preflight_is_refused(self):
        for name,age in (('canary_evidence',dt.timedelta(seconds=gate.CANARY_EVIDENCE_MAX_AGE+60)),
                         ('preflight_evidence',dt.timedelta(seconds=gate.VERIFY_EVIDENCE_MAX_AGE+60))):
            with self.subTest(evidence=name):
                self.f=Fixture(); self.setUp_records()
                self.f.bundle[name]['completed_at']=bridge.iso(self.f.at-age); self.f.seal()
                self.setUp_records()
                with self.assertRaises(gate.Reject) as caught: self.derive()
                self.assertIn('stale',str(caught.exception))

    def test_the_newest_canary_decides_even_when_it_failed(self):
        """A refused canary is a finding about the candidate, not an inconvenience."""
        self.f=Fixture(); self.setUp_records()
        failed=dict(self.records['synthetic:canary']['task'],
                    task_id='go-boss-request-canary-newer',issued_at=bridge.iso(self.f.at-dt.timedelta(seconds=20)),
                    parameters=dict(self.records['synthetic:canary']['task']['parameters']))
        self.records['synthetic:canary-failed']={'status':'published','request_id':'synthetic-canary-failed','task':failed}
        original=self.f.read_evidence
        def evidence(task):
            if task['task_id']==failed['task_id']:
                return {**self.f.bundle['canary_evidence'],'task_id':failed['task_id'],
                        'nonce':failed['nonce'],'status':'REJECTED','executor_result':'CANARY_REJECTED'}
            return original(task)
        with self.assertRaises(gate.Reject) as caught: self.derive(read_evidence=evidence)
        self.assertIn('CANARY_REJECTED',str(caught.exception))

    def test_a_preflight_that_did_not_verify_is_refused(self):
        self.f=Fixture(); self.setUp_records()
        self.f.bundle['preflight_evidence']['status']='REJECTED'
        self.f.bundle['preflight_evidence']['executor_result']='VERIFY_REJECTED'
        self.f.seal(); self.setUp_records()
        with self.assertRaises(gate.Reject) as caught: self.derive()
        self.assertIn('VERIFY_REJECTED',str(caught.exception))

    def test_a_test_pr_the_ledger_does_not_hold_is_refused(self):
        self.records.pop('synthetic:test-pr')
        with self.assertRaises(gate.Reject) as caught: self.derive()
        self.assertEqual(str(caught.exception),'test_pr_task_not_in_ledger')

    def test_an_unadmitted_candidate_is_refused(self):
        for edit,reason in (({'schema':'something-else'},'candidate_pointer_schema'),
                            ({'release_candidate_v1':None},'release_candidate_missing')):
            with self.subTest(edit=edit):
                pointer={**self.f.admission_pointer(),**edit}
                with self.assertRaises(gate.Reject) as caught: self.derive(admission=pointer)
                self.assertEqual(str(caught.exception),reason)

    def test_a_candidate_that_disagrees_with_the_live_host_is_refused(self):
        """The admission record and the root-owned baseline must name the same live image."""
        baseline=dict(self.f.verify_baseline(),image_id='sha256:'+'9'*64)
        with self.assertRaises(gate.Reject) as caught: self.derive(verify_baseline=baseline)
        self.assertEqual(str(caught.exception),'candidate_and_live_current_disagree')

    def test_a_candidate_that_needs_a_migration_is_refused_not_ignored(self):
        """#103 scopes controlled forward migration; this contract does not carry it yet,
        so a candidate that needs one is refused up front rather than deployed with a
        schema it does not match."""
        pointer=self.f.admission_pointer()
        pointer['release_candidate_v1']['migration_required']=True
        with self.assertRaises(gate.Reject) as caught: self.derive(admission=pointer)
        self.assertEqual(str(caught.exception),'migration_required_not_supported')
        self.assertFalse(self.f.bundle['plan']['migration'])

    def test_the_bridge_derives_and_registers_the_plan_by_itself(self):
        """End to end through the Bridge's own derivation path.

        Only the three readers are injected and the plan store is redirected; nothing
        hands the Bridge a plan, and no operator file is consulted.
        """
        with patch.object(gate,'STORE',self.store),\
             patch.object(bridge,'read_admission',side_effect=self.f.admission_pointer),\
             patch.object(bridge,'read_evidence',side_effect=self.f.read_evidence),\
             patch.object(bridge,'load_baseline',side_effect=self.f.verify_baseline):
            context=bridge.derive_and_register_deployment(self.f.request(),
                        {'created_at':bridge.iso(self.f.at-dt.timedelta(seconds=10))},
                        self.f.approval_identity,self.records)
        self.assertTrue((self.store/(context['plan_id']+'.json')).is_file())
        self.assertEqual(context['parameters']['candidate_package_sha256'],self.f.package)
        self.assertEqual(context['parameters']['expected_current_image_id'],self.f.current)
        self.assertEqual(context['approval_identity'],self.f.approval_identity)
        self.assertEqual(context['request_sha256'],self.f.request_sha256)


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


class RemoteReadTests(unittest.TestCase):
    """How the Bridge reads one file out of a read-only remote.

    Two facts about the real remotes decided this code and neither is visible from the
    Bridge's own arguments, so both are pinned here.  First, the remotes do not agree on
    a branch name, and one of them carries no `main` at all -- its publication branch is
    whatever `git clone` checks out for the agent that writes it, which that agent's
    contract leaves untouched.  Second, one of them carries more than a gigabyte of
    history, which a shallow fetch without a blob filter cannot traverse inside a poll
    tick.  Everything below runs on the remote's reply and the fetch's argv, so it needs
    no network and no repository.
    """

    def reply(self, branch="permission-test", symref=True):
        lines = []
        if symref: lines.append("ref: refs/heads/%s\tHEAD" % branch)
        lines.append("%s\tHEAD" % ("c" * 40))
        return "\n".join(lines) + "\n"

    def read(self, reply, show_rc=0):
        """Run the real reader against a synthetic remote. Returns (calls, outcome)."""
        calls = []

        class Done:
            def __init__(self, stdout, returncode=0):
                self.stdout = stdout
                self.returncode = returncode

        def fake_git(env, *argv, cwd=None):
            calls.append(list(argv))
            return Done(reply if argv and argv[0] == "ls-remote" else "")

        def fake_run(argv, **kw):
            calls.append(list(argv))
            return Done(b'{"synthetic":true}' if not show_rc else b"", show_rc)

        try:
            with patch.object(bridge, "git", side_effect=fake_git), \
                 patch.object(bridge.subprocess, "run", side_effect=fake_run):
                return calls, bridge.read_repo_file("git@example.invalid:r.git", "/dev/null", "evidence/x.json")
        except gate.Reject as exc:
            return calls, str(exc)

    def fetches(self, calls):
        return [c for c in calls if "fetch" in c]

    def test_the_branch_is_the_one_the_remote_declares(self):
        """One reader, two remotes, and the name comes from the remote each time.

        The GO repository and the evidence repository disagree about the branch, and the
        reader is the same function for both.  A name compiled into the reader could only
        ever suit one of them.
        """
        for branch in ("main", "permission-test"):
            with self.subTest(branch=branch):
                calls, outcome = self.read(self.reply(branch))
                self.assertEqual(outcome, b'{"synthetic":true}')
                fetch = self.fetches(calls)
                self.assertEqual(len(fetch), 1)
                self.assertEqual(fetch[0][-1], branch)
                self.assertNotIn(branch, fetch[0][:-1],
                                 "the branch must be the fetch target, never an earlier argument")
                self.assertEqual(fetch[0][-2], "origin")

    def test_the_fetch_is_filtered_and_shallow(self):
        """What makes a repository of that size readable inside a poll tick.

        Without `--filter=blob:none` the transfer is the whole of the shallow history; the
        one blob this function wants is then fetched on demand by the `show`.
        """
        calls, _ = self.read(self.reply())
        argv = self.fetches(calls)[0]
        self.assertIn("--filter=blob:none", argv)
        self.assertEqual(argv[argv.index("--depth") + 1], "1")
        self.assertEqual(argv[argv.index("--filter=blob:none") + 1], "origin",
                         "the filter must be a fetch option, not the ref")

    def test_the_remote_is_asked_which_branch_it_publishes(self):
        calls, _ = self.read(self.reply())
        query = [c for c in calls if c and c[0] == "ls-remote"]
        self.assertEqual(len(query), 1)
        self.assertIn("--symref", query[0])
        self.assertEqual(query[0][-1], "HEAD")

    def test_a_remote_that_declares_no_default_branch_is_refused(self):
        """Fail closed, and before the fetch: an unnamed branch is not a reason to guess.

        A reply carrying only the object id -- what a remote that advertises no symbolic
        HEAD returns -- leaves nothing to fetch, so the refusal happens with no fetch
        attempted and the temporary workspace still cleaned up.
        """
        calls, outcome = self.read(self.reply(symref=False))
        self.assertEqual(outcome, "readable_file_unavailable")
        self.assertEqual(self.fetches(calls), [])
        removals = [c for c in calls if "/usr/bin/rm" in c]
        self.assertEqual(len(removals), 1)
        self.assertEqual(removals[0][1], "-rf")

    def test_a_branch_name_that_is_really_an_option_is_refused(self):
        """The name reaches git as an argument, so it is validated first.

        A branch called `--upload-pack=...` would otherwise be handed to `git fetch` as an
        option rather than as a ref.  No remote publishes such a branch, which is exactly
        why the refusal has to be structural rather than a matter of trust.
        """
        for hostile in ("--upload-pack=/tmp/x", "-c", "main --exec=sh", "", "a" * 200):
            with self.subTest(branch=hostile):
                calls, outcome = self.read(self.reply(hostile))
                self.assertEqual(outcome, "readable_file_unavailable")
                self.assertEqual(self.fetches(calls), [])

    def test_a_file_that_cannot_be_shown_is_a_refusal_not_a_crash(self):
        """An escaping error here would end the tick and stop every other action too."""
        calls, outcome = self.read(self.reply(), show_rc=128)
        self.assertEqual(outcome, "readable_file_unavailable")
        removals = [c for c in calls if "/usr/bin/rm" in c]
        self.assertEqual(len(removals), 1)
