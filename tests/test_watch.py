"""Tests for the watch module."""

import tempfile
import time
from pathlib import Path

from trust_meter.watch import _get_file_mtimes, _detect_changes


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_get_file_mtimes():
    d = _make_project({"src/a.py": "x = 1\n", "src/b.py": "y = 2\n"})
    mtimes = _get_file_mtimes(d)
    assert "src/a.py" in mtimes
    assert "src/b.py" in mtimes
    assert all(isinstance(v, float) for v in mtimes.values())


def test_get_file_mtimes_skips_pycache():
    d = _make_project({"src/a.py": "x = 1\n"})
    cache = d / "__pycache__"
    cache.mkdir()
    (cache / "a.cpython-39.pyc").write_bytes(b"\x00")
    mtimes = _get_file_mtimes(d)
    assert not any("__pycache__" in k for k in mtimes)


def test_get_file_mtimes_empty():
    d = _make_project({})
    assert _get_file_mtimes(d) == {}


def test_detect_changes_no_change():
    old = {"a.py": 100.0, "b.py": 200.0}
    new = {"a.py": 100.0, "b.py": 200.0}
    assert _detect_changes(old, new) == []


def test_detect_changes_modified():
    old = {"a.py": 100.0}
    new = {"a.py": 200.0}
    changes = _detect_changes(old, new)
    assert "~a.py" in changes


def test_detect_changes_added():
    old = {"a.py": 100.0}
    new = {"a.py": 100.0, "b.py": 200.0}
    changes = _detect_changes(old, new)
    assert "+b.py" in changes


def test_detect_changes_deleted():
    old = {"a.py": 100.0, "b.py": 200.0}
    new = {"a.py": 100.0}
    changes = _detect_changes(old, new)
    assert "-b.py" in changes


def test_detect_changes_multiple():
    old = {"a.py": 100.0, "b.py": 200.0}
    new = {"a.py": 300.0, "c.py": 400.0}
    changes = _detect_changes(old, new)
    assert "~a.py" in changes
    assert "+c.py" in changes
    assert "-b.py" in changes


def test_detect_changes_empty():
    assert _detect_changes({}, {}) == []
