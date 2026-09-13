"""Installed, hash-pinned site inputs. No Task can supply paths or Docker options."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

SERVICES = ('api', 'recovery-worker', 'outbox-worker', 'mobile-push-receipt-worker',
            'reconciliation-worker', 'mobile-push-worker', 'mobile-engagement-worker', 'judgment-worker')
IMAGE = re.compile(r'sha256:[0-9a-f]{64}')
SHA = re.compile(r'[0-9a-f]{64}')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')
HEAD = '0132_rail_runtime_field_widths'


def read_pinned(path, expected, *, owner=0):
    if not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise ValueError('SITE_BINDING_NOT_SEALED')
    p = Path(path)
    for parent in (p, *p.parents):
        s = parent.lstat()
        if stat.S_ISLNK(s.st_mode) or s.st_uid != owner or s.st_mode & 0o022:
            raise ValueError('SITE_BINDING_PERMISSIONS')
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError('SITE_BINDING_FILE')
        raw = f.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('SITE_BINDING_INTEGRITY')
    return validate(json.loads(raw))


def validate(value):
    required = {'schema_version', 'environment', 'project', 'candidate', 'previous',
                'network', 'media_volume', 'recovery_plan'}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('SITE_BINDING_SCHEMA')
    if (value['schema_version'], value['environment'], value['project']) != ('1', 'HK-STAGING-01', 'go-822-staging'):
        raise ValueError('SITE_BINDING_ENVIRONMENT')
    for key in ('network', 'media_volume'):
        if not isinstance(value[key], str) or not NAME.fullmatch(value[key]):
            raise ValueError('SITE_BINDING_RESOURCE')
    keys = {'image_id', 'repo_digest', 'compose_path', 'compose_sha256', 'env_path',
            'env_sha256', 'layout', 'expected_head', 'database_head'}
    for name in ('candidate', 'previous'):
        profile = value[name]
        if not isinstance(profile, dict) or set(profile) != keys:
            raise ValueError('SITE_PROFILE_SCHEMA')
        if not IMAGE.fullmatch(profile['image_id']):
            raise ValueError('SITE_PROFILE_IMAGE')
        if profile['layout'] not in ('depth40', 'r315'):
            raise ValueError('SITE_PROFILE_LAYOUT')
        if profile['expected_head'] not in (HEAD, '0114_ext_truth_incident_hard'):
            raise ValueError('SITE_PROFILE_HEAD')
        if profile['database_head'] not in (HEAD, '0114_ext_truth_incident_hard'):
            raise ValueError('SITE_DATABASE_HEAD')
        if profile['layout'] == 'depth40' and (profile['expected_head'] != HEAD or profile['database_head'] != HEAD):
            raise ValueError('DEPTH40_HEAD_REQUIRED')
        for field in ('compose_path', 'env_path'):
            path = Path(profile[field])
            if not path.is_absolute() or '..' in path.parts or any(c in str(path) for c in '\n\r\0'):
                raise ValueError('SITE_PROFILE_PATH')
        if any(not SHA.fullmatch(profile[k]) for k in ('compose_sha256', 'env_sha256')):
            raise ValueError('SITE_PROFILE_SHA')
        digest = profile['repo_digest']
        # Format only. Actual config-ID mapping is checked with Docker inspect.
        if digest is not None and not re.fullmatch(r'[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}', digest):
            raise ValueError('SITE_PROFILE_DIGEST')
    if value['candidate']['layout'] != 'depth40':
        raise ValueError('CANDIDATE_LAYOUT_REQUIRED')
    if value['candidate']['image_id'] == value['previous']['image_id']:
        raise ValueError('DISTINCT_UPGRADE_IMAGES_REQUIRED')
    plan = value['recovery_plan']
    if not isinstance(plan, dict) or set(plan) != {'path', 'sha256'}:
        raise ValueError('RECOVERY_PLAN_BINDING')
    if not Path(plan['path']).is_absolute() or '..' in Path(plan['path']).parts or not SHA.fullmatch(plan['sha256']):
        raise ValueError('RECOVERY_PLAN_BINDING')
    return value


def apply(module, kind, binding):
    b = validate(binding)
    c, p = b['candidate'], b['previous']
    if kind == 'collector':
        module.PROFILES = {x['image_id']: dict(x) for x in (c, p)}
        module.COMPOSE_ENVIRONMENTS = {
            x['env_path']: {'GO_RUNTIME_ENV_FILE': x['env_path'],
                            'GO_DEPTH40_IMAGE_ID': x['image_id'],
                            'GO_VERIFIED_RUNTIME_NETWORK': b['network'],
                            'GO_VERIFIED_MEDIA_VOLUME': b['media_volume']}
            for x in (p, c)
        }
    elif kind == 'deploy':
        module.COMPOSE, module.COMPOSE_SHA = c['compose_path'], c['compose_sha256']
        module.ENV, module.ENV_SHA = c['env_path'], c['env_sha256']
        module.SITE = b
    elif kind == 'canary':
        module.COMPOSE, module.COMPOSE_SHA = p['compose_path'], p['compose_sha256']
        module.ENV, module.ENV_SHA = p['env_path'], p['env_sha256']
        module.HEAD = HEAD
        module.WORKDIR = '/opt/go/source'
        module.PYTHON = '/opt/go/python/bin/python3.13'
        module.ALEMBIC = '/opt/go/python/bin/alembic'
        module.CANDIDATE = c['image_id']
    elif kind == 'rollback':
        module.COMPOSE, module.ENV_FILE = c['compose_path'], c['env_path']
        module.SITE = b
    else:
        raise ValueError('SITE_BINDING_MODULE')
