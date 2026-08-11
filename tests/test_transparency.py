"""Tests for the transparency metric."""

import tempfile
from pathlib import Path

from trust_meter.metrics.transparency import collect_transparency


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_well_documented():
    d = _make_project({
        "src/main.py": (
            'def add(a, b):\n'
            '    """Add two numbers."""\n'
            '    return a + b\n'
        ),
    })
    result = collect_transparency(d)
    assert result.passed is True
    assert result.score == 100.0


def test_missing_docstring():
    d = _make_project({
        "src/main.py": "def add(a, b):\n    return a + b\n",
    })
    result = collect_transparency(d)
    assert result.passed is False
    assert any("missing docstring" in e for e in result.evidence)


def test_class_missing_docstring():
    d = _make_project({
        "src/main.py": "class Foo:\n    pass\n",
    })
    result = collect_transparency(d)
    assert result.passed is False
    assert any("Foo" in e and "missing" in e for e in result.evidence)


def test_private_function_skipped():
    d = _make_project({
        "src/main.py": "def _helper():\n    pass\n",
    })
    result = collect_transparency(d)
    assert result.passed is True


def test_todo_comment():
    d = _make_project({
        "src/main.py": (
            'def add(a, b):\n'
            '    """Add."""\n'
            '    # TODO: optimize\n'
            '    return a + b\n'
        ),
    })
    result = collect_transparency(d)
    # TODO in comments is flagged but doesn't fail the metric by itself
    assert any("TODO" in e for e in result.evidence)


def test_empty_project():
    d = _make_project({})
    result = collect_transparency(d)
    assert result.score == 100.0
    assert result.passed is True


def test_oversized_function():
    lines = ["def big():\n"] + ["    x = 1\n"] * 60
    d = _make_project({
        "src/main.py": "".join(lines),
    })
    result = collect_transparency(d)
    assert result.passed is False
    assert any("exceeds" in e for e in result.evidence)


def test_oversized_file():
    lines = ["# line\n"] * 600
    d = _make_project({
        "src/big.py": "".join(lines),
    })
    result = collect_transparency(d)
    assert any("exceeds" in e for e in result.evidence)
