"""Generate small parent metadata; large payloads are existing immutable Git trees."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = 'CP11_DEPTH48_SOURCE_COMPOSITE_PARENT_20260913'


def main():
    inputs = json.loads((HERE / 'inputs.json').read_text())
    old = inputs['previous_manifest']
    parts = inputs['parts']
    leaves = {n: (HERE / n).read_text() for n in ('README.md', 'verify_parent.py', 'create_archive.py')}
    metadata = {n: hashlib.sha256(v.encode()).hexdigest() for n, v in leaves.items()}
    manifest = {
        'schema': 'go.source-composite-parent.v1', 'name': NAME, 'created_date': '2026-09-13',
        'package_kind': 'SOURCE_COMPOSITE_CANDIDATE', 'assembly_method': 'GIT_OBJECT_COMPOSITION',
        'source_snapshot_commit': inputs['source_commit'],
        'source_snapshot_rule': 'All root entries except deliverables; exact DEPTH46 archive retained separately',
        'payloads': {
            'source': {'git_tree': inputs['source_git_tree'], 'files': inputs['source_files'], 'bytes': inputs['source_bytes']},
            'previous_parent': {'git_tree': inputs['previous_parent_git_tree'], 'files': 24, 'bytes': 314744185}},
        'application': {'source_commit': '8a22a4fcbba4574f5a06e356e461d7d083c86ae1',
            'git_tree': 'ad7d1de1190f86ad29d1c6cdafbcedd592e27206', 'files': 1323,
            'source_tree_sha256': '8e91fcf25e66478d5dac105c2608a195a98290640f2ecbfcec24fda27f212ac8',
            'fingerprint_path': 'docs/canonical-baseline/DEPTH48_SOURCE_FINGERPRINT.json',
            'business_source_modified_this_assembly': False, 'image_placeholders_used': False},
        'previous_parent': {'name': 'CP11_DEPTH46_CONSOLIDATED_PARENT_20260913',
            'archive_directory': 'deliverables/CP11_DEPTH46_CONSOLIDATED_PARENT_20260913',
            'zip_bytes': parts['zip_bytes'], 'zip_sha256': parts['zip_sha256'], 'parts': len(parts['parts']),
            'application_git_tree': old['application_git_tree'], 'image_config_id': old['image_config_id'],
            'image_archive_sha256': old['image_archive_sha256'], 'bytes_reused_without_change': True,
            'runtime_scope': 'HISTORICAL_DEPTH46_ONLY'},
        'new_runtime': {'status': 'NOT_BUILT', 'image_config_id': None, 'image_archive_sha256': None,
            'self_contained_runtime_parent': False},
        'evidence': {'inherited_results': 'source/evidence/depth48-ordered-repairs/LOCAL_RESULTS.json',
            'application_tests_rerun_this_assembly': False, 'browser_rerun_this_assembly': False,
            'historical_browser_pass_transferred': False,
            'full_package_byte_verification': 'NOT_RUN_IN_CURRENT_ENVIRONMENT',
            'full_package_restore': 'NOT_RUN_IN_CURRENT_ENVIRONMENT',
            'packaging_tests': '8_SYNTHETIC_TESTS_PASS_SEPARATELY_RECORDED',
            'ci': 'PRIOR_FAILED_BEFORE_STEPS_NO_NEW_PASS_CLAIM'},
        'gates': {'FULL_THREE_END_UX': 'HOLD', 'POSTGRESQL': 'HOLD', 'FROZEN_RUNTIME_CI': 'HOLD',
            'SEALED_NODE': 'HOLD', 'FINAL_RELEASE': 'HOLD', 'PRODUCTION': 'HOLD'},
        'hk_execution': 'NOT_RUN', 'production_execution': 'NOT_RUN',
        'metadata_sha256': metadata}
    leaves['PARENT_MANIFEST.json'] = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    manifest_sha = hashlib.sha256(leaves['PARENT_MANIFEST.json'].encode()).hexdigest()
    sums = dict(metadata, **{'PARENT_MANIFEST.json': manifest_sha})
    leaves['MANIFEST.sha256'] = ''.join(f'{h}  {n}\n' for n, h in sorted(sums.items()))
    leaf_objects = {n: {'mode': '100644', 'type': 'blob', 'size': len(v.encode()),
        'sha': hashlib.sha1(b'blob ' + str(len(v.encode())).encode() + b'\0' + v.encode()).hexdigest()}
        for n, v in leaves.items()}
    output = {'name': NAME, 'manifest_sha256': manifest_sha, 'manifest': manifest, 'leaf_objects': leaf_objects,
        'tree_elements': [{'path': 'source', 'mode': '040000', 'type': 'tree', 'sha': inputs['source_git_tree']},
                          {'path': 'previous_parent', 'mode': '040000', 'type': 'tree', 'sha': inputs['previous_parent_git_tree']}] +
                         [{'path': n, 'mode': '100644', 'type': 'blob', 'content': v} for n, v in sorted(leaves.items())]}
    (HERE / 'generated_tree.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'metadata': 'GENERATED', 'name': NAME, 'manifest_sha256': manifest_sha}))


if __name__ == '__main__':
    main()
