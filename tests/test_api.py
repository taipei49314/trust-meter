"""Tests for the trust API."""

import tempfile
from pathlib import Path

from trust_meter.api import TrustAPI, TrustScore
from trust_meter.meter import TrustReport, MetricResult
from trust_meter.report import FullReport


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_api_score():
    d = _make_project({"src/a.py": "x = 1\n"})
    api = TrustAPI()
    score = api.score(d)
    assert isinstance(score, TrustScore)
    assert score.overall >= 0


def test_api_score_passed():
    d = _make_project({
        "src/calc.py": 'def add(a, b):\n    """Add."""\n    return a + b\n',
        "tests/test_calc.py": "def test_add():\n    assert add(1, 2) == 3\n",
    })
    api = TrustAPI()
    score = api.score(d)
    assert score.passed is True
    assert score.overall == 100.0


def test_api_score_failed():
    d = _make_project({"src/calc.py": "x = 1\n"})
    api = TrustAPI()
    score = api.score(d, threshold=99)
    assert score.passed is False


def test_api_score_metrics():
    d = _make_project({"src/a.py": "x = 1\n"})
    api = TrustAPI()
    score = api.score(d)
    assert "determinism" in score.metrics
    assert "evidence" in score.metrics


def test_api_score_failures():
    d = _make_project({"src/a.py": "x = 1\n"})
    api = TrustAPI()
    score = api.score(d, threshold=99)
    assert len(score.failures) > 0


def test_api_full_report():
    d = _make_project({"src/a.py": "x = 1\n"})
    api = TrustAPI()
    report = api.full_report(d)
    assert isinstance(report, FullReport)
    assert report.overall_score >= 0


def test_api_hints():
    d = _make_project({"src/a.py": "x = 1\n"})
    api = TrustAPI()
    hints = api.hints(d)
    assert isinstance(hints, list)


def test_api_hints_markdown():
    d = _make_project({"src/a.py": "x = 1\n"})
    api = TrustAPI()
    md = api.hints_markdown(d)
    assert isinstance(md, str)


def test_api_modules():
    d = _make_project({"src/a.py": "x = 1\n"})
    api = TrustAPI()
    summary = api.modules(d)
    assert "count" in summary


def test_api_batch():
    d1 = _make_project({"src/a.py": "x = 1\n"})
    d2 = _make_project({"src/b.py": "y = 2\n"})
    api = TrustAPI()
    scores = api.batch([d1, d2])
    assert len(scores) == 2
    assert all(isinstance(s, TrustScore) for s in scores)


def test_trust_score_repr():
    report = TrustReport("test", "", 95, True, [])
    score = TrustScore(report)
    assert "95" in repr(score)
    assert "PASS" in repr(score)


def test_trust_score_repr_fail():
    report = TrustReport("test", "", 50, False, [])
    score = TrustScore(report)
    assert "FAIL" in repr(score)
