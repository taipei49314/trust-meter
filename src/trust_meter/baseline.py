"""Baseline management: save and compare trust snapshots.

Stores trust reports as JSON files for historical comparison.

Usage:
    # Save baseline
    save_baseline(report, Path(".trust-baseline.json"))

    # Load and compare
    baseline = load_baseline(Path(".trust-baseline.json"))
    diff = diff_reports(baseline, current_report, "baseline", "current")
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from trust_meter.meter import TrustReport, MetricResult
from trust_meter.diff import diff_reports, DiffResult

BASELINE_DIR = ".trust-baselines"
DEFAULT_BASELINE = "latest.json"


def save_baseline(report: TrustReport, path: Path) -> Path:
    """Save a trust report as a baseline snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _report_to_baseline(report)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_baseline(path: Path) -> TrustReport:
    """Load a baseline snapshot as a TrustReport."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return _baseline_to_report(data)


def save_versioned(report: TrustReport, root: Path, label: str = "") -> Path:
    """Save a versioned baseline with timestamp."""
    baseline_dir = root / BASELINE_DIR
    baseline_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    name = f"{timestamp}_{label}.json" if label else f"{timestamp}.json"
    path = baseline_dir / name

    save_baseline(report, path)

    # Also update the "latest" symlink/file
    latest = baseline_dir / DEFAULT_BASELINE
    save_baseline(report, latest)

    return path


def load_latest(root: Path) -> TrustReport | None:
    """Load the latest baseline, or None if none exists."""
    latest = root / BASELINE_DIR / DEFAULT_BASELINE
    if latest.exists():
        return load_baseline(latest)
    return None


def list_baselines(root: Path) -> list[Path]:
    """List all saved baselines, newest first."""
    baseline_dir = root / BASELINE_DIR
    if not baseline_dir.exists():
        return []
    files = sorted(baseline_dir.glob("*.json"), reverse=True)
    return [f for f in files if f.name != DEFAULT_BASELINE]


def compare_to_baseline(
    current: TrustReport, root: Path, label: str = "current",
) -> DiffResult | None:
    """Compare current report against the latest baseline."""
    baseline = load_latest(root)
    if baseline is None:
        return None
    return diff_reports(baseline, current, "baseline", label)


def _report_to_baseline(report: TrustReport) -> dict:
    """Convert a TrustReport to a serializable dict."""
    return {
        "target": report.target,
        "timestamp": report.timestamp,
        "overall_score": round(report.overall_score, 2),
        "passed": report.passed,
        "phase_gate": report.phase_gate,
        "metrics": [
            {
                "name": m.name,
                "score": round(m.score, 2),
                "weight": m.weight,
                "passed": m.passed,
                "evidence": m.evidence,
                "details": m.details,
            }
            for m in report.metrics
        ],
    }


def _baseline_to_report(data: dict) -> TrustReport:
    """Convert a baseline dict back to a TrustReport."""
    metrics = [
        MetricResult(
            name=m["name"],
            score=m["score"],
            weight=m["weight"],
            passed=m["passed"],
            evidence=m.get("evidence", []),
            details=m.get("details", ""),
        )
        for m in data.get("metrics", [])
    ]
    return TrustReport(
        target=data.get("target", ""),
        timestamp=data.get("timestamp", ""),
        overall_score=data.get("overall_score", 0),
        passed=data.get("passed", False),
        phase_gate=data.get("phase_gate", ""),
        metrics=metrics,
    )
