"""Tests for the complexity metric."""

import tempfile
from pathlib import Path

from trust_meter.metrics.complexity import collect_complexity, _function_complexity
import ast


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def _cc(code: str) -> int:
    """Get complexity of a function from code string."""
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return _function_complexity(node)
    return 0


def test_simple_function():
    assert _cc("def f():\n    pass\n") == 1


def test_if_branch():
    assert _cc("def f(x):\n    if x:\n        pass\n") == 2


def test_if_else():
    assert _cc("def f(x):\n    if x:\n        pass\n    else:\n        pass\n") == 2


def test_elif():
    assert _cc("def f(x):\n    if x:\n        pass\n    elif x:\n        pass\n") == 3


def test_for_loop():
    assert _cc("def f():\n    for i in range(10):\n        pass\n") == 2


def test_while_loop():
    assert _cc("def f():\n    while True:\n        pass\n") == 2


def test_try_except():
    assert _cc("def f():\n    try:\n        pass\n    except:\n        pass\n") == 3


def test_with_statement():
    assert _cc("def f():\n    with open('f') as fh:\n        pass\n") == 2


def test_bool_and():
    assert _cc("def f(a, b):\n    return a and b\n") == 2


def test_bool_or():
    assert _cc("def f(a, b):\n    return a or b\n") == 2


def test_chained_bool():
    assert _cc("def f(a, b, c):\n    return a and b and c\n") == 3


def test_nested_complexity():
    code = (
        "def f(x):\n"
        "    if x:\n"
        "        for i in range(10):\n"
        "            if i > 5:\n"
        "                pass\n"
    )
    assert _cc(code) == 4


def test_collect_complexity_clean():
    d = _make_project({
        "src/simple.py": "def add(a, b):\n    return a + b\n",
    })
    result = collect_complexity(d)
    assert result.passed is True
    assert result.score == 100.0


def test_collect_complexity_high():
    lines = ["def complex(x):\n"]
    for i in range(15):
        lines.append(f"    if x > {i}:\n        pass\n")
    d = _make_project({"src/complex.py": "".join(lines)})
    result = collect_complexity(d)
    assert result.passed is False
    assert len(result.evidence) >= 1


def test_collect_complexity_empty():
    d = _make_project({})
    result = collect_complexity(d)
    assert result.score == 100.0


def test_collect_complexity_skips_private():
    d = _make_project({
        "src/main.py": "def _private(x):\n    if x:\n        pass\n",
    })
    result = collect_complexity(d)
    # Private functions are skipped
    assert result.passed is True


def test_collect_complexity_details():
    d = _make_project({
        "src/main.py": "def add(a, b):\n    return a + b\n",
    })
    result = collect_complexity(d)
    assert "functions" in result.details
    assert "avg cc" in result.details
