"""Tests for the Trust Meter 0.2.0 release-candidate source contract."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from trust_meter import __version__
from tools import release_bundle as bundle


ROOT = Path(__file__).resolve().parents[1]


def test_release_candidate_version_is_exact_and_equal_at_runtime():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["version"] == __version__
    assert __version__ == bundle.RELEASE_VERSION == "0.2.0"


def test_schema_root_packaging_and_release_url_are_bound():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "schemas" / bundle.SCHEMA_NAME).read_text(encoding="utf-8"),
    )
    force_include = metadata["tool"]["hatch"]["build"]["targets"]["wheel"][
        "force-include"
    ]

    assert schema["$id"] == bundle.SCHEMA_ID == (
        "https://github.com/taipei49314/trust-meter/releases/download/"
        "v0.2.0/trust-meter-measure-v1.schema.json"
    )
    assert force_include["schemas/trust-meter-measure-v1.schema.json"] == (
        "trust_meter/schemas/trust-meter-measure-v1.schema.json"
    )
    assert bundle.SCHEMA_NAME in bundle.release_asset_names()


def test_release_notes_preserve_candidate_and_authority_boundaries():
    notes_path = ROOT / ".github" / bundle.RELEASE_NOTES_NAME
    notes = bundle.read_release_notes(notes_path)
    flattened = " ".join(notes.split())

    assert notes.startswith("# Trust Meter v0.2.0\n")
    assert "release candidate before publication" in flattened
    assert "`authority_effect` fixed to `none`" in flattened
    assert "does not grant Evidence Workbench execution admission" in flattened
    assert "does not provide production multi-tool orchestration" in flattened
    assert "human must recheck" in flattened
    assert ".github/RELEASE_NOTES-v0.2.0.md text eol=lf" in (
        ROOT / ".gitattributes"
    ).read_text(encoding="utf-8")


def test_pypi_is_not_a_release_channel_or_workflow_target():
    workflow_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    ).lower()
    notes = (ROOT / ".github" / bundle.RELEASE_NOTES_NAME).read_text(
        encoding="utf-8",
    )

    assert "pypa/gh-action-pypi-publish" not in workflow_text
    assert "upload.pypi.org" not in workflow_text
    assert "twine" not in workflow_text
    assert "PyPI is not a publication channel for this release" in notes
