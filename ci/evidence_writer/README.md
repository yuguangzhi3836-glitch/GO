# Shared Evidence writer

`writer.py` is the single publication boundary for task-bound Evidence bundles.
It rejects non-canonical JSON (including a final literal `\\n`), binds the
bundle to the candidate commit, application tree and hashed source set, and
publishes only after an independent digest/schema verification of a staged
directory.

Create and verify a bundle with:

```sh
python ci/evidence_writer/writer.py create \
  --target evidence-out/bundle \
  --source-root . \
  --source-path ci/evidence_writer/writer.py \
  --cell SHARED \
  --task-id SHARED-EVIDENCE-WRITER-V1 \
  --candidate "$CANDIDATE_SHA" \
  --application-tree "$APPLICATION_TREE" \
  --json RESULT.json=RESULT.input.json \
  --file raw.log=writer-tests.log

python ci/evidence_writer/writer.py verify \
  --bundle evidence-out/bundle \
  --candidate "$CANDIDATE_SHA" \
  --application-tree "$APPLICATION_TREE" \
  --cell SHARED \
  --task-id SHARED-EVIDENCE-WRITER-V1
```

Callers must pass the checked-out head SHA, not a pull-request merge SHA. An
existing target, source mismatch, invalid JSON, symlink, digest mismatch or
binding mismatch fails closed and leaves no newly published bundle.
