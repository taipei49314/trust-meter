"""Verify Trust Meter wheel and sdist release contracts using the stdlib."""

from __future__ import annotations

import argparse
import ast
import base64
import csv
import hashlib
import io
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath


SCHEMA_RELATIVE_PATH = "schemas/trust-meter-measure-v1.schema.json"
WHEEL_SCHEMA_PATH = "trust_meter/schemas/trust-meter-measure-v1.schema.json"
SDIST_ALWAYS_ALLOWED = {".gitignore", "LICENSE", "README.md", "pyproject.toml"}


class VerificationError(ValueError):
    """Report a closed release-artifact contract violation."""


@dataclass(frozen=True)
class ProjectContract:
    """Canonical package metadata and repository-owned release bytes."""

    name: str
    version: str
    description: str
    requires_python: str
    license_expression: str
    license_bytes: bytes
    schema_bytes: bytes
    pyproject_bytes: bytes
    source_python: dict[str, bytes]

    @property
    def archive_stem(self) -> str:
        """Return the normalized distribution filename stem."""
        return re.sub(r"[-_.]+", "_", self.name)

    @property
    def dist_info(self) -> str:
        """Return the exact wheel metadata directory name."""
        return f"{self.archive_stem}-{self.version}.dist-info"

    @property
    def sdist_root(self) -> str:
        """Return the exact source-distribution root directory."""
        return f"{self.archive_stem}-{self.version}"


@dataclass(frozen=True)
class _SdistContents:
    root: str
    files: dict[str, bytes]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _load_contract(project_root: Path) -> ProjectContract:
    pyproject_path = project_root / "pyproject.toml"
    pyproject_bytes = pyproject_path.read_bytes()
    project = tomllib.loads(pyproject_bytes.decode("utf-8"))["project"]
    license_files = project.get("license-files")
    _require(license_files == ["LICENSE"], "project.license-files must be ['LICENSE']")
    source_root = project_root / "src" / "trust_meter"
    source_python = {
        path.relative_to(source_root).as_posix(): path.read_bytes()
        for path in sorted(source_root.rglob("*.py"))
        if "__pycache__" not in path.parts
    }
    _require("__init__.py" in source_python, "repository package initializer is missing")
    return ProjectContract(
        name=project["name"],
        version=project["version"],
        description=project["description"],
        requires_python=project["requires-python"],
        license_expression=project["license"],
        license_bytes=(project_root / "LICENSE").read_bytes(),
        schema_bytes=(project_root / SCHEMA_RELATIVE_PATH).read_bytes(),
        pyproject_bytes=pyproject_bytes,
        source_python=source_python,
    )


def _safe_member_name(raw_name: str) -> str:
    _require(bool(raw_name), "archive contains an empty member name")
    _require("\\" not in raw_name, f"archive member uses a backslash: {raw_name!r}")
    _require("\x00" not in raw_name, "archive member contains NUL")
    candidate = raw_name[:-1] if raw_name.endswith("/") else raw_name
    _require(bool(candidate), f"archive member is absolute: {raw_name!r}")
    path = PurePosixPath(candidate)
    _require(not path.is_absolute(), f"archive member is absolute: {raw_name!r}")
    _require(path.parts[0] not in {".", ".."}, f"unsafe archive member: {raw_name!r}")
    _require(".." not in path.parts, f"unsafe archive member: {raw_name!r}")
    _require(":" not in path.parts[0], f"drive-qualified archive member: {raw_name!r}")
    _require(candidate == path.as_posix(), f"non-canonical archive member: {raw_name!r}")
    return path.as_posix()


