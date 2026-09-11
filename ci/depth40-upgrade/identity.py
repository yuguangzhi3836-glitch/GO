"""Previously sealed candidate. This supplement never builds a replacement image."""
CANDIDATE = 'CP11_DEPTH40_P03_PARENT_20260911'
BUILD = 'c909af370d55ce7644140a191425a8a66dacec9a'
ARTIFACT = 10183252130
PARENT_ZIP = 'd0aa4b89ed0655271cf5ef7a12cce354dc8d84704cf57071f581f129458cbaf7'
PARENT_ARCHIVE = '2909651f9b644ed56fd6ab833480c9da32b4c5b900df2e5afb192dba49ac2b00'
TREE = '64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667'
RUNTIME_ARTIFACT = 10186084217
RUNTIME_RUN = 34565938702
RUNTIME_ZIP = '715b939feb5529fcd97860ed921e5b292a874a2cbfacae0706a4da39023aad4f'
SUMS = 'c1d24da5428be366aededb9ac7de6d396d807e7c7cc426b1b3efffb3046c7afd'
VERIFIER = '1a3536672581f19a7f1addc72f662fee07e759507e3daae70efdf311762710b6'
IMAGE_ARCHIVE = '68291f358733f4aabf87902e14771baf4a467b2346bc49c4a4701be9d39cd9a0'
IMAGE = 'sha256:9ec6ebaf962b6f5e880ecaa2e878a2ec1e51bfd0f1f4012b90aa709692d5057b'
BEFORE = '0114_ext_truth_incident_hard'
AFTER = '0132_rail_runtime_field_widths'


def binding():
    return dict(candidate=CANDIDATE, parent_build=BUILD, parent_artifact=ARTIFACT,
                parent_zip_sha256=PARENT_ZIP, parent_archive_sha256=PARENT_ARCHIVE,
                source_tree_sha256=TREE, source_files=1271,
                runtime_artifact=RUNTIME_ARTIFACT, runtime_run=RUNTIME_RUN,
                runtime_zip_sha256=RUNTIME_ZIP, image_archive_sha256=IMAGE_ARCHIVE,
                image_id=IMAGE, source_modified=False, image_rebuilt=False)
