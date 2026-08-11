"""Comparison mode: compare trust scores of two directories.

Produces a side-by-side comparison showing which project scores
higher on each metric.

Usage:
    from trust_meter.compare import compare_directories
    result = compare_directories(Path("project_a"), Path("project_b"))
    print(result.to_markdown())
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from trust_meter.meter import TrustMeter, TrustReport


@dataclass
class MetricComparison:
    """Side-by-side comparison of a single metric."""

    name: str
    left_score: float
    right_score: float
    delta: float
    winner: str  # "left", "right", "tie"


@dataclass
class ComparisonResult:
    """Full comparison between two directories."""

    left_target: str
    right_target: str
    left_score: float
    right_score: float
    overall_winner: str
    metrics: list[MetricComparison] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "left_target": self.left_target,
            "right_target": self.right_target,
            "left_score": round(self.left_score, 1),
            "right_score": round(self.right_score, 1),
            "overall_winner": self.overall_winner,
            "metrics": [
                {
                    "name": m.name,
                    "left_score": round(m.left_score, 1),
                    "right_score": round(m.right_score, 1),
                    "delta": round(m.delta, 1),
                    "winner": m.winner,
                }
                for m in self.metrics
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        left_label = Path(self.left_target).name
        right_label = Path(self.right_target).name

        lines = [
            "# Trust Comparison",
            "",
            f"**Left:** {left_label} ({self.left_score:.1f}/100)",
            f"**Right:** {right_label} ({self.right_score:.1f}/100)",
            f"**Winner:** {self.overall_winner.upper()}",
            "",
            f"| Metric | {left_label} | {right_label} | Delta | Winner |",
            f"|--------|{'-' * len(left_label)}|{'-' * len(right_label)}|-------|--------|",
        ]

        for m in self.metrics:
            delta_str = f"{m.delta:+.1f}" if m.delta != 0 else "0"
            lines.append(
                f"| {m.name} | {m.left_score:.0f} | {m.right_score:.0f} | {delta_str} | {m.winner} |"
            )

        return "\n".join(lines)

    def summary_line(self) -> str:
        left_label = Path(self.left_target).name
        right_label = Path(self.right_target).name
        return f"{left_label}={self.left_score:.0f} vs {right_label}={self.right_score:.0f} | winner: {self.overall_winner}"


def compare_directories(
    left: Path,
    right: Path,
    meter: TrustMeter | None = None,
    threshold: float = 70.0,
) -> ComparisonResult:
    """Compare trust scores of two directories."""
    if meter is None:
        from trust_meter.cli import build_meter
        meter = build_meter()

    left_report = meter.measure(left, threshold=threshold)
    right_report = meter.measure(right, threshold=threshold)

    return _build_comparison(left_report, right_report)


def _build_comparison(left: TrustReport, right: TrustReport) -> ComparisonResult:
    """Build comparison from two reports."""
    left_lookup = {m.name: m for m in left.metrics}
    right_lookup = {m.name: m for m in right.metrics}

    all_names = sorted(set(left_lookup.keys()) | set(right_lookup.keys()))

    metric_comparisons: list[MetricComparison] = []
    left_wins = 0
    right_wins = 0

    for name in all_names:
        left_m = left_lookup.get(name)
        right_m = right_lookup.get(name)

        left_score = left_m.score if left_m else 0
        right_score = right_m.score if right_m else 0
        delta = left_score - right_score

        if abs(delta) < 0.5:
            winner = "tie"
        elif delta > 0:
            winner = "left"
            left_wins += 1
        else:
            winner = "right"
            right_wins += 1

        metric_comparisons.append(MetricComparison(
            name=name, left_score=left_score, right_score=right_score,
            delta=delta, winner=winner,
        ))

    if left_wins > right_wins:
        overall = "left"
    elif right_wins > left_wins:
        overall = "right"
    else:
        overall = "tie"

    return ComparisonResult(
        left_target=left.target,
        right_target=right.target,
        left_score=left.overall_score,
        right_score=right.overall_score,
        overall_winner=overall,
        metrics=metric_comparisons,
    )
