# Test evidence hygiene

The original PR #273 R4 redaction covered `first-fix.log/xml` but omitted the
independent failed-test reports. Pytest had included the Authorization fixture
in failure diagnostics. This guard removes credential values before terminal
and JUnit consumers receive test reports, and prepares a separate sanitized
directory before the affected workflow uploads any evidence.

The implementation lives in `application/tests/` so application-only frozen
test sources include it. `application/tests/conftest.py` loads its hooks for
application tests. The CLI uses only the Python standard library.

```sh
python -m pytest ci/evidence_hygiene/test_guard.py -q
python application/tests/evidence_hygiene.py scan docs/acceptance/rental-attractions
python application/tests/evidence_hygiene.py prepare raw-evidence publish-evidence
```

Use `set -o pipefail` with `producer 2>&1 | python
application/tests/evidence_hygiene.py stream | tee evidence.log`. The stream
filter buffers at most 16 MiB of characters and rejects larger output before
echoing it, including credentials split over multiple lines. Original producer
failure remains a failure. Pytest hooks cover failed setup, collection, test
failure, skip reasons, captured output and report properties. They are not a
replacement for filtering direct live output (`-s`, live logging, other tools).

`prepare` leaves its input unchanged, sanitizes UTF-8 text, rescans the staged
output, and computes `SANITIZATION.json` and `SHA256.json` from published bytes.
It creates the destination only when every input passes. Failure verdicts and
JUnit counts are retained. Archives, symlinks, unsupported binaries, NUL text,
oversized files and credential-bearing filenames are rejected. PNG screenshots
are checked for credential byte strings but receive no OCR or visual clearance.

Upload only the prepared directory and require the preparation step's success.
Never fall back to uploading the original directory on failure. Sanitized
diagnostics may be uploaded when tests fail; this must not turn the test result
green. The workflow's evidence-hygiene job gates both subsequent acceptance jobs.

This is a targeted Authorization/session credential guard. For an independent
rescan, use Gitleaks with its default rules plus `gitleaks.toml`; do not silently
ignore generic matches or treat a detector exit code of 1 as a clean scan. The
R5 scan report records reviewed business identifiers and source-file hashes
separately from historical credential fragments. Additional workflows that
publish evidence should adopt this same preparation boundary before upload.
