"""Trust score API: clean programmatic interface.

Provides a simple, high-level API for using trust-meter as a library.

Usage:
    from trust_meter.api import TrustAPI

    api = TrustAPI()
    score = api.score(Path("."))
    print(score.overall)

    report = api.full_report(Path("."))
    print(report.to_markdown())

    hints = api.hints(Path("."))
    for h in hints:
        print(h)
"""

from __future__ import annotations

from pathlib import Path

from trust_meter.baseline import save_versioned, load_latest, compare_to_baseline
from trust_meter.batch import batch_scan
from trust_meter.cli import build_meter
from trust_meter.compare import compare_directories
from trust_meter.diff import diff_reports, DiffResult
from trust_meter.meter import TrustMeter, TrustReport
from trust_meter.module_trust import analyze_modules, modules_summary
from trust_meter.remediation import generate_hints, hints_markdown
from trust_meter.report import generate_report


class TrustScore:
    """Simplified trust score result."""

    def __init__(self, report: TrustReport) -> None:
        self._report = report

    @property
    def overall(self) -> float:
        return self._report.overall_score

    @property
    def passed(self) -> bool:
        return self._report.passed

    @property
    def metrics(self) -> dict[str, float]:
        return {m.name: m.score for m in self._report.metrics}

    @property
    def failures(self) -> list[str]:
        return [m.name for m in self._report.metrics if not m.passed]

    def __repr__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"TrustScore({self.overall:.1f}/100 {status})"


class TrustAPI:
    """High-level trust-meter API."""

    def __init__(self, meter: TrustMeter | None = None) -> None:
        self._meter = meter or build_meter()

    def score(self, target: Path, threshold: float = 70.0) -> TrustScore:
        """Get a simplified trust score for a directory."""
        report = self._meter.measure(target, threshold=threshold)
        return TrustScore(report)

    def full_report(
        self,
        target: Path,
        spec_path: Path | None = None,
        phase_gate: str = "",
        threshold: float = 70.0,
    ) -> TrustReport:
        """Get a full trust report with all details."""
        return generate_report(
            target, self._meter,
            spec_path=spec_path, phase_gate=phase_gate, threshold=threshold,
        )

    def hints(self, target: Path) -> list[str]:
        """Get remediation hints as string list."""
        report = self._meter.measure(target)
        return [str(h) for h in generate_hints(report)]

    def hints_markdown(self, target: Path) -> str:
        """Get remediation hints as markdown."""
        report = self._meter.measure(target)
        return hints_markdown(generate_hints(report))

    def modules(self, target: Path) -> dict:
        """Get per-module trust scores."""
        scores = analyze_modules(target)
        return modules_summary(scores)

    def compare(self, left: Path, right: Path) -> DiffResult:
        """Compare trust between two directories."""
        return compare_directories(left, right, self._meter)

    def diff(self, before: TrustReport, after: TrustReport) -> DiffResult:
        """Compare two trust reports."""
        return diff_reports(before, after)

    def save_baseline(self, target: Path, label: str = "") -> Path:
        """Save current trust as a baseline."""
        report = self._meter.measure(target)
        return save_versioned(report, target, label)

    def check_baseline(self, target: Path) -> DiffResult | None:
        """Compare current trust against saved baseline."""
        report = self._meter.measure(target)
        return compare_to_baseline(report, target)

    def batch(self, targets: list[Path]) -> list[TrustScore]:
        """Score multiple directories."""
        result = batch_scan(targets, self._meter)
        return [TrustScore(r) for r in result.reports]
