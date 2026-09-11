import argparse
import hashlib
import json
from pathlib import Path
import shutil

ap = argparse.ArgumentParser()
ap.add_argument('--directory', type=Path, required=True)
ap.add_argument('--tooling', type=Path, required=True)
ap.add_argument('--run-id', required=True)
ap.add_argument('--tooling-sha', required=True)
a = ap.parse_args(); root = a.directory
image = root / 'GO_DEPTH40_ISOLATED_IMAGE.tar.gz'
image_sha = hashlib.sha256(image.read_bytes()).hexdigest()
image_size = int((root / 'IMAGE_SIZE_BYTES.txt').read_text())
binding = json.loads((root / 'LIVE_CI_BINDING.json').read_text())
assert binding['source_tree_sha256'] == '64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667'
assert json.loads((root/'PACKAGED_RUNTIME_SMOKE.json').read_text())['status'] == 'PASS'
meta = {
 'candidate': 'CP11_DEPTH40_P03_PARENT_20260911',
 'candidate_build_commit': 'c909af370d55ce7644140a191425a8a66dacec9a',
 'source_tree_sha256': binding['source_tree_sha256'], 'source_files': 1271,
 'parent_archive_sha256': '2909651f9b644ed56fd6ab833480c9da32b4c5b900df2e5afb192dba49ac2b00',
 'parent_artifact_id': 10183252130,
 'packaging_commit': a.tooling_sha, 'packaging_run': a.run_id,
 'runtime_archive': image.name, 'runtime_archive_sha256': image_sha,
 'runtime_archive_bytes': image.stat().st_size, 'image_uncompressed_bytes': image_size,
 'docker_image_config_id': (root/'IMAGE_ID.txt').read_text().strip(),
 'registry_repo_digest': None,
 'registry_repo_digest_note': 'Offline docker-save image, not pushed to a registry. Config ID is not a registry RepoDigest.',
 'runtime_scope': 'ISOLATED_SQLITE_HTTP_WITH_FROZEN_SOURCE',
 'runtime_dependencies_included': True, 'runtime_interpreter': 'CPython 3.13.5',
 'platform': 'linux/amd64', 'runtime_os_library_origin': 'ubuntu-22.04 GitHub runner',
 'offline_save_load_and_boot': 'PASS_CI', 'production_runtime': False,
 'node_and_native_client_acceptance': 'NOT_INCLUDED_IN_THIS_RUNTIME_GATE',
 'first_browser_gate': 'HOLD', 'six_vertical_gate': 'HOLD', 'final_release': 'HOLD',
 'hong_kong_execution': 'NOT_RUN', 'deployment_authorized': False,
 'planned_environment': 'HK-ISOLATED-DEPTH40-REVIEW', 'environment_created': False,
 'signature_and_hk_runtime_binding': 'TO_BE_GENERATED_AFTER_SEPARATE_APPROVED_EXECUTION',
 'server_current_image': 'USER_REPORTED_20260911_0945_R3.1.5_NOT_INSPECTED_BY_THIS_BUILD',
}
(root/'RUNTIME_MANIFEST.json').write_text(json.dumps(meta, indent=2)+'\n')
# Advisory planning figures, never an assertion of current HK capacity.
gib = 1024**3
budget = {'schema':'go.isolated-runtime-budget.v1', 'observed_server_source':'user-transferred HK receipt 2026-09-11 09:45–09:46 CST; raw output absent',
 'reported_free_disk_bytes':5705682944, 'reported_available_memory_bytes':1822203904,
 'measured_runtime_archive_bytes':image.stat().st_size, 'measured_image_bytes':image_size,
 'planning':{'delivery_and_archive_copies':2*image.stat().st_size,
             'docker_layers_and_import_headroom':2*image_size,
             'private_database_data_logs_quota_bytes':512*1024**2,
             'host_disk_reserve_bytes':2*gib, 'container_memory_cap_bytes':768*1024**2,
             'host_memory_reserve_bytes':768*1024**2, 'container_cpu_cap':0.5},
 'capacity_gate':'HOLD_FRESH_PREFLIGHT_AND_BUDGET_APPROVAL',
 'limits':'Single API acceptance session only; no load guarantee, no PG/Redis/workers, no local image build, no existing image/data deletion.'}
budget['planned_disk_requirement_bytes'] = sum(budget['planning'][k] for k in ['delivery_and_archive_copies','docker_layers_and_import_headroom','private_database_data_logs_quota_bytes','host_disk_reserve_bytes'])
(root/'RESOURCE_BUDGET.json').write_text(json.dumps(budget, indent=2)+'\n')
for name in ('ISOLATION_AND_APPROVAL.md', 'compose.review.yml', 'verify_delivery.py'):
 shutil.copy2(a.tooling/name, root/name)
# Split only for permanent Git storage. Preserve byte identity on reassembly.
parts=[]
with image.open('rb') as stream:
 for index in range(1000):
  data=stream.read(20*1024*1024)
  if not data: break
  part=root/f'{image.name}.part{index:03}'
  part.write_bytes(data); parts.append({'name':part.name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()})
(root/'RUNTIME_PARTS.json').write_text(json.dumps({'archive_name':image.name,'archive_sha256':image_sha,'size':image.stat().st_size,'parts':parts},indent=2)+'\n')
image.unlink()  # Reconstruct from ordered parts; no duplicate image bytes in archive.
checks={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
(root/'SHA256SUMS').write_text(''.join(f'{h}  {p}\n' for p,h in sorted(checks.items())))
print(json.dumps(meta))
