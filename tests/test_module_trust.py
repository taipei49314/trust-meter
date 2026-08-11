"""Tests for the module-level trust module."""

import json
import tempfile
from pathlib import Path

from trust_meter.module_trust import (
    analyze_modules, modules_summary, modules_to_json,
    modules_to_markdown, ModuleScore,
)


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_analyze_well_tested():
    d = _make_project({
        "src/calc.py": 'def add(a, b):\n    """Add."""\n    return a + b\n',
        "tests/test_calc.py": "def test_add():\n    assert add(1, 2) == 3\n",
    })
    modules = analyze_modules(d)
    assert len(modules) == 1
    assert modules[0].name == "calc"
    assert modules[0].has_test is True
    assert modules[0].has_docstrings is True
    assert modules[0].score == 100.0
    assert modules[0].passed is True


def test_analyze_no_test():
    d = _make_project({
        "src/calc.py": 'def add(a, b):\n    """Add."""\n    return a + b\n',
    })
    modules = analyze_modules(d)
    assert modules[0].has_test is False
    assert modules[0].score == 70.0
    assert modules[0].passed is False


def test_analyze_no_docstring():
    d = _make_project({
        "src/calc.py": "def add(a, b):\n    return a + b\n",
        "tests/test_calc.py": "def test_add():\n    assert add(1, 2) == 3\n",
    })
    modules = analyze_modules(d)
    assert modules[0].has_docstrings is False
    assert modules[0].score == 85.0


def test_analyze_oversized_function():
    lines = ["def big():\n"] + ["    x = 1\n"] * 60
    d = _make_project({
        "src/big.py": "".join(lines),
        "tests/test_big.py": "def test_big():\n    pass\n",
    })
    modules = analyze_modules(d)
    assert any("exceeds" in i for i in modules[0].issues)


def test_analyze_multiple_modules():
    d = _make_project({
        "src/a.py": 'def foo():\n    """Doc."""\n    pass\n',
        "src/b.py": "def bar():\n    pass\n",
        "tests/test_a.py": "def test_foo():\n    pass\n",
    })
    modules = analyze_modules(d)
    assert len(modules) == 2
    names = {m.name for m in modules}
    assert "a" in names
    assert "b" in names


def test_analyze_skips_init():
    d = _make_project({
        "src/__init__.py": "",
        "src/main.py": "x = 1\n",
    })
    modules = analyze_modules(d)
    assert len(modules) == 1
    assert modules[0].name == "main"


def test_analyze_skips_test_files():
    d = _make_project({
        "tests/test_main.py": "def test_x():\n    pass\n",
        "src/main.py": "x = 1\n",
    })
    modules = analyze_modules(d)
    assert len(modules) == 1
    assert modules[0].name == "main"


def test_analyze_empty():
    d = _make_project({})
    modules = analyze_modules(d)
    assert len(modules) == 0


def test_module_score_properties():
    m = ModuleScore("test", "test.py", 90, True, True, 5, 30, 3, [])
    assert m.passed is True

    m2 = ModuleScore("test", "test.py", 90, False, True, 5, 30, 3, [])
    assert m2.passed is False  # no test

    m3 = ModuleScore("test", "test.py", 50, True, True, 5, 30, 3, [])
    assert m3.passed is False  # score < 70


def test_module_score_to_dict():
    m = ModuleScore("calc", "src/calc.py", 100, True, True, 3, 20, 2, [])
    d = m.to_dict()
    assert d["name"] == "calc"
    assert d["score"] == 100.0
    assert d["passed"] is True


def test_modules_summary():
    modules = [
        ModuleScore("a", "a.py", 100, True, True, 5, 20, 2, []),
        ModuleScore("b", "b.py", 50, False, False, 3, 40, 5, ["issue"]),
    ]
    summary = modules_summary(modules)
    assert summary["count"] == 2
    assert summary["avg_score"] == 75.0
    assert summary["passed"] == 1
    assert summary["failed"] == 1


def test_modules_summary_empty():
    summary = modules_summary([])
    assert summary["count"] == 0


def test_modules_to_json():
    modules = [ModuleScore("a", "a.py", 100, True, True, 5, 20, 2, [])]
    j = modules_to_json(modules)
    data = json.loads(j)
    assert "modules" in data
    assert "summary" in data
    assert len(data["modules"]) == 1


def test_modules_to_markdown():
    modules = [
        ModuleScore("a", "a.py", 100, True, True, 5, 20, 2, []),
        ModuleScore("b", "b.py", 50, False, False, 3, 40, 5, ["no test"]),
    ]
    md = modules_to_markdown(modules)
    assert "Module Trust Scores" in md
    assert "a" in md
    assert "b" in md
    assert "no test" in md
    assert "Total" in md


def test_high_import_count():
    imports = "\n".join(f"import m{i}" for i in range(20))
    d = _make_project({
        "src/heavy.py": imports + "\nx = 1\n",
        "tests/test_heavy.py": "def test_x():\n    pass\n",
    })
    modules = analyze_modules(d)
    assert any("imports" in i for i in modules[0].issues)
