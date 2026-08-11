"""Tests for the baseline module."""

import json
import tempfile
from pathlib import Path

from trust_meter.baseline import (
    save_baseline, load_baseline, save_versioned, load_latest,
    list_baselines, compare_to_baseline,
)
from trust_meter.meter import TrustReport, MetricResult


def _make_report(score: float = 95.0) -> TrustReport:
    return TrustReport(
        target="/tmp/test",
        timestamp="2026-01-01T00:00:00Z",
        overall_score=score,
        passed=score >= 70,
        metrics=[
            MetricResult("determinism", 100, 1.0, True, [], "ok"),
            MetricResult("locality", score, 1.0, True, [], "ok"),
        ],
    )


def test_save_and_load_baseline():
    d = Path(tempfile.mkdtemp())
    path = d / "baseline.json"
    report = _make_report(95)

    save_baseline(report, path)
    loaded = load_baseline(path)

    assert loaded.overall_score == 95.0
    assert loaded.target == "/tmp/test"
    assert len(loaded.metrics) == 2
    assert loaded.metrics[0].name == "determinism"


def test_save_baseline_creates_dirs():
    d = Path(tempfile.mkdtemp())
    path = d / "deep" / "nested" / "baseline.json"
    report = _make_report()

    save_baseline(report, path)
    assert path.exists()


def test_save_baseline_json_format():
    d = Path(tempfile.mkdtemp())
    path = d / "baseline.json"
    save_baseline(_make_report(), path)

    data = json.loads(path.read_text())
    assert "overall_score" in data
    assert "metrics" in data
    assert isinstance(data["metrics"], list)


def test_load_baseline_preserves_evidence():
    d = Path(tempfile.mkdtemp())
    path = d / "baseline.json"
    report = _make_report()
    report.metrics[0].evidence = ["evidence1", "evidence2"]

    save_baseline(report, path)
    loaded = load_baseline(path)

    assert loaded.metrics[0].evidence == ["evidence1", "evidence2"]


def test_save_versioned():
    d = Path(tempfile.mkdtemp())
    report = _make_report(88)

    path = save_versioned(report, d, "test-run")
    assert path.exists()
    assert path.parent == d / ".trust-baselines"
    assert "test-run" in path.name

    # Latest should also exist
    latest = d / ".trust-baselines" / "latest.json"
    assert latest.exists()


def test_save_versioned_no_label():
    d = Path(tempfile.mkdtemp())
    path = save_versioned(_make_report(), d)
    assert path.exists()
    assert path.name.endswith(".json")


def test_load_latest():
    d = Path(tempfile.mkdtemp())
    report = _make_report(77)
    save_versioned(report, d, "v1")

    loaded = load_latest(d)
    assert loaded is not None
    assert loaded.overall_score == 77.0


def test_load_latest_none():
    d = Path(tempfile.mkdtemp())
    assert load_latest(d) is None


def test_list_baselines():
    d = Path(tempfile.mkdtemp())
    save_versioned(_make_report(80), d, "v1")
    save_versioned(_make_report(90), d, "v2")
    save_versioned(_make_report(95), d, "v3")

    baselines = list_baselines(d)
    assert len(baselines) == 3
    # Should be newest first
    assert baselines[0].name > baselines[1].name


def test_list_baselines_empty():
    d = Path(tempfile.mkdtemp())
    assert list_baselines(d) == []


def test_compare_to_baseline():
    d = Path(tempfile.mkdtemp())
    baseline = _make_report(80)
    save_versioned(baseline, d, "baseline")

    current = _make_report(95)
    diff = compare_to_baseline(current, d, "current")

    assert diff is not None
    assert diff.before_score == 80.0
    assert diff.after_score == 95.0
    assert diff.overall_status == "improved"


def test_compare_to_baseline_none():
    d = Path(tempfile.mkdtemp())
    diff = compare_to_baseline(_make_report(), d)
    assert diff is None


def test_compare_to_baseline_regression():
    d = Path(tempfile.mkdtemp())
    save_versioned(_make_report(100), d, "good")

    current = _make_report(70)
    diff = compare_to_baseline(current, d)

    assert diff is not None
    assert diff.overall_status == "regressed"
    assert diff.has_regressions


def test_baseline_roundtrip():
    """Save → Load → Save should produce identical JSON."""
    d = Path(tempfile.mkdtemp())
    path1 = d / "first.json"
    path2 = d / "second.json"

    report = _make_report(85)
    save_baseline(report, path1)
    loaded = load_baseline(path1)
    save_baseline(loaded, path2)

    assert path1.read_text() == path2.read_text()
