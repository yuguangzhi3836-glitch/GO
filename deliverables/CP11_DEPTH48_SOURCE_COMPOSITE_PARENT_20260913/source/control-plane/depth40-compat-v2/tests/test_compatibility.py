"""Regression tests: real Python/crypto/filesystem, simulated Docker responses only."""
import base64
from copy import deepcopy
import hashlib
import importlib.util
import json
import io
import contextlib
import runpy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parents[1]
RT = ROOT / 'executor/go-hk-deployctl-runtime'


def load(name, path=None):
    spec = importlib.util.spec_from_file_location(name, path or RT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


d = load('deploy_runtime'); c = load('collector_runtime'); r = load('rollback_runtime')
b = load('site_binding'); g = load('recovery_gate'); can = load('canary_runtime')
pre = load('preflight', ROOT / 'image/preflight.py')
OLD = 'sha256:' + '1' * 64
NEW = 'sha256:' + '2' * 64
DIGEST = 'registry.example.test:5000/go@sha256:' + '3' * 64
OLD_DIGEST = 'registry.example.test:5000/go@sha256:' + '4' * 64
HEAD = b.HEAD


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, separators=(',', ':')))
    return path


def sign(obj, key, hexadecimal=False):
    result = deepcopy(obj)
    sig = key.sign(r.canonical(result))
    result['signature'] = sig.hex() if hexadecimal else base64.b64encode(sig).decode()
    return result


class DockerModel:
    """Command-level model; never calls subprocess, Docker, network or a database."""
    def __init__(self, site):
        self.site = site
        self.calls = []
        self.rows = {}
        self.images = {OLD: OLD, NEW: NEW, DIGEST: NEW, OLD_DIGEST: OLD}
        self.bad_recreate = False
        self.fail_recreate = False
        self.config = {'services': {}, 'networks': {'runtime': {'external': True, 'name': site['network']}},
                       'volumes': {'media-state': {'external': True, 'name': site['media_volume']}}}
        for name in (*d.SERVICES, 'redis', 'caddy'):
            image = OLD if name in d.SERVICES else 'sha256:' + '5' * 64
            self.rows[name] = {'Id': name + '-before', 'Name': name,
                'Image': image, 'RestartCount': 0,
                'Config': {'Labels': {'com.docker.compose.project': d.PROJECT, 'com.docker.compose.service': name}},
                'State': {'Running': True, 'Status': 'running', 'Health': {'Status': 'healthy'},
                          'StartedAt': 'start', 'Restarting': False, 'OOMKilled': False},
                'NetworkSettings': {'Networks': {'test-network': {}}}}
            if name in d.SERVICES:
                self.config['services'][name] = {'command': [name], 'image': NEW, 'user': '10001:10001',
                    'pull_policy': 'never', 'restart': 'no', 'read_only': True, 'cap_drop': ['ALL'], 'volumes': [{'type': 'volume', 'source': 'media-state', 'target': '/state'}]}

    def run(self, argv, *unused):
        self.calls.append(list(argv))
        args = argv[1:]
        out = ''
        code = 0
        if args[0] == 'ps':
            filters = [x.split('service=')[1] for x in args if 'service=' in x]
            rows = [self.rows[filters[0]]] if filters else list(self.rows.values())
            out = '\n'.join(x['Id'] for x in rows)
        elif args[0] == 'inspect':
            rows = [next(x for x in self.rows.values() if x['Id'] == cid) for cid in args[1:]]
            out = json.dumps(rows)
        elif args[:2] == ['image', 'inspect']:
            image = args[2]
            if '.RepoDigests' in args[-1]:
                out = DIGEST if image == NEW else OLD_DIGEST if image == OLD else ''
            else:
                out = self.images.get(image, image)
        elif args[0] == 'compose':
            if 'config' in args:
                out = json.dumps(self.config)
            else:
                fs = [args[i+1] for i, a in enumerate(args) if a == '-f']
                override = Path(fs[-1]).read_text()
                if override.lstrip().startswith('{'):
                    images = {k: v['image'] for k, v in json.loads(override)['services'].items()}
                else:
                    import yaml
                    images = {k: v['image'] for k, v in yaml.safe_load(override)['services'].items()}
                for name, image in images.items():
                    self.rows[name]['Id'] = name + '-after-' + image[-1]
                    if not self.bad_recreate:
                        self.rows[name]['Image'] = image
                if self.fail_recreate:
                    self.rows['api']['State']['Running'] = False
                    code = 1
        elif args[0] == 'exec':
            profile = self.site['candidate'] if self.rows['api']['Image'] == NEW else self.site['previous']
            out = 'Rev: ' + profile['database_head'] + '\n' if args[-2:] == ['current', '-v'] else profile['expected_head'] + ' (head)\n'
        else:
            raise AssertionError('unexpected model command: ' + repr(argv))
        return c.ProcessResult(tuple(argv), code, out, '')


