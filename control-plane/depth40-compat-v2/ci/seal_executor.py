"""Seal source bytes; does not bind a site, install, sign, or execute an operation."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    executable = ROOT / 'executor/go-hk-deployctl'
    text = executable.read_text()
    mapping = {'COLLECTOR': 'collector_runtime.py', 'CANARY': 'canary_runtime.py',
               'DEPLOY': 'deploy_runtime.py', 'ROLLBACK': 'rollback_runtime.py',
               'SITE': 'site_binding.py', 'RECOVERY': 'recovery_gate.py'}
    for name, filename in mapping.items():
        sha = hashlib.sha256((ROOT / 'executor/go-hk-deployctl-runtime' / filename).read_bytes()).hexdigest()
        pattern = rf'(?m)^_{name}_SHA256 = "[0-9a-f]+"$'
        replacement = f'_{name}_SHA256 = "{sha}"'
        if re.search(pattern, text):
            text = re.sub(pattern, replacement, text)
        else:
            text = text.replace('SITE_BINDING_SHA256 = None', replacement + '\nSITE_BINDING_SHA256 = None', 1)
    executable.write_text(text)
    files = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted((ROOT / 'executor').rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    (ROOT / 'EXECUTOR_MANIFEST.json').write_text(json.dumps({
        'version': '0.5.0-depth40-compat-candidate', 'files': files,
        'site_binding': 'UNBOUND', 'installed': False, 'deployment_authorized': False,
        'parent_archive_commit': '1d8bebac37fcc6f0360b17891aa49eb6e70b5f96'
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
