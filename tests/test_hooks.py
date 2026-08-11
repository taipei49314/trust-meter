"""Tests for the git hooks module."""

import tempfile
from pathlib import Path

from trust_meter.hooks import install_hook, uninstall_hook, is_installed, HOOK_SCRIPT


def _make_repo() -> Path:
    d = Path(tempfile.mkdtemp())
    (d / ".git" / "hooks").mkdir(parents=True)
    return d


def test_install_hook():
    d = _make_repo()
    path = install_hook(d)
    assert path.exists()
    assert "trust-meter" in path.read_text()


def test_install_hook_creates_dir():
    d = Path(tempfile.mkdtemp())
    # No .git/hooks dir
    path = install_hook(d)
    assert path.exists()


def test_is_installed_true():
    d = _make_repo()
    install_hook(d)
    assert is_installed(d) is True


def test_is_installed_false():
    d = _make_repo()
    assert is_installed(d) is False


def test_is_installed_other_hook():
    d = _make_repo()
    hook_path = d / ".git" / "hooks" / "pre-commit"
    hook_path.write_text("#!/bin/sh\necho hello\n")
    assert is_installed(d) is False


def test_uninstall_hook():
    d = _make_repo()
    install_hook(d)
    assert uninstall_hook(d) is True
    assert not (d / ".git" / "hooks" / "pre-commit").exists()


def test_uninstall_hook_not_found():
    d = _make_repo()
    assert uninstall_hook(d) is False


def test_uninstall_hook_preserves_other():
    d = _make_repo()
    hook_path = d / ".git" / "hooks" / "pre-commit"
    hook_path.write_text("#!/bin/sh\necho hello\n")
    assert uninstall_hook(d) is False
    assert hook_path.exists()


def test_hook_script_contains_strict():
    assert "--strict" in HOOK_SCRIPT


def test_hook_script_contains_skip_hint():
    assert "--no-verify" in HOOK_SCRIPT


def test_install_overwrites():
    d = _make_repo()
    install_hook(d)
    install_hook(d)  # Should not fail
    assert is_installed(d) is True
