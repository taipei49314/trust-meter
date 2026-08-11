"""Tests for the evidence metric."""

import tempfile
from pathlib import Path

from trust_meter.metrics.evidence import collect_evidence


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_fully_tested():
    d = _make_project({
        "src/calculator.py": "def add(a, b):\n    return a + b\n",
        "tests/test_calculator.py": (
            "from src.calculator import add\n"
            "def test_add():\n"
            "    assert add(1, 2) == 3\n"
        ),
    })
    result = collect_evidence(d)
    assert result.passed is True
    assert result.score == 100.0


def test_missing_test():
    d = _make_project({
        "src/calculator.py": "def add(a, b):\n    return a + b\n",
    })
    result = collect_evidence(d)
    assert result.passed is False
    assert any("calculator" in e for e in result.evidence)


def test_empty_test_function():
    d = _make_project({
        "src/calculator.py": "def add(a, b):\n    return a + b\n",
        "tests/test_calculator.py": (
            "def test_add():\n"
            "    pass\n"
        ),
    })
    result = collect_evidence(d)
    assert result.passed is False
    assert any("empty" in e.lower() for e in result.evidence + [result.details])


def test_no_source_modules():
    d = _make_project({
        "__init__.py": "",
    })
    result = collect_evidence(d)
    assert result.passed is True
    assert result.score == 100.0


def test_multiple_modules_partial_coverage():
    d = _make_project({
        "src/add.py": "def add(a, b):\n    return a + b\n",
        "src/sub.py": "def sub(a, b):\n    return a - b\n",
        "tests/test_add.py": "def test_add():\n    assert 1 + 1 == 2\n",
    })
    result = collect_evidence(d)
    assert result.passed is False
    assert any("sub" in e for e in result.evidence)


def test_test_with_assertions():
    d = _make_project({
        "src/calc.py": "def add(a, b):\n    return a + b\n",
        "tests/test_calc.py": (
            "def test_add():\n"
            "    assert add(1, 2) == 3\n"
            "    assert add(0, 0) == 0\n"
            "    assert add(-1, 1) == 0\n"
        ),
    })
    result = collect_evidence(d)
    assert result.passed is True
    assert "assertions" in result.details
