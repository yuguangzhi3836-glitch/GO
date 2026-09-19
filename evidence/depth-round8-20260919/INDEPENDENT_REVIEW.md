# Independent gallery safety review — 2026-09-19

Scope: operation-local original-image fact reuse in the direct-submission verification, review and public-media call chain. This is a limited performance/security improvement, not complete application acceptance.

## Conclusion

No blocking defect found in the reviewed change. Only decoded image facts are cached; ownership, physical-room binding, rights declarations, current rights/expiry and persisted review state continue to be checked by the existing services. The scope is synchronous and bounded to the outer call. Thread/task ownership prevents copied contexts from sharing active facts with another execution owner; active-state invalidation, clearing and ContextVar reset run on exceptional exit too.

Cache reuse checks the safe path and current device/inode/size/mtime/ctime plus recorded SHA. Content changes, same-size overwrite with restored mtime, deletion, symlink substitution and record-SHA changes invalidate reuse or fail verification. Fresh operations reread bytes. Returned metadata is copied, and original response bytes still pass their existing integrity check. This is not a claim of a transactional filesystem snapshot: changes can still race an individual read/stat as with the existing file path.

I recommended adding a test where the parent context remains active while a child task executes. The implementation agent added that case; I inspected and independently ran it, then reran the final complete scope test file. Rights revocation, review revocation and expiry are separate final cases.

## Actual independent commands and results

Working directory: `application`. Interpreter: `/workspace/scratch/7375eae00ed5/go-depth-venv/bin/python`.

1. `PYTHONPATH=src /workspace/scratch/7375eae00ed5/go-depth-venv/bin/python -m pytest -q tests/test_hotel_original_verification_scope.py tests/test_hotel_direct_submission_verification.py tests/test_hotel_direct_submission_publication.py`
   - Exit 0; all tests collected in that run passed. At collection time the scope file contained 9 cases, before the later additions; verification 16 and publication 13 give 38 cases.
2. `PYTHONPATH=src /workspace/scratch/7375eae00ed5/go-depth-venv/bin/python -m pytest -q tests/test_hotel_original_verification_scope.py::test_active_inherited_context_cannot_share_cache_between_tasks`
   - Exit 0, 1 passed.
3. `PYTHONPATH=src /workspace/scratch/7375eae00ed5/go-depth-venv/bin/python -m pytest -o addopts='' -q tests/test_hotel_original_verification_scope.py`
   - Final scope file: **12 passed**, 2 dependency deprecation warnings, 16.62 seconds.

Final unique independently passing case coverage is **41** (12 scope + 16 verification + 13 publication); these are not 41 additional tests on top of the parent regression suite. The only warnings concern Starlette/httpx and AnyIO API deprecations.

## Remaining limits

- Public reads still validate the complete manifest/gallery: **O(N)** per new operation. This removes repeated decoding within one operation, not all-gallery work or database query cost.
- No browser or mobile rendered flow was executed by this reviewer.
- No PostgreSQL concurrency test was executed by this reviewer; the isolated SQLite service tests do not prove database locking semantics.
- No live hotel data was approved, published or altered. Historical assets and current rights/binding evidence remain separate from this cache review.

## Reviewed final file hashes

| File | SHA-256 |
| --- | --- |
| `application/src/go_hotel/services/hotel_original_verification_scope.py` | `321ed874761b1a7ca8be4dd8d299e7505ed23f6b3d40d36d8ff55e24cc955d9e` |
| `application/src/go_hotel/services/hotel_direct_submission_verification.py` | `318c5b267948f99d360c645e29eb1c74a49a2062b9fc2a7690ff0ab68f27738e` |
| `application/src/go_hotel/services/hotel_direct_submission_review.py` | `ca13968045bdec8fcf59359825edc21d0be9f8d1c573e8bbc3bf49e9ab4dcd17` |
| `application/src/go_hotel/services/hotel_direct_submission_publication.py` | `650812d4da0878fd392abccc63a2f081343b067e00fd9dddb898a6c9080700d3` |
| `application/src/go_hotel/services/hotel_autopage_factory.py` | `3ec0cc286ab7d764c07711fce870dad996364c143b8fba231a6108b45dedb0ea` |
| `application/tests/test_hotel_original_verification_scope.py` | `e67ab31098752588cbb0f646cbea9741193129ac68bf2c6543d2e8efe7eb2307` |
