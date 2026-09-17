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
            'artifact_digest': self.candidate, 'built_image_id': self.candidate,
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
        for label, name in (('test-pr', 'test_pr_task'), ('canary', 'canary_task'),
                            ('preflight', 'preflight_task')):
            records['synthetic:' + label] = {'status': 'published', 'request_id': 'synthetic-' + label,
                                             'task': self.bundle[name]}
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
            self.assertEqual(set(task['parameters']),{'release_id','candidate_image_id','candidate_package_sha256','expected_current_image_id','canary_evidence_id','approval_id','migration'})
            self.assertIs(task['parameters']['migration'],False)
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
               ('artifact_digest', 'sha256:'+'c'*64),  # a different artifact
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
        # derived from, so what has to be exactly one is the DEPLOY record.
        deploys=[r for r in records.values() if (r.get('task') or {}).get('action_id')==gate.ACTION]
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

    def test_a_candidate_that_needs_a_migration_requires_source_bound_admission(self):
        """A boolean cannot authorise a migration; the full admission can."""
        pointer=self.f.admission_pointer()
        pointer['release_candidate_v1']['migration_required']=True
        with self.assertRaises(gate.Reject) as caught: self.derive(admission=pointer)
        self.assertEqual(str(caught.exception),'candidate_admission_incomplete')
        self.assertFalse(self.f.bundle['plan']['migration'])
        block=pointer['release_candidate_v1']
        block['migration_head']='0137_hosted_unknown_episode'
        block['migration_admission']={'schema':'go.forward-migration-admission.v1',
            'source_commit':self.f.source,'application_git_tree':self.f.tree,
            'source_fingerprint_sha256':self.f.fingerprint,
            'prestate_revision':'0133_flight_change_plan','target_revision':'0137_hosted_unknown_episode',
            'lineage_sha256':'1'*64,'forward_only':True,'arbitrary_sql':False,
            'rehearsal_evidence_sha256':'2'*64,'rehearsal_postgres_version':'18.4'}
        plan_id,bundle=self.derive(admission=pointer)
        self.assertEqual(bundle['plan']['migration'],block['migration_admission'])

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
