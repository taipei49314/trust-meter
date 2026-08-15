"""Build and verify the exact Trust Meter GitHub release asset bundle."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import tomllib
import urllib.parse
from pathlib import Path


REPOSITORY = "taipei49314/trust-meter"
RELEASE_VERSION = "0.2.0"
RELEASE_TAG = f"v{RELEASE_VERSION}"
RELEASE_NAME = f"Trust Meter {RELEASE_TAG}"
HTTPS_SCHEME = "https"
GITHUB_WEB_HOST = "github.com"
DEFAULT_BRANCH = "master"
CI_WORKFLOW_PATH = ".github/workflows/trust.yml"
CI_ARTIFACT_NAME = "release-dist"
PREPARED_ARTIFACT_NAME = "trust-meter-v0.2.0-release-bundle"
SCHEMA_NAME = "trust-meter-measure-v1.schema.json"
SCHEMA_ID = urllib.parse.urlunsplit(
    (HTTPS_SCHEME, GITHUB_WEB_HOST,
     f"/{REPOSITORY}/releases/download/{RELEASE_TAG}/{SCHEMA_NAME}", "", "")
)
CHECKSUM_NAME = "SHA256SUMS.txt"
RELEASE_NOTES_NAME = "RELEASE_NOTES-v0.2.0.md"
CONTROL_SCRIPT_NAMES = ("github_release.py", "release_bundle.py", "release_promotion.py")
CONTROL_NAMES = (*CONTROL_SCRIPT_NAMES, RELEASE_NOTES_NAME)
GITHUB_API_HOST = "api.github.com"
GITHUB_UPLOAD_HOST = "uploads.github.com"
APPROVAL_VALUE = f"{REPOSITORY}:{RELEASE_TAG}:upload-draft"
HEX_SHA256 = re.compile(r"[0-9a-f]{64}")
FULL_GIT_SHA = re.compile(r"[0-9a-f]{40}")
VERSION_PART = re.compile(r"0|[1-9][0-9]*")


class ReleaseError(ValueError):
    """Report a closed release-contract violation."""


def require(condition: bool, message: str) -> None:
    """Raise the release error when a contract predicate is false."""
    if not condition:
        raise ReleaseError(message)


def github_origin(host: str) -> str:
    """Construct a strict GitHub HTTPS origin without a path."""
    require(host in {GITHUB_WEB_HOST, GITHUB_API_HOST, GITHUB_UPLOAD_HOST},
            "unexpected GitHub host")
    return urllib.parse.urlunsplit((HTTPS_SCHEME, host, "", "", ""))


def positive_integer(value: object, label: str) -> int:
    """Require a positive non-boolean integer."""
    require(isinstance(value, int) and not isinstance(value, bool) and value > 0,
            f"{label} must be a positive integer")
    return value


def parse_positive_integer(raw: str, label: str) -> int:
    """Parse a canonical positive decimal integer."""
    require(bool(raw) and raw.isascii() and raw.isdecimal(),
            f"{label} must contain only decimal digits")
    return positive_integer(int(raw), label)


def exact_version(raw: str) -> str:
    """Require canonical version 0.2.0, the sole target of this workflow."""
    parts = raw.split(".")
    require(
        len(parts) == 3 and all(VERSION_PART.fullmatch(part) for part in parts),
        "version must be a canonical X.Y.Z release version",
    )
    require(raw == RELEASE_VERSION,
            f"this workflow is locked to release version {RELEASE_VERSION}")
    return raw


def exact_sha(raw: str, label: str) -> str:
    """Require a full lowercase SHA-1 object identifier."""
    require(FULL_GIT_SHA.fullmatch(raw) is not None,
            f"{label} must be a full lowercase SHA-1 object ID")
    return raw


def sha256(data: bytes) -> str:
    """Return a lowercase SHA-256 digest."""
    return hashlib.sha256(data).hexdigest()


def exact_sha256(raw: str, label: str) -> str:
    """Require a bare lowercase SHA-256 digest."""
    require(HEX_SHA256.fullmatch(raw) is not None,
            f"{label} must be a lowercase SHA-256 digest")
    return raw


def regular_directory_files(directory: Path, label: str) -> dict[str, Path]:
    """Return only regular, non-symlink direct children of a real directory."""
    require(directory.is_dir() and not directory.is_symlink(),
            f"{label} must be a real directory")
    files: dict[str, Path] = {}
    for entry in directory.iterdir():
        require(entry.is_file() and not entry.is_symlink(),
                f"{label} contains a non-regular entry: {entry.name}")
        require(entry.name not in files, f"{label} contains a duplicate name")
        files[entry.name] = entry
    return files


def release_asset_names(version: str = RELEASE_VERSION) -> tuple[str, ...]:
    """Return the exact public GitHub release asset names."""
    exact_version(version)
    return (
        f"trust_meter-{version}-py3-none-any.whl",
        f"trust_meter-{version}.tar.gz",
        SCHEMA_NAME,
        CHECKSUM_NAME,
    )


def _payload_names(version: str) -> tuple[str, ...]:
    return tuple(sorted(name for name in release_asset_names(version) if name != CHECKSUM_NAME))


def _checksum_bytes(files: dict[str, Path], version: str) -> bytes:
    rows = [f"{sha256(files[name].read_bytes())}  {name}\n" for name in _payload_names(version)]
    return "".join(rows).encode("ascii")


def _verify_checksum_file(files: dict[str, Path], version: str) -> None:
    raw = files[CHECKSUM_NAME].read_bytes()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise ReleaseError(f"{CHECKSUM_NAME} must be ASCII") from error
    require("\r" not in text and text.endswith("\n"),
            f"{CHECKSUM_NAME} must be LF-terminated")
    rows: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        require(match is not None, f"{CHECKSUM_NAME} contains a non-canonical row")
        digest, name = match.groups()
        require(name not in rows, f"{CHECKSUM_NAME} contains a duplicate asset name")
        rows[name] = digest
    require(set(rows) == set(_payload_names(version)),
            f"{CHECKSUM_NAME} names do not match the exact payload")
    for name in _payload_names(version):
        require(rows[name] == sha256(files[name].read_bytes()),
                f"{CHECKSUM_NAME} digest mismatch: {name}")
    require(raw == _checksum_bytes(files, version),
            f"{CHECKSUM_NAME} rows are not in canonical sorted order")


def verify_release_assets(asset_dir: Path, version: str = RELEASE_VERSION) -> dict[str, Path]:
    """Verify the exact four release files and their checksum ledger."""
    version = exact_version(version)
    files = regular_directory_files(asset_dir, "release asset directory")
    require(set(files) == set(release_asset_names(version)),
            "release asset names do not match the exact GitHub release contract")
    _verify_checksum_file(files, version)
    return {name: files[name] for name in release_asset_names(version)}


def _project_version(project_root: Path) -> str:
    try:
        project = tomllib.loads(
            (project_root / "pyproject.toml").read_bytes().decode("utf-8")
        )["project"]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise ReleaseError("candidate pyproject.toml is not a valid project contract") from error
    require(project.get("name") == "trust-meter", "candidate project name must be trust-meter")
    version = project.get("version")
    require(isinstance(version, str), "candidate project version must be a string")
    return exact_version(version)


def _runtime_version(project_root: Path) -> str:
    initializer = project_root / "src" / "trust_meter" / "__init__.py"
    try:
        tree = ast.parse(initializer.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError) as error:
        raise ReleaseError("candidate package initializer is not valid UTF-8 Python") from error
    versions: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
            if (isinstance(target, ast.Name) and target.id == "__version__"
                    and isinstance(value, ast.Constant) and isinstance(value.value, str)):
                versions.append(value.value)
    require(versions == [RELEASE_VERSION],
            f"candidate runtime version must be exactly {RELEASE_VERSION}")
    return versions[0]


def exact_release_notes(raw: str) -> str:
    """Require one bounded canonical LF-only release-notes body."""
    require(0 < len(raw.encode("utf-8")) <= 64 * 1024,
            "release notes must be nonempty and at most 64 KiB")
    require(raw.endswith("\n") and "\r" not in raw and "\x00" not in raw,
            "release notes must be NUL-free, LF-only, and LF-terminated")
    return raw


def read_release_notes(path: Path) -> str:
    """Read one regular UTF-8 release-notes file without normalization."""
    require(path.is_file() and not path.is_symlink(),
            "release notes must be a regular file")
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ReleaseError("release notes must be readable UTF-8") from error
    require(text.encode("utf-8") == raw, "release notes UTF-8 bytes are not canonical")
    return exact_release_notes(text)


def _json_object_without_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, f"candidate schema contains duplicate JSON key: {key}")
        result[key] = value
    return result


def _candidate_schema_bytes(project_root: Path) -> bytes:
    """Bind the candidate schema bytes to the immutable release-asset URL."""
    path = project_root / "schemas" / SCHEMA_NAME
    require(path.is_file() and not path.is_symlink(), "candidate schema must be regular")
    try:
        raw = path.read_bytes()
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_json_object_without_duplicates,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseError("candidate schema must be valid UTF-8 JSON") from error
    require(isinstance(document, dict), "candidate schema root must be an object")
    require(document.get("$id") == SCHEMA_ID,
            "candidate schema $id must match the exact release asset URL")
    return raw


def _exclusive_write(path: Path, data: bytes) -> None:
    with path.open("xb") as output:
        output.write(data)


def verify_release_bundle(bundle_dir: Path, version: str = RELEASE_VERSION) -> dict[str, Path]:
    """Verify the exact Actions bundle without importing candidate code."""
    version = exact_version(version)
    require(bundle_dir.is_dir() and not bundle_dir.is_symlink(),
            "release bundle must be a real directory")
    entries = {entry.name: entry for entry in bundle_dir.iterdir()}
    require(set(entries) == {"control", "release-assets"},
            "release bundle top-level entries do not match the exact contract")
    require(all(path.is_dir() and not path.is_symlink() for path in entries.values()),
            "release bundle top-level entries must be real directories")
    control = regular_directory_files(entries["control"], "release control directory")
    require(set(control) == set(CONTROL_NAMES),
            "release control directory does not match the exact contract")
    read_release_notes(control[RELEASE_NOTES_NAME])
    return verify_release_assets(entries["release-assets"], version)


def prepare_release_bundle(
    dist_dir: Path, project_root: Path, bundle_dir: Path,
    version: str = RELEASE_VERSION,
) -> dict[str, Path]:
    """Verify a promoted CI distribution and prepare an exact Actions bundle."""
    version = exact_version(version)
    require(_project_version(project_root) == version, "candidate version mismatch")
    require(_runtime_version(project_root) == version, "candidate runtime version mismatch")
    schema_bytes = _candidate_schema_bytes(project_root)
    release_notes = read_release_notes(
        project_root / ".github" / RELEASE_NOTES_NAME,
    ).encode("utf-8")
    wheel_name, sdist_name, _, _ = release_asset_names(version)
    dist_files = regular_directory_files(dist_dir, "promoted CI distribution")
    require(set(dist_files) == {wheel_name, sdist_name},
            "promoted CI distribution must contain exactly one wheel and one sdist")
    try:
        from tools.release_artifacts import verify_sdist, verify_wheel
    except ModuleNotFoundError:
        from release_artifacts import verify_sdist, verify_wheel
    verify_wheel(dist_files[wheel_name], project_root)
    verify_sdist(dist_files[sdist_name], project_root)
    require(not bundle_dir.exists(), "release bundle directory must not already exist")
    assets, control = bundle_dir / "release-assets", bundle_dir / "control"
    assets.mkdir(parents=True)
    control.mkdir()
    for name in (wheel_name, sdist_name):
        _exclusive_write(assets / name, dist_files[name].read_bytes())
    _exclusive_write(assets / SCHEMA_NAME, schema_bytes)
    current = regular_directory_files(assets, "release asset directory")
    _exclusive_write(assets / CHECKSUM_NAME, _checksum_bytes(current, version))
    source_dir = Path(__file__).resolve().parent
    for name in CONTROL_SCRIPT_NAMES:
        _exclusive_write(control / name, (source_dir / name).read_bytes())
    _exclusive_write(control / RELEASE_NOTES_NAME, release_notes)
    verify_release_bundle(bundle_dir, version)
    return verify_release_assets(assets, version)
