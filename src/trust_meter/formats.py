"""Output formats: JUnit XML, HTML report.

Generates CI-compatible and human-readable outputs from trust reports.

Usage:
    from trust_meter.formats import to_junit_xml, to_html
    xml = to_junit_xml(report)
    html = to_html(report)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path

from trust_meter.meter import TrustReport
from trust_meter.remediation import generate_hints


def to_junit_xml(report: TrustReport) -> str:
    """Generate JUnit XML from a trust report.

    Each metric becomes a testcase. Failed metrics include failure details.
    Compatible with Jenkins, GitLab CI, GitHub Actions, etc.
    """
    testsuites = ET.Element("testsuites")
    testsuite = ET.SubElement(testsuites, "testsuite", attrib={
        "name": f"trust-meter:{report.target}",
        "tests": str(len(report.metrics)),
        "failures": str(sum(1 for m in report.metrics if not m.passed)),
        "errors": "0",
        "timestamp": report.timestamp,
    })

    for metric in report.metrics:
        testcase = ET.SubElement(testsuite, "testcase", attrib={
            "classname": f"trust_meter.{metric.name}",
            "name": metric.name,
            "time": "0",
        })

        if not metric.passed:
            failure = ET.SubElement(testcase, "failure", attrib={
                "message": f"{metric.name} score {metric.score:.0f}/100",
                "type": "trust_violation",
            })
            lines = [metric.details]
            for ev in metric.evidence[:10]:
                lines.append(f"  - {ev}")
            failure.text = "\n".join(lines)

    rough = ET.tostring(testsuites, encoding="unicode")
    return minidom.parseString(rough).toprettyxml(indent="  ", encoding=None)


def _metric_rows_html(metrics) -> str:
    """Generate HTML table rows for metrics."""
    rows = ""
    for m in metrics:
        cls = "pass" if m.passed else "fail"
        status = "PASS" if m.passed else "FAIL"
        bar = int(m.score)
        rows += f"""
        <tr class="{cls}">
            <td>{m.name}</td>
            <td>
                <div class="bar-bg"><div class="bar-fill {cls}" style="width:{bar}%"></div></div>
                <span class="score">{m.score:.0f}</span>
            </td>
            <td>{m.weight:.1f}</td>
            <td>{status}</td>
            <td class="details">{m.details}</td>
        </tr>"""
    return rows


def _hints_html(hints) -> str:
    """Generate HTML for remediation hints."""
    if not hints:
        return ""
    parts = ['<div class="hints"><h2>Remediation Hints</h2><ul>']
    for h in hints:
        parts.append(f'<li class="{h.severity}"><strong>{h.metric}:</strong> {h.suggestion}</li>')
    parts.append("</ul></div>")
    return "\n".join(parts)


_HTML_STYLE = (
    "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
    "margin:2rem;background:#f8f9fa;color:#212529}"
    ".header{background:#fff;padding:1.5rem;border-radius:8px;margin-bottom:1.5rem;"
    "box-shadow:0 1px 3px rgba(0,0,0,.1)}"
    ".header h1{margin:0 0 .5rem;font-size:1.5rem}"
    ".header .score{font-size:2.5rem;font-weight:bold}"
    ".header .score.pass{color:#28a745}.header .score.fail{color:#dc3545}"
    ".header .status{display:inline-block;padding:.25rem .75rem;border-radius:4px;color:#fff;font-weight:bold}"
    ".header .status.pass{background:#28a745}.header .status.fail{background:#dc3545}"
    "table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;"
    "box-shadow:0 1px 3px rgba(0,0,0,.1)}"
    "th{background:#343a40;color:#fff;padding:.75rem 1rem;text-align:left}"
    "td{padding:.75rem 1rem;border-bottom:1px solid #dee2e6}"
    "tr.pass td:first-child{border-left:4px solid #28a745}"
    "tr.fail td:first-child{border-left:4px solid #dc3545}"
    ".bar-bg{display:inline-block;width:100px;height:12px;background:#e9ecef;border-radius:6px;vertical-align:middle}"
    ".bar-fill{height:100%;border-radius:6px}"
    ".bar-fill.pass{background:#28a745}.bar-fill.fail{background:#dc3545}"
    ".score{margin-left:.5rem;font-weight:bold}"
    ".details{font-size:.85rem;color:#6c757d;max-width:300px}"
    ".hints{background:#fff;padding:1.5rem;border-radius:8px;margin-top:1.5rem;box-shadow:0 1px 3px rgba(0,0,0,.1)}"
    ".hints h2{margin-top:0}.hints ul{padding-left:1.5rem}"
    ".hints li{margin-bottom:.5rem}"
    ".hints li.critical{color:#dc3545}.hints li.warning{color:#ffc107}.hints li.info{color:#17a2b8}"
    ".meta{font-size:.85rem;color:#6c757d;margin-top:.5rem}"
)


def _html_template(target, status_class, status_text, score, timestamp, phase, rows, hints):
    """Assemble HTML report from pre-computed parts."""
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>Trust Report: {target}</title>"
        f"<style>{_HTML_STYLE}</style></head><body>"
        f"<div class='header'><h1>Trust Report: {target}</h1>"
        f"<div class='score {status_class}'>{score:.1f}/100</div>"
        f"<span class='status {status_class}'>{status_text}</span>"
        f"<div class='meta'>Timestamp: {timestamp} | Phase: {phase or 'none'}</div></div>"
        "<table><thead><tr><th>Metric</th><th>Score</th><th>Weight</th>"
        f"<th>Status</th><th>Details</th></tr></thead><tbody>{rows}</tbody></table>"
        f"{hints}</body></html>"
    )


def to_html(report: TrustReport) -> str:
    """Generate an HTML trust report."""
    hints = generate_hints(report)
    status_class = "pass" if report.passed else "fail"
    status_text = "PASS" if report.passed else "FAIL"
    return _html_template(
        report.target, status_class, status_text,
        report.overall_score, report.timestamp, report.phase_gate,
        _metric_rows_html(report.metrics), _hints_html(hints),
    )
