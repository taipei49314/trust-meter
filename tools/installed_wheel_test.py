"""Install and exercise the canonical wheel from outside the repository."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path


class AcceptanceError(RuntimeError):
    """Report an installed-wheel acceptance contract violation."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceError(message)


def _clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def _run(command: list[str], cwd: Path, environment: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _install_wheel(wheel: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "pip",
        "--isolated",
        "install",
        "--no-index",
        "--no-deps",
        "--force-reinstall",
        str(wheel.resolve()),
    ]
    result = subprocess.run(command, check=False)
    _require(result.returncode == 0, "index-free wheel installation failed")


def _write_fixture(root: Path) -> Path:
    fixture = root / "fixture"
    source = fixture / "src" / "main.py"
    test = fixture / "tests" / "test_main.py"
    source.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    source.write_text(
        'def add(left, right):\n    """Add two values."""\n    return left + right\n',
        encoding="utf-8",
    )
    test.write_text(
        "def test_add():\n    assert 1 + 2 == 3\n",
        encoding="utf-8",
    )
    return fixture


def _verify_import_location(
    outside_root: Path,
    project_root: Path,
    environment: dict[str, str],
) -> None:
    code = "import pathlib, trust_meter; print(pathlib.Path(trust_meter.__file__).resolve())"
    result = _run([sys.executable, "-c", code], outside_root, environment)
    _require(result.returncode == 0, "installed package import failed")
    installed_path = Path(result.stdout.decode("utf-8").strip()).resolve()
    _require(not installed_path.is_relative_to(project_root.resolve()),
             "acceptance imported Trust Meter from the repository")


def _verify_machine_output(
    executable: str,
    fixture: Path,
    outside_root: Path,
    environment: dict[str, str],
) -> None:
    command = [
        executable,
        str(fixture),
        "--json-v1",
        "--no-config",
        "--threshold",
        "0",
        "--phase",
        "installed-asset",
    ]
    first = _run(command, outside_root, environment)
    second = _run(command, outside_root, environment)
    _require(first.returncode == second.returncode == 0, "machine fixture must exit zero")
    _require(first.stderr == second.stderr == b"", "machine fixture wrote diagnostics")
    _require(first.stdout == second.stdout, "machine JSON bytes are not deterministic")
    payload = json.loads(first.stdout)
    _require(payload["schema_version"] == "trust-meter.measure/v1",
             "installed wheel emitted the wrong schema version")
    _require(payload["authority_effect"] == "none",
             "installed wheel changed advisory authority")
    _require(payload["tool"]["version"] == "0.1.0",
             "installed wheel emitted the wrong version")


def _verify_config_error(
    executable: str,
    outside_root: Path,
    environment: dict[str, str],
) -> None:
    config = outside_root / "invalid.toml"
    config.write_text("[trust-meter]\nunknown = true\n", encoding="utf-8")
    command = [executable, str(outside_root), "--json-v1", "--config", str(config)]
    result = _run(command, outside_root, environment)
    _require(result.returncode == 2, "invalid exact config must exit two")
    _require(result.stdout == b"", "invalid exact config wrote stdout")
    _require(b"Error:" in result.stderr and b"unknown" in result.stderr,
             "invalid exact config did not report a bounded error")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Install one wheel and verify its machine interface outside the checkout."""
    args = _parser().parse_args(argv)
    wheels = sorted(args.dist_dir.glob("*.whl"))
    _require(len(wheels) == 1, "expected exactly one canonical wheel")
    _install_wheel(wheels[0])
    environment = _clean_environment()
    _require("PYTHONPATH" not in environment and "PYTHONHOME" not in environment,
             "Python path overrides were not cleared")
    script_name = "trust-meter.exe" if sys.platform == "win32" else "trust-meter"
    script_path = Path(sysconfig.get_path("scripts")) / script_name
    _require(script_path.is_file(), "wheel did not install the trust-meter command")
    executable = str(script_path)
    with tempfile.TemporaryDirectory(prefix="trust-meter-installed-") as temporary:
        outside_root = Path(temporary).resolve()
        _require(not outside_root.is_relative_to(args.project_root.resolve()),
                 "acceptance directory is inside the repository")
        _verify_import_location(outside_root, args.project_root, environment)
        version = _run([executable, "--version"], outside_root, environment)
        _require(version.returncode == 0, "installed --version failed")
        version_lines = version.stdout.decode("utf-8").splitlines()
        _require(version_lines == ["trust-meter 0.1.0"] and version.stderr == b"",
                 "installed --version output is not canonical")
        fixture = _write_fixture(outside_root)
        _verify_machine_output(executable, fixture, outside_root, environment)
        _verify_config_error(executable, outside_root, environment)
    print(f"installed wheel acceptance passed: {wheels[0].name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as error:
        print(f"installed wheel acceptance failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
