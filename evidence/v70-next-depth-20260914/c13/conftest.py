"""Independent diagnostics reuse the canonical isolated database lifecycle only."""
import importlib.util
from pathlib import Path
import sys
APP = Path(__file__).resolve().parents[3] / 'application'
for path in (APP / 'tests', APP / 'tests/journey'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
spec = importlib.util.spec_from_file_location('c13_next_canonical_fixtures', APP / 'tests/conftest.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
reset_db = fixtures.reset_db
client = fixtures.client