def _read_wheel(wheel_path: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    with zipfile.ZipFile(wheel_path) as archive:
        for info in archive.infolist():
            name = _safe_member_name(info.filename)
            _require(name not in seen, f"duplicate wheel member: {name}")
            seen.add(name)
            mode = info.external_attr >> 16
            _require(not stat.S_ISLNK(mode), f"wheel member is a symlink: {name}")
            _require(not (info.flag_bits & 1), f"wheel member is encrypted: {name}")
            if not info.is_dir():
                files[name] = archive.read(info)
    return files


def _record_rows(record_bytes: bytes) -> dict[str, tuple[str, str]]:
    try:
        text = record_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise VerificationError("wheel RECORD is not UTF-8") from error
    rows: dict[str, tuple[str, str]] = {}
    for row in csv.reader(io.StringIO(text, newline="")):
        _require(len(row) == 3, "wheel RECORD row must have exactly three fields")
        name = _safe_member_name(row[0])
        _require(name not in rows, f"duplicate wheel RECORD row: {name}")
        rows[name] = (row[1], row[2])
    return rows


def _record_digest(data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return f"sha256={digest.decode('ascii')}"


def _verify_record(files: dict[str, bytes], record_path: str) -> None:
    _require(record_path in files, "wheel is missing RECORD")
    rows = _record_rows(files[record_path])
    _require(set(rows) == set(files), "wheel RECORD paths do not match archive files")
    for name, data in files.items():
        digest, size = rows[name]
        if name == record_path:
            _require((digest, size) == ("", ""), "RECORD must not hash itself")
            continue
        _require(digest == _record_digest(data), f"RECORD hash mismatch: {name}")
        _require(size == str(len(data)), f"RECORD size mismatch: {name}")


def _metadata_values(raw: bytes, contract: ProjectContract, label: str) -> None:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    expected = {
        "Metadata-Version": "2.4",
        "Name": contract.name,
        "Version": contract.version,
        "Summary": contract.description,
        "Requires-Python": contract.requires_python,
        "License-Expression": contract.license_expression,
    }
    for key, value in expected.items():
        _require(message.get_all(key, []) == [value], f"{label} has unexpected {key}")
    _require(message.get_all("License-File", []) == ["LICENSE"],
             f"{label} must declare exactly License-File: LICENSE")
    _require(message.get_all("Requires-Dist", []) == [],
             f"{label} must not declare runtime dependencies")
    _require(message.get_all("Provides-Extra", []) == [],
             f"{label} must not declare package extras")
    allowed = set(expected) | {"License-File"}
    _require(set(message.keys()) == allowed,
             f"{label} declares fields outside the exact metadata contract")
    _require(message.get_payload() == "", f"{label} must not contain a metadata body")


def _wheel_descriptor_values(raw: bytes) -> None:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    expected = {
        "Wheel-Version": "1.0",
        "Generator": "hatchling 1.27.0",
        "Root-Is-Purelib": "true",
    }
    for key, value in expected.items():
        _require(message.get_all(key, []) == [value], f"wheel has unexpected {key}")
    _require(message.get_all("Tag", []) == ["py3-none-any"],
             "wheel must declare exactly the py3-none-any tag")
    allowed = set(expected) | {"Tag"}
    _require(set(message.keys()) == allowed,
             "wheel declares fields outside the exact WHEEL contract")
    _require(message.get_payload() == "", "wheel WHEEL metadata must not contain a body")


def _verify_runtime_version(raw: bytes, contract: ProjectContract, label: str) -> None:
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, UnicodeError) as error:
        raise VerificationError(f"{label} package initializer is not valid UTF-8 Python") from error
    versions = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "__version__":
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                versions.append(node.value.value)
    _require(versions == [contract.version],
             f"{label} runtime version does not match project metadata")


def _verify_source_bytes(
    files: dict[str, bytes], contract: ProjectContract, prefix: str, label: str,
) -> None:
    for relative, expected in contract.source_python.items():
        path = f"{prefix}/{relative}"
        _require(files.get(path) == expected,
                 f"{label} source does not match the repository: {path}")


def _verify_wheel_member_set(files: dict[str, bytes], contract: ProjectContract) -> None:
    package_files = {f"trust_meter/{name}" for name in contract.source_python}
    metadata_files = {
        f"{contract.dist_info}/{name}"
        for name in ("METADATA", "WHEEL", "entry_points.txt", "licenses/LICENSE", "RECORD")
    }
    expected = package_files | metadata_files | {WHEEL_SCHEMA_PATH}
    _require(set(files) == expected, "wheel members do not match the exact release contract")


def verify_wheel(wheel_path: Path, project_root: Path) -> None:
    """Verify paths, RECORD, metadata, license, schema, and version in a wheel."""
    contract = _load_contract(project_root)
    expected_name = f"{contract.archive_stem}-{contract.version}-py3-none-any.whl"
    _require(wheel_path.name == expected_name, "wheel filename is not canonical")
    files = _read_wheel(wheel_path)
    record_path = f"{contract.dist_info}/RECORD"
    _verify_record(files, record_path)
    metadata_path = f"{contract.dist_info}/METADATA"
    license_path = f"{contract.dist_info}/licenses/LICENSE"
    _require(metadata_path in files, "wheel is missing METADATA")
    _metadata_values(files[metadata_path], contract, "wheel METADATA")
    wheel_path = f"{contract.dist_info}/WHEEL"
    entry_points_path = f"{contract.dist_info}/entry_points.txt"
    _require(wheel_path in files, "wheel is missing WHEEL metadata")
    _wheel_descriptor_values(files[wheel_path])
    expected_entry_points = b"[console_scripts]\ntrust-meter = trust_meter.cli:main\n"
    _require(files.get(entry_points_path) == expected_entry_points,
             "wheel console entry point is not canonical")
    _require(files.get(license_path) == contract.license_bytes,
             "wheel LICENSE does not match repository LICENSE")
    _require(files.get(WHEEL_SCHEMA_PATH) == contract.schema_bytes,
             "wheel schema does not match the canonical root schema")
    _verify_source_bytes(files, contract, "trust_meter", "wheel")
    init_path = "trust_meter/__init__.py"
    _require(init_path in files, "wheel is missing trust_meter/__init__.py")
    _verify_runtime_version(files[init_path], contract, "wheel")
    _verify_wheel_member_set(files, contract)


def _read_sdist(sdist_path: Path, contract: ProjectContract) -> _SdistContents:
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    with tarfile.open(sdist_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            name = _safe_member_name(member.name)
            _require(name not in seen, f"duplicate sdist member: {name}")
            seen.add(name)
            parts = PurePosixPath(name).parts
            _require(parts[0] == contract.sdist_root, "sdist has an unexpected root")
            if member.isdir():
                continue
            _require(member.isfile(), f"sdist member is not a regular file: {name}")
            source = archive.extractfile(member)
            _require(source is not None, f"cannot read sdist member: {name}")
            relative = PurePosixPath(*parts[1:]).as_posix()
            _require(relative != ".", "sdist root must be a directory")
            files[relative] = source.read()
    return _SdistContents(contract.sdist_root, files)


def _verify_sdist_allowlist(files: dict[str, bytes], contract: ProjectContract) -> None:
    generated = {"PKG-INFO"}
    explicit = SDIST_ALWAYS_ALLOWED | {SCHEMA_RELATIVE_PATH}
    for name in files:
        allowed = name in generated or name in explicit or name.startswith("src/trust_meter/")
        _require(allowed, f"sdist member is outside the explicit allowlist: {name}")
        _require(Path(name).name not in {"trust-report.html", "trust-report.md"},
                 f"tracked trust report leaked into sdist: {name}")
    source_files = {f"src/trust_meter/{name}" for name in contract.source_python}
    expected = generated | explicit | source_files
    _require(set(files) == expected, "sdist members do not match the exact allowlist")


def verify_sdist(sdist_path: Path, project_root: Path) -> None:
    """Verify safe members, metadata, license, schema, and allowlist in an sdist."""
    contract = _load_contract(project_root)
    expected_name = f"{contract.archive_stem}-{contract.version}.tar.gz"
    _require(sdist_path.name == expected_name, "sdist filename is not canonical")
    contents = _read_sdist(sdist_path, contract)
    files = contents.files
    _verify_sdist_allowlist(files, contract)
    _require(files.get("pyproject.toml") == contract.pyproject_bytes,
             "sdist pyproject.toml does not match the repository")
    _require(files.get("LICENSE") == contract.license_bytes,
             "sdist LICENSE does not match the repository LICENSE")
    _require(files.get(SCHEMA_RELATIVE_PATH) == contract.schema_bytes,
             "sdist schema does not match the canonical root schema")
    _verify_source_bytes(files, contract, "src/trust_meter", "sdist")
    _require("PKG-INFO" in files, "sdist is missing PKG-INFO")
    _metadata_values(files["PKG-INFO"], contract, "sdist PKG-INFO")
    init_path = "src/trust_meter/__init__.py"
    _require(init_path in files, "sdist is missing the package initializer")
    _verify_runtime_version(files[init_path], contract, "sdist")


def _extract_sdist(contents: _SdistContents, destination: Path) -> Path:
    source_root = destination / contents.root
    for relative, data in sorted(contents.files.items()):
        output = source_root / PurePosixPath(relative)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
    return source_root


def _venv_python(environment: Path) -> Path:
    if sys.platform == "win32":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _run_checked(command: list[str], label: str) -> None:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        raise VerificationError(f"{label} failed ({result.returncode}): {detail}")


def rebuild_sdist(
    sdist_path: Path,
    project_root: Path,
    wheelhouse: Path,
    build_requirements: Path,
) -> None:
    """Rebuild an sdist wheel with a fresh, hash-locked, index-free backend."""
    contract = _load_contract(project_root)
    contents = _read_sdist(sdist_path, contract)
    with tempfile.TemporaryDirectory(prefix="trust-meter-rebuild-") as temporary:
        temp_root = Path(temporary)
        source_root = _extract_sdist(contents, temp_root / "source")
        environment = temp_root / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = _venv_python(environment)
        install = [
            str(python), "-m", "pip", "--isolated", "install", "--no-index",
            "--find-links", str(wheelhouse.resolve()), "--only-binary=:all:",
            "--require-hashes", "-r", str(build_requirements.resolve()),
        ]
        _run_checked(install, "offline build dependency installation")
        output = temp_root / "rebuilt"
        build = [
            str(python), "-m", "build", "--no-isolation", "--wheel",
            "--outdir", str(output), str(source_root),
        ]
        _run_checked(build, "offline sdist wheel rebuild")
        wheels = sorted(output.glob("*.whl"))
        _require(len(wheels) == 1, "sdist rebuild did not produce exactly one wheel")
        verify_wheel(wheels[0], project_root)


def _single_artifact(dist_dir: Path, pattern: str, label: str) -> Path:
    matches = sorted(dist_dir.glob(pattern))
    _require(len(matches) == 1, f"expected exactly one {label} in {dist_dir}")
    return matches[0]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--rebuild-sdist", action="store_true")
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--build-requirements", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the closed release-artifact verification command."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.rebuild_sdist and not (args.wheelhouse and args.build_requirements):
        parser.error("--rebuild-sdist requires --wheelhouse and --build-requirements")
    try:
        wheel = _single_artifact(args.dist_dir, "*.whl", "wheel")
        sdist = _single_artifact(args.dist_dir, "*.tar.gz", "sdist")
        verify_wheel(wheel, args.project_root)
        verify_sdist(sdist, args.project_root)
        if args.rebuild_sdist:
            rebuild_sdist(
                sdist, args.project_root, args.wheelhouse, args.build_requirements,
            )
    except (
        OSError,
        KeyError,
        SyntaxError,
        UnicodeError,
        ValueError,
        csv.Error,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as error:
        print(f"release artifact verification failed: {error}", file=sys.stderr)
        return 1
    print(f"verified wheel: {wheel.name}")
    print(f"verified sdist: {sdist.name}")
    if args.rebuild_sdist:
        print("verified offline hash-locked sdist wheel rebuild")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
