"""Tests for the locality metric."""

import tempfile
from pathlib import Path

from trust_meter.metrics.locality import collect_locality


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_clean_project():
    d = _make_project({
        "src/main.py": "import os\nprint(os.getcwd())\n",
    })
    result = collect_locality(d)
    assert result.score == 100.0
    assert result.passed is True


def test_remote_dependency():
    d = _make_project({
        "requirements.txt": "requests==2.31.0\n",
        "src/main.py": "x = 1\n",
    })
    result = collect_locality(d)
    assert result.passed is False
    assert any("requests" in e for e in result.evidence)


def test_hardcoded_url():
    d = _make_project({
        "src/main.py": "API = 'https://api.example.com/v1'\n",
    })
    result = collect_locality(d)
    assert result.passed is False
    assert any("URL" in e or "url" in e.lower() for e in result.evidence)


def test_url_in_comment_ok():
    d = _make_project({
        "src/main.py": "# see https://docs.python.org for docs\nx = 1\n",
    })
    result = collect_locality(d)
    # Comments with URLs are correctly skipped — they don't indicate runtime dependencies
    assert result.passed is True


def test_no_requirements():
    d = _make_project({
        "src/main.py": "import pathlib\np = pathlib.Path('.')\n",
    })
    result = collect_locality(d)
    assert result.passed is True
