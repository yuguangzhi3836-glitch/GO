"""The candidate's dependency profile must stay one Hong Kong can build.

Hong Kong builds a candidate image with the network switched off, from a base
image whose wheels are already installed, and its TEST_PR executor refuses any
candidate whose declared dependency profile is not one of the two it was
provisioned for (``TEST_PR_DEPENDENCY_PROFILE_REJECT``).  Adding a dependency to
``pyproject.toml`` therefore looks harmless on a developer machine and makes the
candidate undeployable on the only host we deploy to -- which is exactly what
happened, and what this asserts against.

Note the shape of the failure: the reject happens *before* the image is built, so
nothing about the candidate's own tests can reveal it.  Only the profile can.

The digest is recomputed the way the executor recomputes it, over exactly the
three fields it hashes.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import tomllib

import pytest

PYPROJECT = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"

#: Both profiles the Hong Kong executor accepts: the legacy requirement set, and
#: the legacy set plus ``uvicorn[standard]`` (the one this repository declares).
ACCEPTED_PROFILES = {
    "904ede5e7ee3408e5f80bc2957d5f4b4d32754be6797bf6a53cff545b2fc94aa",
    "c3140ecf1e38bf7f635ff6a80758677441a56866d0aa18727a2f6193adc707e1",
}


def dependency_profile(path: pathlib.Path) -> str:
    project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
    hashed = {
        "requires-python": project["requires-python"],
        "dependencies": project["dependencies"],
        "optional-dependencies": {"dev": project.get("optional-dependencies", {})["dev"]},
    }
    encoded = json.dumps(hashed, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@pytest.mark.no_db
def test_the_dependency_profile_is_one_hong_kong_can_build():
    profile = dependency_profile(PYPROJECT)
    assert profile in ACCEPTED_PROFILES, (
        "pyproject.toml no longer matches a dependency profile the Hong Kong "
        "TEST_PR executor was provisioned for, so every candidate build is "
        "rejected with TEST_PR_DEPENDENCY_PROFILE_REJECT before an image exists. "
        f"Observed {profile}. A new runtime dependency has to be provisioned into "
        "the image first; it cannot be added from this repository."
    )
