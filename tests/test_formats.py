"""Tests for the output formats module."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from trust_meter.formats import to_junit_xml, to_html
from trust_meter.meter import TrustReport, MetricResult


def _make_report(passed: bool = True, metrics: list[MetricResult] | None = None) -> TrustReport:
    if metrics is None:
        metrics = [
            MetricResult("determinism", 100, 1.0, True, [], "ok"),
            MetricResult("locality", 100, 1.0, True, [], "ok"),
        ]
    return TrustReport(
        target="/tmp/test", timestamp="2026-01-01T00:00:00Z",
        overall_score=100 if passed else 50, passed=passed, metrics=metrics,
    )


def test_junit_xml_valid():
    report = _make_report()
    xml = to_junit_xml(report)
    assert '<?xml' in xml
    root = ET.fromstring(xml.split('\n', 1)[1] if '<?xml' in xml else xml)
    assert root.tag == "testsuites"


def test_junit_xml_testcase_count():
    report = _make_report()
    xml = to_junit_xml(report)
    root = ET.fromstring(xml.split('\n', 1)[1])
    suite = root.find("testsuite")
    assert suite is not None
    assert suite.get("tests") == "2"


def test_junit_xml_failures():
    metrics = [
        MetricResult("determinism", 50, 1.0, False, ["src/a.py:1:random"], "fail"),
        MetricResult("locality", 100, 1.0, True, [], "ok"),
    ]
    report = _make_report(passed=False, metrics=metrics)
    xml = to_junit_xml(report)
    root = ET.fromstring(xml.split('\n', 1)[1])
    suite = root.find("testsuite")
    assert suite.get("failures") == "1"


def test_junit_xml_failure_message():
    metrics = [
        MetricResult("determinism", 50, 1.0, False, ["src/a.py:1:random"], "5 violations"),
    ]
    report = _make_report(passed=False, metrics=metrics)
    xml = to_junit_xml(report)
    assert "5 violations" in xml
    assert "trust_violation" in xml


def test_junit_xml_all_pass():
    report = _make_report(passed=True)
    xml = to_junit_xml(report)
    assert "<failure" not in xml


def test_junit_xml_timestamp():
    report = _make_report()
    xml = to_junit_xml(report)
    assert "2026-01-01T00:00:00Z" in xml


def test_html_valid():
    report = _make_report()
    html = to_html(report)
    assert "<!DOCTYPE html>" in html
    assert "</html>" in html


def test_html_contains_score():
    report = _make_report()
    html = to_html(report)
    assert "100.0/100" in html


def test_html_contains_metrics():
    report = _make_report()
    html = to_html(report)
    assert "determinism" in html
    assert "locality" in html


def test_html_pass_status():
    report = _make_report(passed=True)
    html = to_html(report)
    assert "PASS" in html
    assert "pass" in html


def test_html_fail_status():
    report = _make_report(passed=False)
    html = to_html(report)
    assert "FAIL" in html


def test_html_contains_phase():
    report = _make_report()
    report.phase_gate = "Phase 1"
    html = to_html(report)
    assert "Phase 1" in html


def test_html_hints_when_failing():
    metrics = [
        MetricResult("determinism", 50, 1.0, False, ["src/a.py:1:random"], "fail"),
    ]
    report = _make_report(passed=False, metrics=metrics)
    html = to_html(report)
    assert "Remediation Hints" in html


def test_html_no_hints_when_passing():
    report = _make_report(passed=True)
    html = to_html(report)
    assert "Remediation Hints" not in html


def test_html_bar_width():
    metrics = [MetricResult("test", 75, 1.0, True, [], "ok")]
    report = _make_report(passed=True, metrics=metrics)
    html = to_html(report)
    assert "width:75%" in html


def test_junit_xml_classname():
    report = _make_report()
    xml = to_junit_xml(report)
    assert "trust_meter.determinism" in xml
    assert "trust_meter.locality" in xml
