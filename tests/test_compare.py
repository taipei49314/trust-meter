"""Tests for comparison mode."""

import json
import tempfile
from pathlib import Path

from trust_meter.compare import compare_directories, ComparisonResult, MetricComparison
from trust_meter.meter import TrustReport, MetricResult


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def _make_meter():
    from trust_meter.cli import build_meter
    return build_meter()


def test_compare_identical():
    d1 = _make_project({"src/a.py": "x = 1\n"})
    d2 = _make_project({"src/b.py": "y = 2\n"})
    result = compare_directories(d1, d2, _make_meter())
    assert result.overall_winner == "tie"
    assert result.left_score == result.right_score


def test_compare_different():
    d1 = _make_project({
        "src/a.py": 'def f():\n    """Doc."""\n    pass\n',
        "tests/test_a.py": "def test_f():\n    pass\n",
    })
    d2 = _make_project({"src/b.py": "x = 1\n"})
    result = compare_directories(d1, d2, _make_meter())
    assert result.left_score > result.right_score
    assert result.overall_winner == "left"


def test_comparison_result_properties():
    result = ComparisonResult(
        left_target="a", right_target="b",
        left_score=90, right_score=80,
        overall_winner="left", metrics=[],
    )
    assert result.left_score == 90
    assert result.overall_winner == "left"


def test_comparison_to_dict():
    result = ComparisonResult(
        left_target="a", right_target="b",
        left_score=90, right_score=80,
        overall_winner="left",
        metrics=[MetricComparison("det", 100, 90, 10, "left")],
    )
    d = result.to_dict()
    assert d["left_score"] == 90.0
    assert len(d["metrics"]) == 1


def test_comparison_to_json():
    result = ComparisonResult(
        left_target="a", right_target="b",
        left_score=90, right_score=80,
        overall_winner="left", metrics=[],
    )
    j = result.to_json()
    data = json.loads(j)
    assert "left_target" in data


def test_comparison_to_markdown():
    result = ComparisonResult(
        left_target="/tmp/a", right_target="/tmp/b",
        left_score=90, right_score=80,
        overall_winner="left",
        metrics=[MetricComparison("det", 100, 90, 10, "left")],
    )
    md = result.to_markdown()
    assert "Trust Comparison" in md
    assert "a" in md
    assert "b" in md


def test_comparison_summary_line():
    result = ComparisonResult(
        left_target="/tmp/a", right_target="/tmp/b",
        left_score=90, right_score=80,
        overall_winner="left", metrics=[],
    )
    summary = result.summary_line()
    assert "vs" in summary
    assert "left" in summary


def test_metric_comparison():
    m = MetricComparison("det", 100, 80, 20, "left")
    assert m.winner == "left"
    assert m.delta == 20
