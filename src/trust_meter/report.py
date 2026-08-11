"""Report generator: produce comprehensive trust reports.

Combines:
- Trust meter scores (determinism, locality, evidence, reproducibility, transparency)
- Spec verification results
- Evidence bundle (file hashes, import graph, test results)

Output formats:
- Markdown (human-readable)
- JSON (machine-parseable)
- Summary (one-line pass/fail with score)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from trust_meter.meter import TrustMeter, TrustReport, MetricResult
from trust_meter.spec import Spec, parse_spec_file, emit_assertions, verify_assertions, Assertion
from trust_meter.evidence import EvidenceBundle, collect_evidence_bundle


@dataclass
class SpecVerification:
    """Result of verifying a single spec assertion."""

    kind: str
    target: str
    expected: str
    evidence: str
    passed: bool


@dataclass
class FullReport:
    """Complete trust report combining all verification layers."""

    target: str
    timestamp: str
    overall_score: float
    passed: bool
    phase_gate: str
    metrics: list[MetricResult]
    spec_verifications: list[SpecVerification]
    evidence_summary: dict

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "timestamp": self.timestamp,
            "overall_score": round(self.overall_score, 2),
            "passed": self.passed,
            "phase_gate": self.phase_gate,
            "metrics": [
                {
                    "name": m.name,
                    "score": round(m.score, 2),
                    "weight": m.weight,
                    "passed": m.passed,
                    "evidence": m.evidence,
                    "details": m.details,
                }
                for m in self.metrics
            ],
            "spec_verifications": [
                {
                    "kind": sv.kind,
                    "target": sv.target,
                    "expected": sv.expected,
                    "evidence": sv.evidence,
                    "passed": sv.passed,
                }
                for sv in self.spec_verifications
            ],
            "evidence_summary": self.evidence_summary,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        lines = [
            f"# Trust Report: {self.target}",
            f"",
            f"**Timestamp:** {self.timestamp}",
            f"**Overall Score:** {self.overall_score:.1f}/100",
            f"**Phase Gate:** {self.phase_gate or 'none'}",
            f"**Status:** {'PASS' if self.passed else 'FAIL'}",
            f"",
        ]

        # Metrics section
        lines.append("## Metrics")
        lines.append("")
        lines.append("| Metric | Score | Weight | Status |")
        lines.append("|--------|-------|--------|--------|")
        for m in self.metrics:
            status = "PASS" if m.passed else "FAIL"
            lines.append(f"| {m.name} | {m.score:.1f} | {m.weight:.2f} | {status} |")
        lines.append("")

        # Spec verifications
        if self.spec_verifications:
            lines.append("## Spec Verifications")
            lines.append("")
            lines.append("| Kind | Target | Expected | Evidence | Status |")
            lines.append("|------|--------|----------|----------|--------|")
            for sv in self.spec_verifications:
                status = "PASS" if sv.passed else "FAIL"
                lines.append(f"| {sv.kind} | {sv.target} | {sv.expected} | {sv.evidence} | {status} |")
            lines.append("")

        # Evidence summary
        if self.evidence_summary:
            lines.append("## Evidence Summary")
            lines.append("")
            for key, value in self.evidence_summary.items():
                lines.append(f"- **{key}:** {value}")
            lines.append("")

        return "\n".join(lines)

    def summary_line(self) -> str:
        """One-line summary for terminal output."""
        status = "PASS" if self.passed else "FAIL"
        metric_summary = ", ".join(
            f"{m.name}={m.score:.0f}" for m in self.metrics
        )
        return f"[{status}] {self.overall_score:.1f}/100 | {metric_summary}"


def _verify_spec(spec_path: Path, target: Path) -> list[SpecVerification]:
    """Verify spec assertions against target. Returns verification results."""
    if not spec_path or not spec_path.exists():
        return []
    spec = parse_spec_file(spec_path)
    assertions = emit_assertions(spec)
    verified = verify_assertions(assertions, target)
    results: list[SpecVerification] = []
    for v in verified:
        passed = all(
            s not in v.evidence
            for s in ("not found", "no test", "missing")
        )
        results.append(SpecVerification(
            kind=v.kind, target=v.target,
            expected=v.expected, evidence=v.evidence, passed=passed,
        ))
    return results


def _build_evidence_summary(
    evidence: EvidenceBundle, spec_verifications: list[SpecVerification],
) -> dict:
    """Build evidence summary dict from bundle and spec results."""
    summary = {
        "files_scanned": len(evidence.files),
        "total_lines": sum(f.lines for f in evidence.files),
        "import_edges": len(evidence.imports),
    }
    if evidence.test_result:
        summary["tests_passed"] = evidence.test_result.passed
        summary["tests_failed"] = evidence.test_result.failed
        summary["tests_errors"] = evidence.test_result.errors
    if spec_verifications:
        summary["spec_assertions"] = len(spec_verifications)
        summary["spec_passed"] = sum(1 for sv in spec_verifications if sv.passed)
    return summary


def generate_report(
    target: Path,
    meter: TrustMeter,
    spec_path: Path | None = None,
    phase_gate: str = "",
    threshold: float = 70.0,
    run_tests: bool = False,
) -> FullReport:
    """Generate a comprehensive trust report."""
    trust_report = meter.measure(target, threshold=threshold, phase_gate=phase_gate)
    evidence = collect_evidence_bundle(target, run_tests=run_tests)
    spec_verifications = _verify_spec(spec_path, target) if spec_path else []
    evidence_summary = _build_evidence_summary(evidence, spec_verifications)

    return FullReport(
        target=str(target),
        timestamp=trust_report.timestamp,
        overall_score=trust_report.overall_score,
        passed=trust_report.passed,
        phase_gate=phase_gate,
        metrics=trust_report.metrics,
        spec_verifications=spec_verifications,
        evidence_summary=evidence_summary,
    )
