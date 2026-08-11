"""Tests for the self_audit script."""

from scripts.self_audit import main


def test_self_audit_runs():
    """Self-audit should run without crashing."""
    result = main()
    assert isinstance(result, int)
