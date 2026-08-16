"""Tests for the closed release archive verifier."""

from __future__ import annotations

import base64
import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from tools.release_artifacts import VerificationError, verify_sdist, verify_wheel


VERSION = "0.2.1"
DIST_INFO = f"trust_meter-{VERSION}.dist-info"
SCHEMA_PATH = "schemas/trust-meter-measure-v1.schema.json"
WHEEL_SCHEMA_PATH = "trust_meter/schemas/trust-meter-measure-v1.schema.json"


def _metadata(requires_python: str = ">=3.11") -> bytes:
    return (
        "Metadata-Version: 2.4\n"
        "Name: trust-meter\n"
        f"Version: {VERSION}\n"
        "Summary: Measure before you trust. Deterministic, local-first, "
        "evidence-backed trust scoring.\n"
        f"Requires-Python: {requires_python}\n"
        "License-Expression: MIT\n"
        "License-File: LICENSE\n\n"
    ).encode("utf-8")


def _write_project(root: Path) -> None:
    (root / "schemas").mkdir()
    package = root / "src" / "trust_meter"
    package.mkdir(parents=True)
    (root / "LICENSE").write_text("test license\n", encoding="utf-8")
    (root / SCHEMA_PATH).write_text('{"title":"canonical"}\n', encoding="utf-8")
    (package / "__init__.py").write_text(
        '__version__ = "0.2.1"\n', encoding="utf-8",
    )
    (package / "cli.py").write_text('"""CLI."""\n', encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "trust-meter"\n'
        f'version = "{VERSION}"\n'
        'description = "Measure before you trust. Deterministic, local-first, '
        'evidence-backed trust scoring."\n'
        'requires-python = ">=3.11"\n'
        'license = "MIT"\n'
        'license-files = ["LICENSE"]\n',
        encoding="utf-8",
    )


