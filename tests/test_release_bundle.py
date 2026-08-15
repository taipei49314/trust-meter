"""Tests for exact Trust Meter GitHub release bundle construction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools import release_bundle as bundle


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
    for name in bundle.CONTROL_NAMES:
        (control / name).write_text("# trusted release control\n", encoding="utf-8")
    return target


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
    package = project / "src" / "trust_meter"
    schema_dir = project / "schemas"
    package.mkdir(parents=True)
    schema_dir.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "trust-meter"\nversion = "0.2.0"\n', encoding="utf-8",
    )
    (package / "__init__.py").write_text('__version__ = "0.2.0"\n', encoding="utf-8")
    (schema_dir / bundle.SCHEMA_NAME).write_text("{}\n", encoding="utf-8")
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


def test_current_0_1_0_source_and_schema_remain_inert(tmp_path):
    project = Path(__file__).resolve().parents[1]
    metadata = project.joinpath("pyproject.toml").read_text(encoding="utf-8")
    runtime = project.joinpath("src", "trust_meter", "__init__.py").read_text(encoding="utf-8")
    schema = json.loads(project.joinpath("schemas", bundle.SCHEMA_NAME).read_text(encoding="utf-8"))
    dist = tmp_path / "dist"
    dist.mkdir()

    with pytest.raises(bundle.ReleaseError) as error:
        bundle.prepare_release_bundle(dist, project, tmp_path / "release-bundle")

    assert 'version = "0.1.0"' in metadata
    assert '__version__ = "0.1.0"' in runtime
    assert schema["$id"] == (
        "https://github.com/taipei49314/trust-meter/"
        "schemas/trust-meter-measure-v1.schema.json"
    )
    assert "locked to release version 0.2.0" in str(error.value)
