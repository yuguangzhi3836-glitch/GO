"""External harness adapter; product files and installed distributions stay untouched."""
import hashlib, importlib.util, json, pathlib, sys
spec = importlib.util.spec_from_file_location("image_acceptance_runtime", "/app/scripts/acceptance_runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
EXCLUDED = {".pytest_cache/.gitignore", ".pytest_cache/CACHEDIR.TAG", ".pytest_cache/README.md", ".pytest_cache/v/cache/nodeids"}
def verify(root, fp, expected):
    assert str(root) == "/app"
    assert runtime.tree_hash(fp) == expected == "1c4d78c3c1bb5f448d0ebdb99d16a2d76419bbc663cc9ed8fae831e1d18c10c4"
    assert len(fp) == 1332 and EXCLUDED <= set(fp)
    kept = {p: h for p, h in fp.items() if p not in EXCLUDED}
    for p, h in kept.items():
        f = pathlib.Path(root) / p
        assert not f.is_symlink() and f.is_file() and hashlib.sha256(f.read_bytes()).hexdigest() == h, p
    assert all(not (pathlib.Path(root) / p).exists() for p in EXCLUDED)
    print(json.dumps({"canonical_source_files":1332,"image_verified_files":len(kept),"image_runtime_source_sha256":runtime.tree_hash(kept),"canonical_cache_exclusions":sorted(EXCLUDED)}), flush=True)
    return len(kept)
runtime.verify_source = verify
runtime.main()

