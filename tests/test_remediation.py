"""Tests for the remediation module."""

from trust_meter.remediation import generate_hints, hints_markdown, Hint
from trust_meter.meter import TrustReport, MetricResult


def _make_report(metrics: list[MetricResult]) -> TrustReport:
    return TrustReport(
        target="test", timestamp="2026-01-01T00:00:00Z",
        overall_score=50, passed=False, metrics=metrics,
    )


def test_no_hints_when_all_pass():
    report = _make_report([
        MetricResult("determinism", 100, 1.0, True, [], "ok"),
    ])
    hints = generate_hints(report)
    assert len(hints) == 0


def test_determinism_random_hint():
    report = _make_report([
        MetricResult("determinism", 50, 1.0, False, ["src/main.py:3:random"], "fail"),
    ])
    hints = generate_hints(report)
    assert len(hints) >= 1
    assert any("random" in h.suggestion.lower() for h in hints)


def test_determinism_network_hint():
    report = _make_report([
        MetricResult("determinism", 50, 1.0, False, ["src/main.py:5:network"], "fail"),
    ])
    hints = generate_hints(report)
    assert any("network" in h.suggestion.lower() for h in hints)


def test_determinism_dynamic_import_hint():
    report = _make_report([
        MetricResult("determinism", 50, 1.0, False, ["src/main.py:1:dynamic_import"], "fail"),
    ])
    hints = generate_hints(report)
    assert any("import" in h.suggestion.lower() for h in hints)


def test_determinism_timestamp_hint():
    report = _make_report([
        MetricResult("determinism", 50, 1.0, False, ["src/main.py:1:timestamp"], "fail"),
    ])
    hints = generate_hints(report)
    assert any("timestamp" in h.suggestion.lower() for h in hints)


def test_locality_hint():
    report = _make_report([
        MetricResult("locality", 50, 1.0, False, ["src/main.py:1: hardcoded URL"], "fail"),
    ])
    hints = generate_hints(report)
    assert any("url" in h.suggestion.lower() or "configuration" in h.suggestion.lower() for h in hints)


def test_evidence_untested_hint():
    report = _make_report([
        MetricResult("evidence", 50, 1.0, False, ["untested:calculator"], "fail"),
    ])
    hints = generate_hints(report)
    assert any("test_calculator" in h.suggestion for h in hints)


def test_evidence_empty_test_hint():
    report = _make_report([
        MetricResult("evidence", 50, 1.0, False, ["empty_test:test_calc::test_add"], "fail"),
    ])
    hints = generate_hints(report)
    assert any("assertion" in h.suggestion.lower() for h in hints)


def test_reproducibility_env_hint():
    report = _make_report([
        MetricResult("reproducibility", 50, 1.0, False, ["src/main.py:1:env_var"], "fail"),
    ])
    hints = generate_hints(report)
    assert any("environment" in h.suggestion.lower() or "argument" in h.suggestion.lower() for h in hints)


def test_reproducibility_ordering_hint():
    report = _make_report([
        MetricResult("reproducibility", 50, 1.0, False, ["src/main.py:1:ordering"], "fail"),
    ])
    hints = generate_hints(report)
    assert any("sorted" in h.suggestion.lower() for h in hints)


def test_architecture_cycle_hint():
    report = _make_report([
        MetricResult("architecture", 50, 1.0, False, ["cycle:a->b->a"], "fail"),
    ])
    hints = generate_hints(report)
    assert any("circular" in h.suggestion.lower() or "cycle" in h.suggestion.lower() for h in hints)


def test_transparency_docstring_hint():
    report = _make_report([
        MetricResult("transparency", 50, 1.0, False,
                     ["src/main.py:5: add missing docstring"], "fail"),
    ])
    hints = generate_hints(report)
    assert any("docstring" in h.suggestion.lower() for h in hints)


def test_transparency_length_hint():
    report = _make_report([
        MetricResult("transparency", 50, 1.0, False,
                     ["src/main.py:5: big_func exceeds 50 lines (80)"], "fail"),
    ])
    hints = generate_hints(report)
    assert any("split" in h.suggestion.lower() for h in hints)


def test_transparency_todo_hint():
    report = _make_report([
        MetricResult("transparency", 50, 1.0, False,
                     ["src/main.py:5: contains TODO"], "fail"),
    ])
    hints = generate_hints(report)
    assert any("todo" in h.suggestion.lower() for h in hints)


def test_hints_markdown_empty():
    md = hints_markdown([])
    assert "No issues" in md


def test_hints_markdown_with_hints():
    hints = [
        Hint("determinism", "random", "critical", "src/main.py:3:random",
             "Replace random.randint with deterministic alternative."),
        Hint("evidence", "coverage", "critical", "untested:calc",
             "Create tests/test_calc.py."),
    ]
    md = hints_markdown(hints)
    assert "Remediation Hints" in md
    assert "Critical" in md
    assert "determinism" in md
    assert "evidence" in md


def test_hints_markdown_severity_ordering():
    hints = [
        Hint("test", "info", "info", "e", "Info hint"),
        Hint("test", "critical", "critical", "e", "Critical hint"),
        Hint("test", "warning", "warning", "e", "Warning hint"),
    ]
    md = hints_markdown(hints)
    # Critical should come before warning, warning before info
    crit_pos = md.index("Critical")
    warn_pos = md.index("Warnings")
    info_pos = md.index("Info")
    assert crit_pos < warn_pos < info_pos


def test_hint_str():
    h = Hint("test", "cat", "critical", "e", "Fix this")
    assert str(h) == "[CRITICAL] Fix this"


def test_multiple_metrics_hints():
    report = _make_report([
        MetricResult("determinism", 50, 1.0, False, ["src/a.py:1:random"], "fail"),
        MetricResult("evidence", 50, 1.0, False, ["untested:b"], "fail"),
    ])
    hints = generate_hints(report)
    assert len(hints) >= 2
    metrics = {h.metric for h in hints}
    assert "determinism" in metrics
    assert "evidence" in metrics
