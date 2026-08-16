"""Tests for exact Trust Meter GitHub release bundle construction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools import release_bundle as bundle


SYNTHETIC_RELEASE_NOTES = "# Trust Meter v0.2.1\n\nSynthetic release notes.\n"


def write_bundle(root: Path) -> Path:
    """Create an exact synthetic release bundle."""
    target = root / "release-bundle"
    assets = target / "release-assets"
    control = target / "control"
    assets.mkdir(parents=True)
    control.mkdir()
    wheel, sdist, schema, checksum = bundle.release_asset_names()
    payload = {
        wheel: b"wheel bytes\n",
        sdist: b"sdist bytes\n",
        schema: b'{"type":"object"}\n',
    }
    for name, data in payload.items():
        (assets / name).write_bytes(data)
    rows = [
        f"{hashlib.sha256(payload[name]).hexdigest()}  {name}\n"
        for name in sorted(payload)
    ]
    (assets / checksum).write_text("".join(rows), encoding="ascii", newline="\n")
    for name in bundle.CONTROL_SCRIPT_NAMES:
        (control / name).write_text("# trusted release control\n", encoding="utf-8")
    (control / bundle.RELEASE_NOTES_NAME).write_text(
        SYNTHETIC_RELEASE_NOTES, encoding="utf-8", newline="\n",
    )
    return target


def _write_candidate_source(
    project: Path, *, metadata_version: str = "0.2.1",
    runtime_version: str = "0.2.1", schema_text: str | None = None,
) -> None:
    package = project / "src" / "trust_meter"
    schema_dir = project / "schemas"
    notes_dir = project / ".github"
    package.mkdir(parents=True)
    schema_dir.mkdir()
    notes_dir.mkdir()
    (project / "pyproject.toml").write_text(
        f'[project]\nname = "trust-meter"\nversion = "{metadata_version}"\n',
        encoding="utf-8",
    )
    (package / "__init__.py").write_text(
        f'__version__ = "{runtime_version}"\n', encoding="utf-8",
    )
    if schema_text is None:
        schema_text = json.dumps({"$id": bundle.SCHEMA_ID}) + "\n"
    (schema_dir / bundle.SCHEMA_NAME).write_text(schema_text, encoding="utf-8")
    (notes_dir / bundle.RELEASE_NOTES_NAME).write_text(
        SYNTHETIC_RELEASE_NOTES, encoding="utf-8", newline="\n",
    )


def test_verify_release_bundle_accepts_exact_four_assets(tmp_path):
    target = write_bundle(tmp_path)

    files = bundle.verify_release_bundle(target)

    assert tuple(files) == bundle.release_asset_names()
    checksum = files[bundle.CHECKSUM_NAME].read_bytes()
    assert b"\r" not in checksum and checksum.endswith(b"\n")


def test_verify_release_bundle_rejects_extra_asset(tmp_path):
    target = write_bundle(tmp_path)
    (target / "release-assets" / "extra.txt").write_text("drift", encoding="utf-8")

    with pytest.raises(bundle.ReleaseError) as error:
        bundle.verify_release_bundle(target)

    assert "exact GitHub release contract" in str(error.value)


def test_verify_release_bundle_rejects_noncanonical_release_notes(tmp_path):
    target = write_bundle(tmp_path)
    notes = target / "control" / bundle.RELEASE_NOTES_NAME
    notes.write_bytes(notes.read_bytes().replace(b"\n", b"\r\n"))

    with pytest.raises(bundle.ReleaseError) as error:
        bundle.verify_release_bundle(target)

    assert "LF-only" in str(error.value)


def test_verify_release_bundle_rejects_duplicate_checksum_name(tmp_path):
    target = write_bundle(tmp_path)
    checksum = target / "release-assets" / bundle.CHECKSUM_NAME
    row = checksum.read_text(encoding="ascii").splitlines()[0]
    checksum.write_text(f"{row}\n{row}\n", encoding="ascii", newline="\n")

    with pytest.raises(bundle.ReleaseError) as error:
        bundle.verify_release_bundle(target)

    assert "duplicate asset name" in str(error.value)


def test_verify_release_bundle_rejects_checksum_mismatch(tmp_path):
    target = write_bundle(tmp_path)
    wheel = target / "release-assets" / bundle.release_asset_names()[0]
    wheel.write_bytes(b"tampered\n")

    with pytest.raises(bundle.ReleaseError) as error:
        bundle.verify_release_bundle(target)

    assert "digest mismatch" in str(error.value)


def test_prepare_promoted_bundle_checks_version_and_archives(tmp_path, monkeypatch):
    project = tmp_path / "candidate"
    _write_candidate_source(project)
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel, sdist, _, _ = bundle.release_asset_names()
    (dist / wheel).write_bytes(b"wheel\n")
    (dist / sdist).write_bytes(b"sdist\n")
    verified: list[str] = []
    monkeypatch.setattr(
        "tools.release_artifacts.verify_wheel",
        lambda path, root: verified.append(path.name),
    )
    monkeypatch.setattr(
        "tools.release_artifacts.verify_sdist",
        lambda path, root: verified.append(path.name),
    )

    files = bundle.prepare_release_bundle(dist, project, tmp_path / "bundle")

    assert verified == [wheel, sdist]
    assert set(files) == set(bundle.release_asset_names())
    assert files[bundle.SCHEMA_NAME].read_bytes() == (
        project / "schemas" / bundle.SCHEMA_NAME
    ).read_bytes()
    assert (tmp_path / "bundle" / "control" / bundle.RELEASE_NOTES_NAME).read_text(
        encoding="utf-8",
    ) == SYNTHETIC_RELEASE_NOTES


def test_current_candidate_passes_source_gates_before_requiring_exact_dist(tmp_path):
    project = Path(__file__).resolve().parents[1]
    metadata = project.joinpath("pyproject.toml").read_text(encoding="utf-8")
    runtime = project.joinpath("src", "trust_meter", "__init__.py").read_text(encoding="utf-8")
    schema = json.loads(project.joinpath("schemas", bundle.SCHEMA_NAME).read_text(encoding="utf-8"))
    dist = tmp_path / "dist"
    dist.mkdir()

    with pytest.raises(bundle.ReleaseError) as error:
        bundle.prepare_release_bundle(dist, project, tmp_path / "release-bundle")

    assert 'version = "0.2.1"' in metadata
    assert '__version__ = "0.2.1"' in runtime
    assert schema["$id"] == bundle.SCHEMA_ID
    assert "promoted CI distribution" in str(error.value)


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("metadata", "locked to release version 0.2.1"),
        ("runtime", "candidate runtime version"),
        ("schema-id", "exact release asset URL"),
        ("schema-duplicate", "duplicate JSON key"),
    ],
)
def test_prepare_rejects_any_candidate_source_gate_drift(tmp_path, fault, message):
    project = tmp_path / "candidate"
    arguments: dict[str, str] = {}
    if fault == "metadata":
        arguments["metadata_version"] = "0.1.0"
    elif fault == "runtime":
        arguments["runtime_version"] = "0.1.0"
    elif fault == "schema-id":
        arguments["schema_text"] = '{"$id":"https://example.invalid/schema"}\n'
    else:
        arguments["schema_text"] = (
            f'{{"$id":"{bundle.SCHEMA_ID}","$id":"{bundle.SCHEMA_ID}"}}\n'
        )
    _write_candidate_source(project, **arguments)
    dist = tmp_path / "dist"
    dist.mkdir()

    with pytest.raises(bundle.ReleaseError) as error:
        bundle.prepare_release_bundle(dist, project, tmp_path / "release-bundle")

    assert message in str(error.value)