class Compatibility(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        profiles = []
        for name, image, digest, layout, head in [('candidate', NEW, DIGEST, 'depth40', HEAD), ('previous', OLD, OLD_DIGEST, 'r315', '0114_ext_truth_incident_hard')]:
            compose = self.root / (name + '.yml'); compose.write_text('services: {}\n')
            env = self.root / (name + '.env'); env.write_text('APP_ENV=staging\n')
            profiles.append({'image_id': image, 'repo_digest': digest, 'layout': layout,
                'compose_path': str(compose), 'compose_sha256': sha(compose), 'env_path': str(env), 'env_sha256': sha(env),
                'expected_head': head, 'database_head': HEAD})
        self.site = {'schema_version': '1', 'environment': 'HK-STAGING-01', 'project': d.PROJECT,
            'candidate': profiles[0], 'previous': profiles[1], 'network': 'test-network', 'media_volume': 'test-media',
            'recovery_plan': {'path': str(self.root/'recovery.json'), 'sha256': 'a'*64}}
        for module, kind in [(d,'deploy'),(c,'collector'),(r,'rollback'),(can,'canary')]:
            b.apply(module, kind, self.site)
        # Recovery signature is exercised separately; no HK plan is synthesized.
        self.gate = patch.object(d, 'RECOVERY_GATE', SimpleNamespace(verify_plan=lambda s: None))
        self.gate.start(); self.addCleanup(self.gate.stop)
        d.RECORD_DIR = str(self.root/'records'); r.TEMP_DIR = str(self.root/'tmp')
        self.docker = DockerModel(self.site)
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.root/'key.pub'
        self.pub.write_bytes(self.key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH))
        self.task = {'schema_version':'1','action_id':'HK_STAGING_DEPLOY','environment':'HK-STAGING-01',
            'authority':'GO-COMMAND-CENTER','task_id':'test-deploy','nonce':'test-nonce','issued_at':'2026-09-12T00:00:00Z',
            'parameters':{'release_id':'test-release'}}
        self.binding = {'task_id':'test-deploy','nonce':'test-nonce','authority':'GO-COMMAND-CENTER',
                        'canonical_sha256':hashlib.sha256(r.canonical(self.task)).hexdigest()}

    def deploy(self):
        # The override filesystem location is isolated, while exercising its real writer.
        original = d._override
        def temporary_override(image):
            path = self.root/'deploy-override.json'
            write(path, {'services':{s:{'image':image} for s in d.SERVICES}})
            return str(path)
        with patch.object(d, '_override', temporary_override):
            return d.run_deploy('test-release', NEW, DIGEST, OLD, self.binding, self.docker, c, lambda _:None)

    def handoff(self, record):
        evidence = {'schema_version':'1','task_id':self.task['task_id'],'nonce':self.task['nonce'],
                    'action_id':'HK_STAGING_DEPLOY','environment':'HK-STAGING-01','status':'SUCCESS','executor_result':'DEPLOY_OK',
                    'release_id':'test-release','deploy_record_id':record['deploy_record_id'],'deploy_record_sha256':record['deploy_record_sha256']}
        task = sign(self.task, self.key, True); evidence = sign(evidence, self.key)
        self.handoff_dir = self.root/'handoff'; self.handoff_dir.mkdir()
        handoff = {'schema_version':'1','rollback_task_id':'test-rollback','source_deploy_task_id':self.task['task_id'],
                   'source_task':task,'source_evidence':evidence,'deploy_record_id':record['deploy_record_id'],
                   'deploy_record_sha256':record['deploy_record_sha256'],'history':[{'task':task,'evidence':evidence}]}
        write(self.handoff_dir/'test-rollback.json', handoff)
        return handoff

    def rollback(self):
        return r.run_rollback('rollback-release','test-deploy',{'task_id':'test-rollback','nonce':'rollback-nonce',
            'authority':'GO-COMMAND-CENTER','canonical_sha256':'b'*64},self.docker,c,
            handoff_dir=str(self.handoff_dir),deploy_dir=d.RECORD_DIR,rollback_dir=str(self.root/'rollback'),
            task_key=str(self.pub),evidence_key=str(self.pub),sleeper=lambda _:None)

    def test_distinct_config_and_registry_digests_are_accepted(self):
        result = self.deploy()
        self.assertEqual(result['post_deploy_verify'], 'PASS')
        self.assertTrue(all(self.docker.rows[s]['Image']==NEW for s in d.SERVICES))
        record = json.loads(Path(result['record_path']).read_text())
        self.assertEqual(record['previous_runtime'], self.site['previous'])

    def test_digest_resolving_to_wrong_config_rejected_before_mutation(self):
        self.docker.images[DIGEST]=OLD
        with self.assertRaisesRegex(ValueError,'REPO_DIGEST_BINDING'): self.deploy()
        self.assertFalse(any('up' in a for a in self.docker.calls))

    def test_old_worker_command_rejected(self):
        self.docker.config['services']['outbox-worker']['command']=['python','-m','old_worker']
        with self.assertRaisesRegex(ValueError,'COMPOSE_ROLE_IMAGE'): self.deploy()

    def test_old_pythonpath_rejected(self):
        self.docker.config['services']['api']['environment']={'PYTHONPATH':'/app/src'}
        with self.assertRaisesRegex(ValueError,'PYTHONPATH'): self.deploy()

    def test_extra_service_rejected(self):
        self.docker.config['services']['redis']={}
        with self.assertRaisesRegex(ValueError,'COMPOSE_SCOPE'): self.deploy()

    def test_missing_persistent_media_rejected(self):
        self.docker.config['volumes']['media-state']['external']=False
        with self.assertRaisesRegex(ValueError,'COMPOSE_MEDIA'): self.deploy()

    def test_profile_drift_rejected(self):
        Path(self.site['previous']['env_path']).write_text('changed')
        with self.assertRaisesRegex(ValueError,'PROFILE_DRIFT'): self.deploy()

    def test_unplanned_schema_transition_rejected(self):
        self.site['previous']['database_head']='0114_ext_truth_incident_hard'
        b.apply(c,'collector',self.site)
        with self.assertRaisesRegex(ValueError,'SCHEMA_TRANSITION'): self.deploy()
        self.assertFalse(any('up' in a for a in self.docker.calls))

    def test_collector_uses_bound_candidate_paths_and_head(self):
        self.deploy()
        executions = [a for a in self.docker.calls if a[1]=='exec']
        self.assertTrue(any('/opt/go/python/bin/alembic' in a and '/opt/go/source' in a for a in executions))
        self.assertTrue(all('PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=15000' in a for a in executions))

    def test_mutation_failure_retains_previous_state_and_failure_record(self):
        self.docker.fail_recreate=True
        with self.assertRaises(d.DeployFailure) as ctx: self.deploy()
        self.assertTrue(Path(ctx.exception.record['record_path']).is_file())
        self.assertEqual(len(list(Path(d.RECORD_DIR).glob('*-failure.json'))),1)
        self.assertEqual(sum('up' in a for a in self.docker.calls),1)

    def test_rollback_drives_recorded_images_and_checks_identity(self):
        self.handoff(self.deploy())
        result=self.rollback()
        self.assertEqual(result['postcheck'],'PASS')
        self.assertTrue(all(self.docker.rows[s]['Image']==OLD for s in d.SERVICES))
        self.assertTrue(all('-f' in a and self.site['previous']['compose_path'] in a for a in self.docker.calls if 'up' in a and self.site['previous']['env_path'] in a))

    def test_wrong_image_cannot_return_rollback_pass(self):
        self.handoff(self.deploy()); self.docker.bad_recreate=True
        with self.assertRaisesRegex(ValueError,'readiness timeout'): self.rollback()

    def test_unhealthy_api_cannot_return_rollback_pass(self):
        self.handoff(self.deploy()); self.docker.rows['api']['State']['Health']['Status']='unhealthy'
        with self.assertRaisesRegex(ValueError,'readiness timeout'): self.rollback()

    def test_consumed_source_cannot_be_replayed(self):
        self.handoff(self.deploy()); self.rollback()
        with self.assertRaisesRegex(ValueError,'source consumed'): self.rollback()

    def test_modified_source_signature_rejected(self):
        handoff=self.handoff(self.deploy()); handoff['source_task']['nonce']='tampered'
        write(self.handoff_dir/'test-rollback.json',handoff)
        with self.assertRaisesRegex(ValueError,'signature'): self.rollback()

    def test_failed_deploy_not_promoted_to_successful_rollback_source(self):
        handoff=self.handoff(self.deploy()); evidence=handoff['source_evidence']; evidence['status']='REJECTED'
        handoff['source_evidence']=sign(evidence,self.key)
        write(self.handoff_dir/'test-rollback.json',handoff)
        with self.assertRaisesRegex(ValueError,'source evidence binding'): self.rollback()

    def test_worker_restart_during_observation_rejected(self):
        self.deploy()
        def restart(_): self.docker.rows['outbox-worker']['RestartCount']+=1
        with self.assertRaisesRegex(ValueError,'drift'):
            c._collect_verify(self.docker,NEW,NEW,c.inputs_for(NEW),restart)

    def test_unbound_profile_rejected(self):
        with self.assertRaisesRegex(ValueError,'unbound image'): c.inputs_for('sha256:'+'f'*64)

    def test_production_site_binding_rejected(self):
        self.site['environment']='PRODUCTION'
        with self.assertRaisesRegex(ValueError,'ENVIRONMENT'): b.validate(self.site)

    def test_unsealed_site_binding_rejected(self):
        with self.assertRaisesRegex(ValueError,'NOT_SEALED'): b.read_pinned(self.root/'missing',None)

    def test_entrypoint_rejects_unsealed_site_without_docker_call(self):
        entry=runpy.run_path(str(ROOT/'executor/go-hk-deployctl'))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code=entry['main'](['verify','--release-id','test','--candidate-image-id',NEW,'--expected-current-image-id',NEW],runner=self.docker)
        self.assertEqual(code,2)
        self.assertEqual(json.loads(output.getvalue())['status'],'REJECTED')
        self.assertEqual(self.docker.calls,[])

    def test_pulling_policy_rejected(self):
        self.docker.config['services']['api']['pull_policy']='always'
        with self.assertRaisesRegex(ValueError,'PULL_RESTART_POLICY'):self.deploy()

    def test_replaced_protected_container_rejected_before_rollback(self):
        self.handoff(self.deploy());self.docker.rows['redis']['Id']='redis-replaced'
        with self.assertRaisesRegex(ValueError,'protected drift'):self.rollback()

    def test_previous_runtime_record_drift_rejected(self):
        self.handoff(self.deploy())
        Path(self.site['previous']['compose_path']).write_text('unexpected changed config')
        with self.assertRaisesRegex(ValueError,'previous profile drift'):self.rollback()

    def make_plan(self):
        evidence=write(self.root/'restore-evidence.json',{'scope':'TEST_FIXTURE_ONLY'})
        procedure=write(self.root/'procedure.json',{'scope':'TEST_FIXTURE_ONLY'})
        plan={'purpose':'DEPLOY_FAILURE_RECOVERY_PREPARATION','environment':'HK-STAGING-01','authority':'GO-COMMAND-CENTER',
              'status':'APPROVED','candidate':self.site['candidate'],'previous':self.site['previous'],'valid_until':200,
              'automatic_recovery':False,'fresh_recovery_authorization_required':True,
              'failure_modes':['partial_recreate','readiness_failure','postcheck_failure'],
              'backup_restore_evidence':{'path':str(evidence),'sha256':sha(evidence)},
              'stop_restore_procedure':{'path':str(procedure),'sha256':sha(procedure)}}
        path=write(Path(self.site['recovery_plan']['path']),sign(plan,self.key));self.site['recovery_plan']['sha256']=sha(path)
        return path

    def test_recovery_preparation_signature_and_binding(self):
        self.make_plan()
        self.assertFalse(g.verify_plan(self.site,key=str(self.pub),now=100)['automatic_recovery'])

    def test_expired_recovery_plan_rejected(self):
        self.make_plan()
        with self.assertRaisesRegex(ValueError,'EXPIRED'): g.verify_plan(self.site,key=str(self.pub),now=201)

    def test_tampered_recovery_signature_rejected(self):
        path=self.make_plan(); p=json.loads(path.read_text());p['valid_until']=999
        write(path,p);self.site['recovery_plan']['sha256']=sha(path)
        with self.assertRaisesRegex(ValueError,'SIGNATURE'):g.verify_plan(self.site,key=str(self.pub),now=100)

    def test_missing_restore_evidence_rejected(self):
        self.make_plan();(self.root/'restore-evidence.json').unlink()
        with self.assertRaisesRegex(ValueError,'EVIDENCE_MISSING'):g.verify_plan(self.site,key=str(self.pub),now=100)


