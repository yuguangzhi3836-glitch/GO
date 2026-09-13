# Local pagination repair evidence

2026-09-13. Existing private Python 3.12 environment, new temporary SQLite per
test, FastAPI TestClient. 28 SQL/HTTP tests passed. One focused original-source
check reproduced the missing exact-order filtering before applying the repair.
Raw log and JUnit are retained. These are local tests, not independent CI or HK.

The local cached application is missing four unchanged PNG blobs. Their GitHub
identities and the prior verified full source fingerprint are retained when
constructing the candidate tree. No image is replaced with a placeholder and no
complete local browser/runtime validation is claimed. Fresh CI checkout must
verify all 1325 files before browser execution; source-fingerprint.json is the
expected candidate manifest, not a claim that missing local images were read.

Candidate: ../../ci/admin-pagination/CANDIDATE.json. No shared database or network
endpoint was accessed by these tests. No migration or runtime change was made.
