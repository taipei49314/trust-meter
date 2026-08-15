"""Tests for the locality metric."""

import tempfile
from pathlib import Path

from trust_meter.metrics.locality import _check_requirements, collect_locality


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


def test_requirement_evidence_is_independent_of_glob_iteration_order(
    tmp_path, monkeypatch
):
    (tmp_path / "requirements-z.txt").write_text("requests\n", encoding="utf-8")
    (tmp_path / "requirements-a.txt").write_text("httpx\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("redis\n", encoding="utf-8")
    expected = [
        "pyproject.toml: redis is a remote-only dependency",
        "requirements-a.txt: httpx is a remote-only dependency",
        "requirements-z.txt: requests is a remote-only dependency",
    ]

    normal, _ = _check_requirements(tmp_path)
    real_glob = Path.glob

    def reversed_glob(path, pattern):
        return iter(reversed(list(real_glob(path, pattern))))

    monkeypatch.setattr(Path, "glob", reversed_glob)
    reversed_order, _ = _check_requirements(tmp_path)

    assert normal == reversed_order == expected


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
