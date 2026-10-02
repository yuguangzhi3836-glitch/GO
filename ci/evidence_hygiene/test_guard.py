import base64
import hashlib
import html
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from application.tests.evidence_hygiene import MARKER, prepare, redact, scan

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "application/tests/evidence_hygiene.py"


def credential():
    # Generated locally for these tests, never issued by any service.
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    return header + "." + secrets.token_urlsafe(64) + "." + secrets.token_urlsafe(32)


@pytest.mark.parametrize("encoding", ["repr", "json", "escaped_json", "xml", "assignment", "header", "fragment", "bare_jwt"])
def test_redacts_encodings_and_is_idempotent(encoding):
    token = credential()
    if encoding == "repr":
        value = repr({"Authorization": "Bearer " + token})
    elif encoding == "json":
        value = json.dumps({"Authorization": "Bearer " + token})
    elif encoding == "escaped_json":
        value = json.dumps(json.dumps({"Authorization": "Bearer " + token}))
    elif encoding == "xml":
        value = '<failure message="' + html.escape(repr({"Authorization": "Bearer " + token}), quote=True) + '"/>'
    elif encoding == "assignment":
        value = "refresh_token=" + token
    elif encoding == "header":
        value = "a retained failure\nCookie: go_access=" + token + "; go_refresh=" + token
    elif encoding == "fragment":
        token = token[:70] + "..." + token[-95:]
        value = "workspace = " + repr({"Authorization": "Bearer " + token})
    else:
        value = token
    clean, count = redact(value)
    assert count > 0 and token not in clean and MARKER in clean
    assert redact(clean) == (clean, 0)
    if encoding == "xml":
        ET.fromstring(clean)
    if encoding in {"json", "escaped_json"}:
        json.loads(clean)


def test_stream_multiline_and_original_pipeline_exit(tmp_path):
    token = secrets.token_urlsafe(32)
    source = 'refresh_token="' + token + '\ncontinued"\nretained failure\n'
    streamed = subprocess.run([sys.executable, str(GUARD), "stream"], input=source, capture_output=True, text=True)
    assert streamed.returncode == 0 and token not in streamed.stdout
    assert "retained failure" in streamed.stdout
    script = f'set -o pipefail; "{sys.executable}" -c "raise SystemExit(7)" 2>&1 | "{sys.executable}" "{GUARD}" stream | tee "{tmp_path / "log"}"'
    failed = subprocess.run(["bash", "-c", script], capture_output=True)
    assert failed.returncode == 7


def test_existing_redaction_marker_is_not_rewritten():
    value = repr({"Authorization": "Bearer " + MARKER})
    assert redact(value) == (value, 0)


