"""Independent C13 tests reuse only the canonical isolated database lifecycle."""
import importlib.util
from pathlib import Path
APP = Path(__file__).resolve().parents[3] / 'application'
spec = importlib.util.spec_from_file_location('c13_canonical_fixture_lifecycle', APP / 'tests/conftest.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
reset_db = fixtures.reset_db
client = fixtures.client
