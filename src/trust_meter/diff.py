"""Diff trust: compare trust scores between two reports.

Detects:
- Regressions (score decreased)
- Improvements (score increased)
- New violations
- Fixed violations

Usage:
    from trust_meter.diff import diff_reports, DiffResult
    result = diff_reports(before_report, after_report)
    print(result.to_markdown())
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from trust_meter.meter import TrustReport, MetricResult


@dataclass
class MetricDiff:
    """Change in a single metric."""

    name: str
    before_score: float
    after_score: float
    delta: float
    before_passed: bool
    after_passed: bool
    status: str  # "improved", "regressed", "unchanged", "new_fail", "new_pass"

    @property
    def improved(self) -> bool:
        return self.status in ("improved", "new_pass")

    @property
    def regressed(self) -> bool:
        return self.status in ("regressed", "new_fail")


@dataclass
class DiffResult:
    """Comparison between two trust reports."""

    before_label: str
    after_label: str
    before_score: float
    after_score: float
    overall_delta: float
    overall_status: str  # "improved", "regressed", "unchanged"
    metrics: list[MetricDiff] = field(default_factory=list)

    @property
    def has_regressions(self) -> bool:
        return any(m.regressed for m in self.metrics)

    @property
    def has_improvements(self) -> bool:
        return any(m.improved for m in self.metrics)

    def to_dict(self) -> dict:
        return {
            "before_label": self.before_label,
            "after_label": self.after_label,
            "before_score": round(self.before_score, 2),
            "after_score": round(self.after_score, 2),
            "overall_delta": round(self.overall_delta, 2),
            "overall_status": self.overall_status,
            "metrics": [
                {
                    "name": m.name,
                    "before_score": round(m.before_score, 2),
                    "after_score": round(m.after_score, 2),
                    "delta": round(m.delta, 2),
                    "status": m.status,
                }
                for m in self.metrics
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        lines = [
            f"# Trust Diff: {self.before_label} → {self.after_label}",
            f"",
            f"**Before:** {self.before_score:.1f}/100",
            f"**After:** {self.after_score:.1f}/100",
            f"**Delta:** {self.overall_delta:+.1f}",
            f"**Status:** {self.overall_status.upper()}",
            f"",
            f"## Metric Changes",
            f"",
            f"| Metric | Before | After | Delta | Status |",
            f"|--------|--------|-------|-------|--------|",
        ]

        for m in self.metrics:
            delta_str = f"{m.delta:+.1f}" if m.delta != 0 else "0"
            lines.append(
                f"| {m.name} | {m.before_score:.0f} | {m.after_score:.0f} | {delta_str} | {m.status} |"
            )

        if self.has_regressions:
            lines.append("")
            lines.append("## Regressions")
            lines.append("")
            for m in self.metrics:
                if m.regressed:
                    lines.append(f"- **{m.name}**: {m.before_score:.0f} → {m.after_score:.0f} ({m.delta:+.1f})")

        if self.has_improvements:
            lines.append("")
            lines.append("## Improvements")
            lines.append("")
            for m in self.metrics:
                if m.improved:
                    lines.append(f"- **{m.name}**: {m.before_score:.0f} → {m.after_score:.0f} ({m.delta:+.1f})")

        return "\n".join(lines)

    def summary_line(self) -> str:
        """One-line summary for terminal output."""
        regressed = sum(1 for m in self.metrics if m.regressed)
        improved = sum(1 for m in self.metrics if m.improved)
        return f"{self.overall_status.upper()} {self.overall_delta:+.1f} | {improved} improved, {regressed} regressed"


def _classify_metric(before: MetricResult, after: MetricResult) -> MetricDiff:
    """Classify the change in a single metric."""
    delta = after.score - before.score

    if not before.passed and after.passed:
        status = "new_pass"
    elif before.passed and not after.passed:
        status = "new_fail"
    elif delta > 0.5:
        status = "improved"
    elif delta < -0.5:
        status = "regressed"
    else:
        status = "unchanged"

    return MetricDiff(
        name=before.name,
        before_score=before.score,
        after_score=after.score,
        delta=delta,
        before_passed=before.passed,
        after_passed=after.passed,
        status=status,
    )


def diff_reports(
    before: TrustReport,
    after: TrustReport,
    before_label: str = "before",
    after_label: str = "after",
) -> DiffResult:
    """Compare two trust reports and produce a diff."""
    # Build lookup for after metrics
    after_lookup = {m.name: m for m in after.metrics}

    metric_diffs: list[MetricDiff] = []
    for before_metric in before.metrics:
        after_metric = after_lookup.get(before_metric.name)
        if after_metric:
            metric_diffs.append(_classify_metric(before_metric, after_metric))
        else:
            # Metric exists in before but not after
            metric_diffs.append(MetricDiff(
                name=before_metric.name,
                before_score=before_metric.score,
                after_score=0.0,
                delta=-before_metric.score,
                before_passed=before_metric.passed,
                after_passed=False,
                status="regressed",
            ))

    overall_delta = after.overall_score - before.overall_score
    if overall_delta > 0.5:
        overall_status = "improved"
    elif overall_delta < -0.5:
        overall_status = "regressed"
    else:
        overall_status = "unchanged"

    return DiffResult(
        before_label=before_label,
        after_label=after_label,
        before_score=before.overall_score,
        after_score=after.overall_score,
        overall_delta=overall_delta,
        overall_status=overall_status,
        metrics=metric_diffs,
    )
