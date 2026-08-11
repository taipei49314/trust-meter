"""Tests for file-level trust."""

import json
import tempfile
from pathlib import Path

from trust_meter.file_trust import (
    analyze_files, files_summary, files_to_json, files_to_markdown, FileScore,
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
    files = analyze_files(d)
    assert len(files) == 2  # src + test
    src = next(f for f in files if f.path.endswith("calc.py") and "test" not in f.path)
    assert src.has_test is True
    assert src.score == 100.0


def test_analyze_no_test():
    d = _make_project({"src/calc.py": "x = 1\n"})
    files = analyze_files(d)
    assert files[0].has_test is False
    assert files[0].score < 100.0


def test_analyze_large_file():
    content = "\n".join(f"x{i} = {i}" for i in range(600))
    d = _make_project({"src/big.py": content + "\n"})
    files = analyze_files(d)
    assert any("lines" in i for i in files[0].issues)


def test_analyze_oversized_func():
    lines = ["def big():\n"] + ["    x = 1\n"] * 60
    d = _make_project({"src/big.py": "".join(lines)})
    files = analyze_files(d)
    assert any("exceeds" in i for i in files[0].issues)


def test_analyze_high_imports():
    imports = "\n".join(f"import m{i}" for i in range(20))
    d = _make_project({"src/heavy.py": imports + "\nx = 1\n"})
    files = analyze_files(d)
    assert any("imports" in i for i in files[0].issues)


def test_analyze_no_docstring():
    d = _make_project({
        "src/calc.py": "def add(a, b):\n    return a + b\n",
    })
    files = analyze_files(d)
    assert any("documented" in i for i in files[0].issues)


def test_analyze_empty():
    d = _make_project({})
    assert len(analyze_files(d)) == 0


def test_file_score_properties():
    f = FileScore("a.py", 90, 100, 5, 30, 3, 1.0, True, [])
    assert f.passed is True
    f2 = FileScore("b.py", 50, 100, 5, 30, 3, 1.0, False, [])
    assert f2.passed is False


def test_file_score_to_dict():
    f = FileScore("a.py", 100, 50, 3, 20, 2, 1.0, True, [])
    d = f.to_dict()
    assert d["path"] == "a.py"
    assert d["score"] == 100.0


def test_files_summary():
    files = [
        FileScore("a.py", 100, 50, 3, 20, 2, 1.0, True, []),
        FileScore("b.py", 50, 200, 10, 60, 8, 0.5, False, ["issue"]),
    ]
    s = files_summary(files)
    assert s["count"] == 2
    assert s["passed"] == 1
    assert s["failed"] == 1
    assert s["total_lines"] == 250


def test_files_to_json():
    files = [FileScore("a.py", 100, 50, 3, 20, 2, 1.0, True, [])]
    j = files_to_json(files)
    data = json.loads(j)
    assert "files" in data
    assert "summary" in data


def test_files_to_markdown():
    files = [
        FileScore("a.py", 100, 50, 3, 20, 2, 1.0, True, []),
        FileScore("b.py", 50, 200, 10, 60, 8, 0.5, False, ["no test"]),
    ]
    md = files_to_markdown(files)
    assert "File Trust Scores" in md
    assert "no test" in md
    assert "Total" in md


def test_test_file_is_test():
    d = _make_project({
        "src/calc.py": "x = 1\n",
        "tests/test_calc.py": "def test_x():\n    pass\n",
    })
    files = analyze_files(d)
    src_f = next(f for f in files if f.path.endswith("src/calc.py"))
    assert src_f.has_test is True


def test_skip_pycache():
    d = _make_project({"src/calc.py": "x = 1\n"})
    cache = d / "__pycache__"
    cache.mkdir()
    (cache / "calc.cpython-39.pyc").write_bytes(b"\x00")
    files = analyze_files(d)
    assert all("__pycache__" not in f.path for f in files)
