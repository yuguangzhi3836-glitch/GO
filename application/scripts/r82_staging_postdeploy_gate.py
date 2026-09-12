#!/usr/bin/env python3
from pathlib import Path
import ast, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'scripts'/'r82_staging_postdeploy_controller.py'; text=p.read_text(); ast.parse(text)
checks={
'five_unified_checks': all(x in text for x in ['container_health','migration_runtime','https_three_surface','browser_console','rc17_checkpoint']),
'health_required': 'API_CONTAINER_NOT_HEALTHY' in text and 'CONTAINER_NOT_RUNNING' in text,
'rds_runtime_required': 'r82_rds_lineage_probe.py' in text and '0112_ti_p0_20260829' in text and 'EXPECTED_REVISIONS=112' in text,
'https_three_surfaces': 'deploy/https_verify.sh' in text,
'browser_console_required': 'deploy/browser_verify.sh' in text,
'rc17_chain_required': 'RC17_EVIDENCE_CHAIN_INVALID' in text,
'no_auto_advance': "'does_not_advance_rc17':True" in text,
'not_live': "'production_live':False" in text,
'no_new_migration': not any('rc17_3' in x.name.lower() or 'rc173' in x.name.lower() for x in (ROOT/'alembic/versions').glob('*.py')),
'posix_wrapper': subprocess.run(['sh','-n',str(ROOT/'scripts'/'r82_staging_postdeploy.sh')]).returncode==0,
'no_pipefail': 'pipefail' not in (ROOT/'scripts'/'r82_staging_postdeploy.sh').read_text(),
}
failed=[k for k,v in checks.items() if not v]
print('R8.2_RC17_3_POSTDEPLOY_ACCEPTANCE_GATE:', 'PASS' if not failed else 'FAIL')
for k,v in checks.items(): print(f'{k}={str(v).lower()}')
if failed: print('FAILED='+','.join(failed)); sys.exit(1)