def test_actual_application_conftest_applies_guard_without_database(tmp_path):
    repo = tmp_path / "repo"
    tests = repo / "application/tests"
    tests.mkdir(parents=True)
    for name in ["evidence_hygiene.py", "evidence_hygiene_plugin.py"]:
        (tests / name).write_text((ROOT / "application/tests" / name).read_text())
    (tests / "conftest.py").write_text((ROOT / "application/tests/conftest.py").read_text())
    (tests / "test_smoke.py").write_text("import os,pytest\n@pytest.mark.no_db\ndef test_smoke():\n    assert False, 'Authorization: Bearer '+os.environ['HYGIENE_TEST_VALUE']\n")
    token = credential()
    result = subprocess.run([sys.executable, "-m", "pytest", "tests", "--junitxml=report.xml"],
                            cwd=repo / "application", env={**os.environ, "HYGIENE_TEST_VALUE": token},
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert token not in result.stdout + result.stderr + (repo / "application/report.xml").read_text()
    assert MARKER in result.stdout


def test_prepare_hashes_only_sanitized_bytes_preserves_xml_verdict(tmp_path):
    raw = tmp_path / "raw"; raw.mkdir()
    token = credential()
    text = '<testsuite tests="1" failures="1"><testcase name="failure"><failure>Authorization: Bearer ' + token + '</failure></testcase></testsuite>'
    (raw / "junit.xml").write_text(text)
    (raw / "SHA256.json").write_text('{}')
    destination = tmp_path / "published"
    result = prepare(raw, destination)
    assert result["status"] == "PASS"
    assert scan([destination])["status"] == "PASS"
    cleaned = (destination / "junit.xml").read_text()
    assert token not in cleaned and ET.fromstring(cleaned).attrib["failures"] == "1"
    hashes = json.loads((destination / "SHA256.json").read_text())
    assert hashes["junit.xml"] == hashlib.sha256(cleaned.encode()).hexdigest()
    manifest = json.loads((destination / "SANITIZATION.json").read_text())
    assert manifest["files"][0]["original_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert token in (raw / "junit.xml").read_text()  # Sanitization never overwrites original inputs.


@pytest.mark.parametrize("unsafe", ["symlink", "source_symlink", "archive", "nul", "png_credential"])
def test_unsafe_artifact_never_creates_publish_destination(tmp_path, unsafe):
    source = tmp_path / "raw"; source.mkdir()
    (source / "safe.log").write_text("diagnostic")
    if unsafe == "symlink":
        (source / "outside").symlink_to(tmp_path / "missing")
    elif unsafe == "source_symlink":
        alias = tmp_path / "alias"; alias.symlink_to(source, target_is_directory=True); source = alias
    elif unsafe == "archive":
        (source / "hidden.zip").write_bytes(b"PK\x03\x04\xff")
    elif unsafe == "nul":
        (source / "nul.log").write_bytes(b"a\x00b")
    else:
        (source / "view.png").write_bytes(b"\x89PNG\r\n\x1a\n" + ("Bearer " + credential()).encode())
    destination = tmp_path / "published"
    with pytest.raises(ValueError):
        prepare(source, destination)
    assert not destination.exists()


@pytest.mark.parametrize("mode", ["failure", "setup", "collection", "skipped"])
@pytest.mark.parametrize("kind", ["jwt", "opaque"])
def test_pytest_console_junit_and_properties_do_not_publish_credentials(tmp_path, mode, kind):
    token = credential() if kind == "jwt" else secrets.token_urlsafe(64)
    code = '''import os,sys,logging,pytest
token=os.environ['HYGIENE_TEST_VALUE']
@pytest.fixture
def workspace():
    return {'Authorization':'Bearer '+token}
def test_failure(workspace,record_property):
    record_property('refresh_token',token)
    print('Cookie: go_access='+token)
    print('Authorization: Bearer '+token,file=sys.stderr)
    logging.warning('refresh_token="%s"',token)
    assert False, 'retained diagnostic Authorization: Bearer '+token
'''
    if mode == "setup":
        code = "import os,pytest\n@pytest.fixture(autouse=True)\ndef setup():\n    raise ValueError('Authorization: Bearer '+os.environ['HYGIENE_TEST_VALUE'])\ndef test_setup(): pass\n"
    elif mode == "collection":
        code = "import os\nraise ValueError('Authorization: Bearer '+os.environ['HYGIENE_TEST_VALUE'])\n"
    elif mode == "skipped":
        code = "import os,pytest\ndef test_skip():\n    pytest.skip('Authorization: Bearer '+os.environ['HYGIENE_TEST_VALUE'])\n"
    (tmp_path / "test_fixture.py").write_text(code)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "application"), "HYGIENE_TEST_VALUE": token}
    result = subprocess.run([sys.executable, "-m", "pytest", "-p", "tests.evidence_hygiene_plugin",
                             "--showlocals", "--junitxml=report.xml", "-o", "junit_logging=all", "-rs", "test_fixture.py"],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    combined = result.stdout + result.stderr + (tmp_path / "report.xml").read_text()
    assert token not in combined
    assert redact(combined)[1] == 0
    suite = ET.parse(tmp_path / "report.xml").getroot().find("testsuite")
    assert result.returncode == {"failure": 1, "setup": 1, "collection": 2, "skipped": 0}[mode]
    assert suite.attrib[{"failure": "failures", "setup": "errors", "collection": "errors", "skipped": "skipped"}[mode]] == "1"
