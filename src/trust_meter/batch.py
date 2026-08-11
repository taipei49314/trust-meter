"""Batch mode: scan multiple directories at once.

Produces a combined report across multiple targets.

Usage:
    from trust_meter.batch import batch_scan
    results = batch_scan([Path("src/a"), Path("src/b")])
    for r in results:
        print(f"{r.target}: {r.overall_score:.0f}/100")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from trust_meter.meter import TrustMeter, TrustReport


@dataclass
class BatchResult:
    """Result of a batch scan."""

    reports: list[TrustReport] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.reports)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.reports)

    @property
    def avg_score(self) -> float:
        if not self.reports:
            return 0
        return sum(r.overall_score for r in self.reports) / len(self.reports)

    @property
    def min_score(self) -> float:
        if not self.reports:
            return 0
        return min(r.overall_score for r in self.reports)

    @property
    def max_score(self) -> float:
        if not self.reports:
            return 0
        return max(r.overall_score for r in self.reports)

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "all_passed": self.all_passed,
            "avg_score": round(self.avg_score, 1),
            "min_score": round(self.min_score, 1),
            "max_score": round(self.max_score, 1),
            "reports": [
                {
                    "target": r.target,
                    "score": round(r.overall_score, 1),
                    "passed": r.passed,
                }
                for r in self.reports
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        lines = [
            "# Batch Trust Report",
            "",
            f"**Scanned:** {self.count} targets",
            f"**Average:** {self.avg_score:.1f}/100",
            f"**Range:** {self.min_score:.1f} — {self.max_score:.1f}",
            f"**All Passed:** {'YES' if self.all_passed else 'NO'}",
            "",
            "| Target | Score | Status |",
            "|--------|-------|--------|",
        ]
        for r in self.reports:
            status = "PASS" if r.passed else "FAIL"
            lines.append(f"| {r.target} | {r.overall_score:.0f} | {status} |")
        return "\n".join(lines)


def batch_scan(
    targets: list[Path],
    meter: TrustMeter | None = None,
    threshold: float = 70.0,
    phase_gate: str = "",
) -> BatchResult:
    """Scan multiple directories and produce a combined report."""
    if meter is None:
        from trust_meter.cli import build_meter
        meter = build_meter()

    result = BatchResult()
    for target in targets:
        if target.is_dir():
            report = meter.measure(target, threshold=threshold, phase_gate=phase_gate)
            result.reports.append(report)
    return result


def batch_scan_glob(
    pattern: str,
    root: Path,
    meter: TrustMeter | None = None,
    threshold: float = 70.0,
) -> BatchResult:
    """Scan directories matching a glob pattern."""
    targets = sorted(p for p in root.glob(pattern) if p.is_dir())
    return batch_scan(targets, meter, threshold)
