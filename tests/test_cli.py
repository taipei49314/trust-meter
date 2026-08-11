"""Tests for the CLI entry point."""

import tempfile
from pathlib import Path

from trust_meter.cli import main, build_meter


def test_build_meter():
    meter = build_meter()
    assert len(meter._collectors) == 5


def test_main_clean_project():
    d = Path(tempfile.mkdtemp())
    (d / "src").mkdir()
    (d / "src" / "main.py").write_text(
        'def add(a, b):\n'
        '    """Add two numbers."""\n'
        '    return a + b\n'
    )
    (d / "tests").mkdir()
    (d / "tests" / "test_main.py").write_text(
        'def test_add():\n'
        '    assert add(1, 2) == 3\n'
    )
    # Should not raise
    result = main([str(d)])
    assert result == 0


def test_main_with_json_output():
    d = Path(tempfile.mkdtemp())
    (d / "src").mkdir()
    (d / "src" / "main.py").write_text('x = 1\n')
    result = main([str(d), "--json"])
    assert result == 1  # no test for main


def test_main_with_phase():
    d = Path(tempfile.mkdtemp())
    (d / "src").mkdir()
    (d / "src" / "main.py").write_text('x = 1\n')
    result = main([str(d), "--phase", "Phase 0"])
    assert result == 1


def test_main_nonexistent_dir():
    result = main(["/nonexistent/path/that/does/not/exist"])
    assert result == 1


def test_main_strict_mode():
    d = Path(tempfile.mkdtemp())
    (d / "src").mkdir()
    (d / "src" / "main.py").write_text('x = 1\n')
    result = main([str(d), "--strict"])
    assert result == 1  # no tests = evidence fails


def test_main_output_file():
    d = Path(tempfile.mkdtemp())
    (d / "src").mkdir()
    (d / "src" / "main.py").write_text('x = 1\n')
    out = d / "report.md"
    result = main([str(d), "--output", str(out)])
    assert out.exists()
    content = out.read_text()
    assert "Trust Report" in content
