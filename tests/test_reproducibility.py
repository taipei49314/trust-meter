"""Tests for the reproducibility metric."""

import tempfile
from pathlib import Path

from trust_meter.metrics.reproducibility import collect_reproducibility


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_clean_project():
    d = _make_project({
        "src/main.py": "def add(a, b):\n    return a + b\n",
    })
    result = collect_reproducibility(d)
    assert result.score == 100.0
    assert result.passed is True


def test_env_var_read():
    d = _make_project({
        "src/main.py": "import os\nval = os.environ['HOME']\n",
    })
    result = collect_reproducibility(d)
    assert result.passed is False
    assert any("env_var" in e for e in result.evidence)


def test_datetime_now():
    d = _make_project({
        "src/main.py": "from datetime import datetime\nnow = datetime.now()\n",
    })
    result = collect_reproducibility(d)
    assert result.passed is False
    assert any("timestamp" in e for e in result.evidence)


def test_os_listdir():
    d = _make_project({
        "src/main.py": "import os\nfiles = os.listdir('.')\n",
    })
    result = collect_reproducibility(d)
    assert result.passed is False
    assert any("ordering" in e for e in result.evidence)


def test_test_files_skipped():
    d = _make_project({
        "tests/test_main.py": "import os\nval = os.environ['HOME']\n",
        "src/main.py": "x = 1\n",
    })
    result = collect_reproducibility(d)
    assert result.passed is True


def test_empty_project():
    d = _make_project({})
    result = collect_reproducibility(d)
    assert result.score == 100.0