def _digest(data: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"sha256={encoded.decode('ascii')}"


def _wheel_files(
    project: Path,
    requires_python: str = ">=3.11",
    duplicate_metadata: bool = False,
    duplicate_wheel_header: bool = False,
    runtime_dependency: bool = False,
) -> dict[str, bytes]:
    metadata = _metadata(requires_python)
    if duplicate_metadata:
        metadata = metadata.replace(b"\n\n", b"\nName: contradictory-name\n\n")
    if runtime_dependency:
        metadata = metadata.replace(b"\n\n", b"\nRequires-Dist: injected-package\n\n")
    wheel_descriptor = (
        b"Wheel-Version: 1.0\n"
        b"Generator: hatchling 1.27.0\n"
        b"Root-Is-Purelib: true\n"
        b"Tag: py3-none-any\n"
    )
    if duplicate_wheel_header:
        wheel_descriptor += b"Generator: contradictory-generator\n"
    return {
        "trust_meter/__init__.py": (project / "src/trust_meter/__init__.py").read_bytes(),
        "trust_meter/cli.py": (project / "src/trust_meter/cli.py").read_bytes(),
        WHEEL_SCHEMA_PATH: (project / SCHEMA_PATH).read_bytes(),
        f"{DIST_INFO}/licenses/LICENSE": (project / "LICENSE").read_bytes(),
        f"{DIST_INFO}/METADATA": metadata,
        f"{DIST_INFO}/WHEEL": wheel_descriptor,
        f"{DIST_INFO}/entry_points.txt": (
            b"[console_scripts]\ntrust-meter = trust_meter.cli:main\n"
        ),
    }


def _write_wheel(
    project: Path,
    *,
    extra: tuple[str, bytes] | None = None,
    omit_license: bool = False,
    tamper_schema: bool = False,
    requires_python: str = ">=3.11",
    duplicate_metadata: bool = False,
    duplicate_wheel_header: bool = False,
    runtime_dependency: bool = False,
) -> Path:
    files = _wheel_files(
        project,
        requires_python,
        duplicate_metadata,
        duplicate_wheel_header,
        runtime_dependency,
    )
    if omit_license:
        del files[f"{DIST_INFO}/licenses/LICENSE"]
    if extra:
        files[extra[0]] = extra[1]
    record_path = f"{DIST_INFO}/RECORD"
    record = [f"{name},{_digest(data)},{len(data)}" for name, data in sorted(files.items())]
    record.append(f"{record_path},,")
    files[record_path] = ("\n".join(record) + "\n").encode("utf-8")
    if tamper_schema:
        files[WHEEL_SCHEMA_PATH] = b"tampered after RECORD\n"
    wheel = project / f"trust_meter-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    return wheel


def _sdist_files(
    project: Path,
    duplicate_pkg_info: bool = False,
    provides_extra: bool = False,
) -> dict[str, bytes]:
    pkg_info = _metadata()
    if duplicate_pkg_info:
        pkg_info = pkg_info.replace(b"\n\n", b"\nVersion: 9.9.9\n\n")
    if provides_extra:
        pkg_info = pkg_info.replace(b"\n\n", b"\nProvides-Extra: injected\n\n")
    return {
        ".gitignore": b"dist/\n",
        "LICENSE": (project / "LICENSE").read_bytes(),
        "README.md": b"# trust-meter\n",
        "pyproject.toml": (project / "pyproject.toml").read_bytes(),
        "PKG-INFO": pkg_info,
        SCHEMA_PATH: (project / SCHEMA_PATH).read_bytes(),
        "src/trust_meter/__init__.py": (
            project / "src/trust_meter/__init__.py"
        ).read_bytes(),
        "src/trust_meter/cli.py": (project / "src/trust_meter/cli.py").read_bytes(),
    }


def _write_sdist(
    project: Path,
    extra: tuple[str, bytes] | None = None,
    duplicate_pkg_info: bool = False,
    provides_extra: bool = False,
) -> Path:
    root = f"trust_meter-{VERSION}"
    files = _sdist_files(project, duplicate_pkg_info, provides_extra)
    if extra:
        files[extra[0]] = extra[1]
    sdist = project / f"{root}.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        for relative, data in sorted(files.items()):
            info = tarfile.TarInfo(f"{root}/{relative}")
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    return sdist


def test_verify_wheel_accepts_closed_canonical_archive(tmp_path):
    _write_project(tmp_path)
    wheel = _write_wheel(tmp_path)

    verify_wheel(wheel, tmp_path)

    assert wheel.is_file()


def test_verify_wheel_rejects_record_hash_mismatch(tmp_path):
    _write_project(tmp_path)
    wheel = _write_wheel(tmp_path, tamper_schema=True)

    with pytest.raises(VerificationError) as error:
        verify_wheel(wheel, tmp_path)

    assert "RECORD hash mismatch" in str(error.value)


def test_verify_wheel_rejects_path_traversal(tmp_path):
    _write_project(tmp_path)
    wheel = _write_wheel(tmp_path, extra=("../escape.py", b"escape\n"))

    with pytest.raises(VerificationError) as error:
        verify_wheel(wheel, tmp_path)

    assert "unsafe archive member" in str(error.value)


def test_verify_wheel_requires_license_and_schema_bytes(tmp_path):
    _write_project(tmp_path)
    wheel = _write_wheel(tmp_path, omit_license=True)

    with pytest.raises(VerificationError) as error:
        verify_wheel(wheel, tmp_path)

    assert "wheel LICENSE" in str(error.value)


def test_verify_wheel_requires_python_floor_metadata(tmp_path):
    _write_project(tmp_path)
    wheel = _write_wheel(tmp_path, requires_python=">=3.9")

    with pytest.raises(VerificationError) as error:
        verify_wheel(wheel, tmp_path)

    assert "unexpected Requires-Python" in str(error.value)


def test_verify_wheel_rejects_duplicate_metadata_singleton(tmp_path):
    _write_project(tmp_path)
    wheel = _write_wheel(tmp_path, duplicate_metadata=True)

    with pytest.raises(VerificationError) as error:
        verify_wheel(wheel, tmp_path)

    assert "unexpected Name" in str(error.value)


def test_verify_wheel_rejects_duplicate_wheel_singleton(tmp_path):
    _write_project(tmp_path)
    wheel = _write_wheel(tmp_path, duplicate_wheel_header=True)

    with pytest.raises(VerificationError) as error:
        verify_wheel(wheel, tmp_path)

    assert "unexpected Generator" in str(error.value)


def test_verify_wheel_rejects_injected_runtime_dependency(tmp_path):
    _write_project(tmp_path)
    wheel = _write_wheel(tmp_path, runtime_dependency=True)

    with pytest.raises(VerificationError) as error:
        verify_wheel(wheel, tmp_path)

    assert "must not declare runtime dependencies" in str(error.value)


def test_verify_sdist_accepts_explicit_allowlist(tmp_path):
    _write_project(tmp_path)
    sdist = _write_sdist(tmp_path)

    verify_sdist(sdist, tmp_path)

    assert sdist.is_file()


def test_verify_sdist_rejects_tracked_report(tmp_path):
    _write_project(tmp_path)
    sdist = _write_sdist(tmp_path, extra=("trust-report.md", b"stale report\n"))

    with pytest.raises(VerificationError) as error:
        verify_sdist(sdist, tmp_path)

    assert "outside the explicit allowlist" in str(error.value)


def test_verify_sdist_rejects_path_traversal(tmp_path):
    _write_project(tmp_path)
    sdist = _write_sdist(tmp_path, extra=("../escape.py", b"escape\n"))

    with pytest.raises(VerificationError) as error:
        verify_sdist(sdist, tmp_path)

    assert "unsafe archive member" in str(error.value)


def test_verify_sdist_rejects_duplicate_pkg_info_singleton(tmp_path):
    _write_project(tmp_path)
    sdist = _write_sdist(tmp_path, duplicate_pkg_info=True)

    with pytest.raises(VerificationError) as error:
        verify_sdist(sdist, tmp_path)

    assert "unexpected Version" in str(error.value)


def test_verify_sdist_rejects_injected_package_extra(tmp_path):
    _write_project(tmp_path)
    sdist = _write_sdist(tmp_path, provides_extra=True)

    with pytest.raises(VerificationError) as error:
        verify_sdist(sdist, tmp_path)

    assert "must not declare package extras" in str(error.value)
