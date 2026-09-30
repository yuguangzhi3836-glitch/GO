"""Closed isolated-validation profile. This validates a proposal, never authority."""
import json
from pathlib import Path

# Separate from the caller-supplied document; unknown additions fail closed too.
EXPECTED = {
    'schema_version': 1, 'topology_id': 'GO_C_RUNTIME_ISOLATED_SINGLETON',
    'version': 1, 'status': 'PROPOSED_HOLD', 'authorizes_any_action': False,
    'environment': 'ISOLATED_VALIDATION_ONLY',
    'services': [{'role': 'go-c1-c14-runtime', 'replicas': 1, 'adapter': 'noop', 'task_kinds': ['RUNTIME_PROBE']}],
    'persistence': {'engine': 'sqlite', 'local_disk_only': True, 'shared_filesystem': False, 'ha': False},
    'network': {'listeners': [], 'egress': []}, 'credentials': [],
    'business_topology_mutation': False,
    'protected_targets': ['HK-STAGING', 'Production', 'business_database', 'caddy', 'redis', 'media', 'HK_Agent', 'Executor', 'signing_keys', 'authority_ledger', 'SSH'],
    'activation_gate': 'TOPOLOGY_CHANGE_REQUIRED',
}

def validate_topology(document: dict) -> dict:
    # Canonical JSON comparison distinguishes false/0 and true/1.
    canonical = lambda x: json.dumps(x, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if canonical(document) != canonical(EXPECTED):
        raise ValueError('unsupported topology: isolated singleton profile required')
    return document

def load_topology(path: Path) -> dict:
    return validate_topology(json.loads(path.read_text()))
