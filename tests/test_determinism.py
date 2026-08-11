"""Tests for the determinism metric."""

import tempfile
from pathlib import Path

from trust_meter.metrics.determinism import collect_determinism


def _make_project(files: dict[str, str]) -> Path:
    """Create a temp project with given files."""
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_clean_project():
    d = _make_project({
        "src/main.py": "def add(a, b):\n    return a + b\n",
        "src/utils.py": "def double(x):\n    return x * 2\n",
    })
    result = collect_determinism(d)
    assert result.score == 100.0
    assert result.passed is True
    assert result.name == "determinism"


def test_random_usage():
    d = _make_project({
        "src/main.py": "import random\nvalue = random.randint(1, 10)\n",
    })
    result = collect_determinism(d)
    assert result.score < 100.0
    assert result.passed is False
    assert any("random" in e for e in result.evidence)


def test_requests_usage():
    d = _make_project({
        "src/main.py": "import requests\nresp = requests.get('http://example.com')\n",
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert any("network" in e for e in result.evidence)


def test_comment_not_flagged():
    d = _make_project({
        "src/main.py": "# random.randint is not called\nx = 1\n",
    })
    result = collect_determinism(d)
    assert result.passed is True


def test_test_files_skipped():
    d = _make_project({
        "tests/test_main.py": "import random\nvalue = random.randint(1, 10)\n",
        "src/main.py": "x = 1\n",
    })
    result = collect_determinism(d)
    assert result.passed is True


def test_empty_project():
    d = _make_project({})
    result = collect_determinism(d)
    assert result.score == 100.0
    assert result.passed is True


def test_dynamic_import():
    d = _make_project({
        "src/main.py": "mod = __import__('os')\n",
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert any("dynamic_import" in e for e in result.evidence)


def test_multiple_violations():
    d = _make_project({
        "src/main.py": (
            "import random\n"
            "import requests\n"
            "value = random.randint(1, 10)\n"
            "resp = requests.get('http://example.com')\n"
        ),
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert result.score < 100.0
    assert len(result.evidence) >= 2
