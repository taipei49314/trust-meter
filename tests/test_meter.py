"""Tests for the core TrustMeter engine."""

import json
import tempfile
from pathlib import Path

from trust_meter.meter import TrustMeter, MetricResult, TrustReport, file_hash, dir_hash_tree


def test_metric_result_weighted():
    m = MetricResult("test", score=80, weight=0.5, passed=True, evidence=[], details="ok")
    assert m.weighted == 40.0


def test_metric_result_weighted_zero_weight():
    m = MetricResult("test", score=80, weight=0, passed=True, evidence=[], details="ok")
    assert m.weighted == 0.0


def test_trust_report_to_dict():
    report = TrustReport(
        target="/tmp/test",
        timestamp="2026-01-01T00:00:00Z",
        overall_score=85.0,
        passed=True,
        metrics=[MetricResult("m1", 90, 1.0, True, ["e1"], "good")],
        phase_gate="Phase 0",
    )
    d = report.to_dict()
    assert d["target"] == "/tmp/test"
    assert d["overall_score"] == 85.0
    assert d["passed"] is True
    assert len(d["metrics"]) == 1
    assert d["phase_gate"] == "Phase 0"


def test_trust_report_to_json():
    report = TrustReport(
        target="/tmp/test",
        timestamp="2026-01-01T00:00:00Z",
        overall_score=85.0,
        passed=True,
        metrics=[],
    )
    j = report.to_json()
    parsed = json.loads(j)
    assert parsed["overall_score"] == 85.0


def test_trust_report_to_markdown():
    report = TrustReport(
        target="/tmp/test",
        timestamp="2026-01-01T00:00:00Z",
        overall_score=85.0,
        passed=True,
        metrics=[MetricResult("m1", 90, 1.0, True, ["e1"], "good")],
    )
    md = report.to_markdown()
    assert "# Trust Report: /tmp/test" in md
    assert "PASS" in md
    assert "m1" in md


def test_trust_report_markdown_fail():
    report = TrustReport(
        target="/tmp/test",
        timestamp="2026-01-01T00:00:00Z",
        overall_score=50.0,
        passed=False,
        metrics=[MetricResult("m1", 50, 1.0, False, [], "bad")],
    )
    md = report.to_markdown()
    assert "FAIL" in md


def test_meter_empty():
    meter = TrustMeter()
    report = meter.measure(Path(tempfile.mkdtemp()), threshold=70)
    assert report.overall_score == 0.0  # no metrics = 0
    assert report.passed is False


def test_meter_single_metric():
    meter = TrustMeter()
    meter.register("test", lambda p: MetricResult("test", 90, 1.0, True, [], "ok"))
    report = meter.measure(Path(tempfile.mkdtemp()), threshold=70)
    assert report.overall_score == 90.0
    assert report.passed is True


def test_meter_weighted_average():
    meter = TrustMeter()
    meter.register("a", lambda p: MetricResult("a", 100, 1.0, True, [], "ok"), weight=2.0)
    meter.register("b", lambda p: MetricResult("b", 50, 1.0, True, [], "ok"), weight=1.0)
    report = meter.measure(Path(tempfile.mkdtemp()), threshold=70)
    # weighted: (100*2 + 50*1) / (2+1) = 250/3 = 83.33
    assert abs(report.overall_score - 83.33) < 0.1


def test_meter_threshold():
    meter = TrustMeter()
    meter.register("test", lambda p: MetricResult("test", 60, 1.0, True, [], "ok"))
    report = meter.measure(Path(tempfile.mkdtemp()), threshold=70)
    assert report.passed is False  # 60 < 70


def test_meter_metric_fails():
    meter = TrustMeter()
    meter.register("test", lambda p: MetricResult("test", 80, 1.0, False, [], "failed"))
    report = meter.measure(Path(tempfile.mkdtemp()), threshold=70)
    assert report.passed is False  # metric didn't pass


def test_meter_phase_gate():
    meter = TrustMeter()
    meter.register("test", lambda p: MetricResult("test", 90, 1.0, True, [], "ok"))
    report = meter.measure(Path(tempfile.mkdtemp()), threshold=70, phase_gate="Phase 0")
    assert report.phase_gate == "Phase 0"


def test_file_hash_deterministic():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello world")
        path = Path(f.name)
    h1 = file_hash(path)
    h2 = file_hash(path)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex
    path.unlink()


def test_dir_hash_tree():
    d = Path(tempfile.mkdtemp())
    (d / "a.txt").write_text("aaa")
    (d / "b.txt").write_text("bbb")
    tree = dir_hash_tree(d)
    assert "a.txt" in tree
    assert "b.txt" in tree
    assert len(tree["a.txt"]) == 64


def test_dir_hash_tree_with_patterns():
    d = Path(tempfile.mkdtemp())
    (d / "a.py").write_text("print(1)")
    (d / "b.txt").write_text("hello")
    tree = dir_hash_tree(d, patterns=["*.py"])
    assert "a.py" in tree
    assert "b.txt" not in tree
