"""Tests for the trending module."""

import json
import tempfile
from pathlib import Path

from trust_meter.trending import TrendTracker, TrendEntry
from trust_meter.meter import TrustReport, MetricResult


def _make_report(score: float) -> TrustReport:
    return TrustReport(
        target="test", timestamp="2026-01-01T00:00:00Z",
        overall_score=score, passed=score >= 70,
        metrics=[MetricResult("determinism", score, 1.0, True, [], "ok")],
    )


def test_tracker_empty():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    assert tracker.count == 0
    assert tracker.latest is None
    assert tracker.average() == 0


def test_tracker_add():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    tracker.add(_make_report(95))
    assert tracker.count == 1
    assert tracker.latest is not None
    assert tracker.latest.score == 95


def test_tracker_persistence():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    tracker.add(_make_report(90))
    tracker.add(_make_report(95))

    # Load fresh
    tracker2 = TrendTracker(d)
    assert tracker2.count == 2
    assert tracker2.scores() == [90, 95]


def test_tracker_add_score():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    tracker.add_score(85, "2026-01-01T00:00:00Z")
    tracker.add_score(90, "2026-01-02T00:00:00Z")
    assert tracker.count == 2
    assert tracker.scores() == [85, 90]


def test_tracker_average():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    tracker.add_score(80)
    tracker.add_score(90)
    tracker.add_score(100)
    assert tracker.average() == 90.0


def test_tracker_min_max():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    tracker.add_score(70)
    tracker.add_score(100)
    tracker.add_score(85)
    assert tracker.min_score() == 70
    assert tracker.max_score() == 100


def test_tracker_sparkline_empty():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    assert tracker.sparkline() == ""


def test_tracker_sparkline():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    for s in [70, 75, 80, 85, 90, 95, 100]:
        tracker.add_score(s)
    spark = tracker.sparkline(width=7)
    assert len(spark) == 7
    # Should be ascending
    assert spark == "▁▂▃▄▅▆█"


def test_tracker_trend_improving():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    for s in [70, 72, 75, 80, 85, 90, 95, 100]:
        tracker.add_score(s)
    assert tracker.trend() == "improving"


def test_tracker_trend_declining():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    for s in [100, 95, 90, 85, 80, 75, 70]:
        tracker.add_score(s)
    assert tracker.trend() == "declining"


def test_tracker_trend_stable():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    for _ in range(10):
        tracker.add_score(90)
    assert tracker.trend() == "stable"


def test_tracker_trend_insufficient():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    tracker.add_score(90)
    assert tracker.trend() == "insufficient"


def test_tracker_to_json():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    tracker.add_score(90)
    j = tracker.to_json()
    data = json.loads(j)
    assert "count" in data
    assert "sparkline" in data
    assert "trend" in data


def test_tracker_to_markdown():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    tracker.add_score(90)
    md = tracker.to_markdown()
    assert "Trust Trend" in md
    assert "90" in md


def test_tracker_metrics_stored():
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    tracker.add(_make_report(95))
    assert tracker.latest is not None
    assert "determinism" in tracker.latest.metrics
    assert tracker.latest.metrics["determinism"] == 95


def test_trend_entry():
    e = TrendEntry("2026-01-01", 95, {"det": 100})
    assert e.score == 95
    assert e.metrics["det"] == 100