class CriticalColumns(unittest.TestCase):
    def rows(self):
        return [('rail_order_runtime','status',64,'character varying','varchar'),
                ('rail_order_runtime','booking_reference',128,'character varying','varchar')]

    def test_exact_widths(self): pre.critical_column_gate(self.rows())
    def test_unbounded_text(self):
        pre.critical_column_gate([(t,n,None,'text','text') for t,n,*_ in self.rows()])
    def test_non_character_null_width_rejected(self):
        rows=self.rows();rows[0]=('rail_order_runtime','status',None,'integer','int4')
        with self.assertRaisesRegex(pre.Hold,'TYPE_MISMATCH'):pre.critical_column_gate(rows)
    def test_narrow_varchar_rejected(self):
        rows=self.rows();rows[1]=('rail_order_runtime','booking_reference',24,'character varying','varchar')
        with self.assertRaisesRegex(pre.Hold,'WIDTH_MISMATCH'):pre.critical_column_gate(rows)
    def test_missing_column_rejected(self):
        with self.assertRaisesRegex(pre.Hold,'COLUMNS_MISSING'):pre.critical_column_gate(self.rows()[:1])
    def test_domain_or_unknown_type_rejected(self):
        rows=self.rows();rows[0]=('rail_order_runtime','status',None,'USER-DEFINED','unreviewed')
        with self.assertRaisesRegex(pre.Hold,'TYPE_MISMATCH'):pre.critical_column_gate(rows)


if __name__ == '__main__': unittest.main(verbosity=2)
