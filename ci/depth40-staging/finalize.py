"""Seal this build's actual outcomes. A failed schema/boot check is never upgraded to PASS."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ap=argparse.ArgumentParser()
ap.add_argument('--directory',type=Path,required=True)
ap.add_argument('--run-id',required=True)
ap.add_argument('--tooling-sha',required=True)
a=ap.parse_args(); root=a.directory; here=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
result=json.loads((root/'CI_RESULT.json').read_text()) if (root/'CI_RESULT.json').exists() else {'status':'NOT_RUN','checks':[]}
archive=root/'GO_DEPTH40_STAGING_IMAGE.tar.gz'
assert archive.is_file(), 'ACTUAL_IMAGE_REQUIRED'
image_size=int((root/'IMAGE_SIZE_BYTES.txt').read_text())
meta={'candidate':'CP11_DEPTH40_P03_PARENT_20260911',
      'candidate_build_commit':'c909af370d55ce7644140a191425a8a66dacec9a',
      'parent_artifact_id':10183252130,
      'parent_artifact_zip_sha256':'d0aa4b89ed0655271cf5ef7a12cce354dc8d84704cf57071f581f129458cbaf7',
      'parent_archive_sha256':'2909651f9b644ed56fd6ab833480c9da32b4c5b900df2e5afb192dba49ac2b00',
      'source_tree_sha256':'64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667',
      'source_files':1271,'source_modified':False,'packaging_commit':a.tooling_sha,'packaging_run':a.run_id,
      'platform':'linux/amd64','runtime_scope':'STAGING_EIGHT_SERVICE_POSTGRES_REVIEW',
      'image_config_id':(root/'IMAGE_ID.txt').read_text().strip(),
      'image_tag':(root/'IMAGE_TAG.txt').read_text().strip(),
      'registry_repo_digest':None, 'registry_status':'NOT_PUSHED_EXECUTOR_INTEGRATION_HOLD',
      'runtime_archive':archive.name,'runtime_archive_sha256':sha(archive),
      'runtime_archive_bytes':archive.stat().st_size,'image_uncompressed_bytes':image_size,
      'required_database_head':'0132_rail_runtime_field_widths','hk_migration_authorized':False,
      'offline_image_load':'PASS_CI','isolated_pg16_eight_service_gate':result['status'],
      'hk_database_compatibility':'HOLD_CURRENT_RDS_HEAD_AND_STRUCTURE',
      'hk_compose_binding':'HOLD_FRESH_RUNTIME_MAPPING',
      'hk_rollback_ready':'HOLD_LIVE_PREVIOUS_STATE_AND_APPROVED_EXECUTOR_MAPPING',
      'hk_execution':'NOT_RUN','three_end_browser_gate':'HOLD','six_vertical_e2e_gate':'HOLD',
      'physical_iphone_gate':'HOLD_EXTERNAL_DEVICE_RUNNER','final_production_release_gate':'HOLD',
      'deployment_authorized_by_this_package':False}
(root/'RUNTIME_MANIFEST.json').write_text(json.dumps(meta,indent=2)+'\n')
budget={'observed_image_bytes':image_size,'observed_archive_bytes':archive.stat().st_size,
    'disk_before_backup_budget_bytes':2*archive.stat().st_size+2*image_size+160*1024**2+2*1024**3,
    'backup_bytes':'UNKNOWN','full_disk_requirement':'UNKNOWN_UNTIL_BACKUP_BUDGET',
    'api_memory_cap_bytes':512*1024**2,'seven_workers_memory_cap_bytes':7*192*1024**2,
    'host_memory_reserve_bytes':768*1024**2,'capacity_gate':'HOLD_FRESH_HK_PREFLIGHT',
    'notes':'CI samples are not peak-load evidence. No image/data cleanup is authorized.'}
(root/'RESOURCE_BUDGET.json').write_text(json.dumps(budget,indent=2)+'\n')
for name in ('README.md','Dockerfile','compose.staging.review.yml','preflight.py','launch.py',
             'build.py','verify_delivery.py'):
    shutil.copy2(here/name,root/name)
parts=[]
with archive.open('rb') as stream:
    for i in range(1000):
        data=stream.read(20*1024*1024)
        if not data: break
        part=root/f'{archive.name}.part{i:03}'
        part.write_bytes(data)
        parts.append({'name':part.name,'size':len(data),'sha256':sha(part)})
(root/'RUNTIME_PARTS.json').write_text(json.dumps({'archive_name':archive.name,
    'archive_sha256':meta['runtime_archive_sha256'],'size':archive.stat().st_size,'parts':parts},indent=2)+'\n')
archive.unlink()
files={p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file()}
(root/'SHA256SUMS').write_text(''.join(f'{h}  {p}\n' for p,h in sorted(files.items())))
print(json.dumps(meta))
