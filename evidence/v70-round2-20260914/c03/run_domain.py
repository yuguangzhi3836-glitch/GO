"""Capture isolated domain pytest evidence without changing runtime configuration."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "application"
ANCHOR = "fef9c748adb77d37ba5d4dc4fa4662eb668303a1"
CELL, RUN, *ARGS = sys.argv[1:]
OUT = ROOT / "evidence/v70-round2-20260914" / CELL
OUT.mkdir(parents=True, exist_ok=True)
PREFIXES = {
    "c03": ["src/go_hotel/rail/", "src/go_hotel/services/rail_change_resolution.py", "src/go_hotel/services/vertical_capacity.py", "src/go_hotel/services/vertical_refund_recovery.py", "src/go_hotel/api/routes/rail.py"],
    "c06": ["src/go_hotel/attractions/", "src/go_hotel/services/vertical_capacity.py", "src/go_hotel/services/vertical_refund_recovery.py", "src/go_hotel/api/routes/attractions.py"],
    "c09": ["src/go_hotel/judgment/", "src/go_hotel/api/routes/judgment.py"],
}

def snapshot():
    files = set()
    for prefix in PREFIXES[CELL]:
        p = APP / prefix
        files.update(p.rglob("*.py") if p.is_dir() else [p])
    for arg in ARGS:
        p = APP / arg.split("::")[0]
        if p.is_file():
            files.add(p)
        elif p.is_dir() and arg.startswith("tests/"):
            files.update(p.rglob("*.py"))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files) if p.is_file()}

before = snapshot()
(OUT / f"{RUN}.hashes-before.json").write_text(json.dumps(before, indent=2) + "\n")
database = "/tmp/go-v70-r2-" + CELL + "-" + uuid.uuid4().hex + ".db"
env = dict(os.environ, PYTHONPATH="src", GO_TEST_DB_PATH=database, PYTHONDONTWRITEBYTECODE="1")
command = [sys.executable, "-m", "pytest", *ARGS, "-q", "-p", "no:cacheprovider", "--junitxml=" + str(OUT / f"{RUN}.junit.xml")]
start = datetime.datetime.now(datetime.timezone.utc).isoformat()
metadata = {"anchor": ANCHOR, "cell": CELL.upper(), "run": RUN, "cwd": str(APP), "argv": command, "environment_overrides": {"PYTHONPATH": "src", "GO_TEST_DB_PATH": database, "PYTHONDONTWRITEBYTECODE": "1"}, "runtime": sys.version, "started_at": start, "database_backend": "isolated SQLite", "external_provider": "simulated", "hk_or_browser_acceptance": False}
(OUT / f"{RUN}.command.json").write_text(json.dumps(metadata, indent=2) + "\n")
with (OUT / f"{RUN}.raw.log").open("w") as logfile:
    process = subprocess.run(command, cwd=APP, env=env, stdout=logfile, stderr=subprocess.STDOUT)
after = snapshot()
(OUT / f"{RUN}.hashes-after.json").write_text(json.dumps(after, indent=2) + "\n")
metadata.update(exit_code=process.returncode, ended_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), domain_unchanged_during_run=before == after)
(OUT / f"{RUN}.result.json").write_text(json.dumps(metadata, indent=2) + "\n")
print(json.dumps(metadata))
print((OUT / f"{RUN}.raw.log").read_text()[-12000:])
sys.exit(process.returncode)
