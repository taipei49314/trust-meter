"""Tests for batch mode."""

import json
import tempfile
from pathlib import Path

from trust_meter.batch import batch_scan, batch_scan_glob, BatchResult
from trust_meter.meter import TrustMeter, TrustReport, MetricResult


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def _make_meter() -> TrustMeter:
    from trust_meter.cli import build_meter
    return build_meter()


def test_batch_scan_empty():
    result = batch_scan([], _make_meter())
    assert result.count == 0
    assert result.all_passed is True
    assert result.avg_score == 0


def test_batch_scan_single():
    d = _make_project({"src/calc.py": "x = 1\n"})
    result = batch_scan([d], _make_meter())
    assert result.count == 1
    assert result.reports[0].target == str(d)


def test_batch_scan_multiple():
    d1 = _make_project({"src/a.py": "x = 1\n"})
    d2 = _make_project({"src/b.py": "y = 2\n"})
    result = batch_scan([d1, d2], _make_meter())
    assert result.count == 2


def test_batch_scan_skips_nonexistent():
    d = _make_project({"src/a.py": "x = 1\n"})
    result = batch_scan([d, Path("/nonexistent")], _make_meter())
    assert result.count == 1


def test_batch_result_properties():
    result = BatchResult(reports=[
        TrustReport("a", "", 90, True, []),
        TrustReport("b", "", 80, True, []),
    ])
    assert result.count == 2
    assert result.all_passed is True
    assert result.avg_score == 85.0
    assert result.min_score == 80.0
    assert result.max_score == 90.0


def test_batch_result_not_all_passed():
    result = BatchResult(reports=[
        TrustReport("a", "", 90, True, []),
        TrustReport("b", "", 50, False, []),
    ])
    assert result.all_passed is False


def test_batch_result_to_dict():
    result = BatchResult(reports=[
        TrustReport("a", "", 90, True, []),
    ])
    d = result.to_dict()
    assert d["count"] == 1
    assert d["avg_score"] == 90.0


def test_batch_result_to_json():
    result = BatchResult(reports=[
        TrustReport("a", "", 90, True, []),
    ])
    j = result.to_json()
    data = json.loads(j)
    assert "reports" in data


def test_batch_result_to_markdown():
    result = BatchResult(reports=[
        TrustReport("a", "", 90, True, []),
        TrustReport("b", "", 50, False, []),
    ])
    md = result.to_markdown()
    assert "Batch Trust Report" in md
    assert "PASS" in md
    assert "FAIL" in md


def test_batch_scan_glob():
    root = Path(tempfile.mkdtemp())
    (root / "project_a").mkdir()
    (root / "project_a" / "main.py").write_text("x = 1\n")
    (root / "project_b").mkdir()
    (root / "project_b" / "main.py").write_text("y = 2\n")

    result = batch_scan_glob("project_*", root, _make_meter())
    assert result.count == 2
