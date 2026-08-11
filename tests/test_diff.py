"""Tests for the diff module."""

from trust_meter.diff import diff_reports, DiffResult, MetricDiff
from trust_meter.meter import TrustReport, MetricResult


def _make_report(score: float, metrics: list[MetricResult]) -> TrustReport:
    return TrustReport(
        target="test",
        timestamp="2026-01-01T00:00:00Z",
        overall_score=score,
        passed=score >= 70,
        metrics=metrics,
    )


def test_diff_identical():
    metrics = [MetricResult("determinism", 100, 1.0, True, [], "ok")]
    before = _make_report(100, metrics)
    after = _make_report(100, metrics)

    result = diff_reports(before, after, "v1", "v2")
    assert result.overall_status == "unchanged"
    assert result.overall_delta == 0.0
    assert not result.has_regressions
    assert not result.has_improvements


def test_diff_improvement():
    before_metrics = [MetricResult("determinism", 80, 1.0, True, [], "ok")]
    after_metrics = [MetricResult("determinism", 95, 1.0, True, [], "ok")]

    result = diff_reports(
        _make_report(80, before_metrics),
        _make_report(95, after_metrics),
        "v1", "v2",
    )
    assert result.overall_status == "improved"
    assert result.overall_delta == 15.0
    assert result.has_improvements
    assert not result.has_regressions
    assert result.metrics[0].status == "improved"


def test_diff_regression():
    before_metrics = [MetricResult("determinism", 100, 1.0, True, [], "ok")]
    after_metrics = [MetricResult("determinism", 70, 1.0, True, [], "ok")]

    result = diff_reports(
        _make_report(100, before_metrics),
        _make_report(70, after_metrics),
        "v1", "v2",
    )
    assert result.overall_status == "regressed"
    assert result.overall_delta == -30.0
    assert result.has_regressions
    assert result.metrics[0].status == "regressed"


def test_diff_new_failure():
    before_metrics = [MetricResult("determinism", 100, 1.0, True, [], "ok")]
    after_metrics = [MetricResult("determinism", 50, 1.0, False, [], "fail")]

    result = diff_reports(
        _make_report(100, before_metrics),
        _make_report(50, after_metrics),
    )
    assert result.metrics[0].status == "new_fail"
    assert result.has_regressions


def test_diff_new_pass():
    before_metrics = [MetricResult("determinism", 50, 1.0, False, [], "fail")]
    after_metrics = [MetricResult("determinism", 100, 1.0, True, [], "ok")]

    result = diff_reports(
        _make_report(50, before_metrics),
        _make_report(100, after_metrics),
    )
    assert result.metrics[0].status == "new_pass"
    assert result.has_improvements


def test_diff_multiple_metrics():
    before_metrics = [
        MetricResult("determinism", 100, 1.0, True, [], "ok"),
        MetricResult("locality", 80, 1.0, True, [], "ok"),
    ]
    after_metrics = [
        MetricResult("determinism", 90, 1.0, True, [], "ok"),
        MetricResult("locality", 95, 1.0, True, [], "ok"),
    ]

    result = diff_reports(
        _make_report(90, before_metrics),
        _make_report(92.5, after_metrics),
    )
    assert result.metrics[0].status == "regressed"
    assert result.metrics[1].status == "improved"


def test_diff_missing_metric():
    before_metrics = [
        MetricResult("determinism", 100, 1.0, True, [], "ok"),
        MetricResult("locality", 80, 1.0, True, [], "ok"),
    ]
    after_metrics = [MetricResult("determinism", 100, 1.0, True, [], "ok")]

    result = diff_reports(
        _make_report(90, before_metrics),
        _make_report(100, after_metrics),
    )
    locality_diff = next(m for m in result.metrics if m.name == "locality")
    assert locality_diff.status == "regressed"
    assert locality_diff.after_score == 0.0


def test_diff_to_dict():
    metrics = [MetricResult("determinism", 100, 1.0, True, [], "ok")]
    result = diff_reports(_make_report(100, metrics), _make_report(100, metrics))
    d = result.to_dict()
    assert "before_score" in d
    assert "after_score" in d
    assert "metrics" in d


def test_diff_to_json():
    metrics = [MetricResult("determinism", 100, 1.0, True, [], "ok")]
    result = diff_reports(_make_report(100, metrics), _make_report(100, metrics))
    j = result.to_json()
    assert '"before_score"' in j


def test_diff_to_markdown():
    before = [MetricResult("determinism", 80, 1.0, True, [], "ok")]
    after = [MetricResult("determinism", 100, 1.0, True, [], "ok")]
    result = diff_reports(_make_report(80, before), _make_report(100, after), "v1", "v2")
    md = result.to_markdown()
    assert "Trust Diff" in md
    assert "v1" in md
    assert "v2" in md
    assert "Improvements" in md


def test_diff_summary_line():
    metrics = [MetricResult("determinism", 100, 1.0, True, [], "ok")]
    result = diff_reports(_make_report(100, metrics), _make_report(100, metrics))
    summary = result.summary_line()
    assert "UNCHANGED" in summary


def test_metric_diff_properties():
    m = MetricDiff("test", 80, 100, 20, True, True, "improved")
    assert m.improved is True
    assert m.regressed is False

    m2 = MetricDiff("test", 100, 70, -30, True, False, "regressed")
    assert m2.improved is False
    assert m2.regressed is True


def test_diff_labels():
    metrics = [MetricResult("determinism", 100, 1.0, True, [], "ok")]
    result = diff_reports(
        _make_report(100, metrics),
        _make_report(100, metrics),
        "commit-abc", "commit-def",
    )
    assert result.before_label == "commit-abc"
    assert result.after_label == "commit-def"
