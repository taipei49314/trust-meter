"""Core trust measurement engine.

Every metric produces a MetricResult. The meter aggregates them
into a TrustReport. No network. No randomness. No LLM at runtime.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable


@dataclass
class MetricResult:
    """A single metric measurement with score, weight, and evidence."""

    name: str
    score: float          # 0-100
    weight: float         # relative weight for aggregation
    passed: bool
    evidence: list[str]   # machine-parseable evidence lines
    details: str          # human-readable explanation

    @property
    def weighted(self) -> float:
        return self.score * self.weight


@dataclass
class TrustReport:
    """Aggregated trust measurement with all metric results."""

    target: str
    timestamp: str
    overall_score: float
    passed: bool
    metrics: list[MetricResult] = field(default_factory=list)
    phase_gate: str = ""

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
            f"## Metrics",
            f"",
            f"| Metric | Score | Weight | Status |",
            f"|--------|-------|--------|--------|",
        ]
        for m in self.metrics:
            status = "PASS" if m.passed else "FAIL"
            lines.append(f"| {m.name} | {m.score:.1f} | {m.weight:.2f} | {status} |")

        lines.append("")
        lines.append("## Details")
        lines.append("")
        for m in self.metrics:
            lines.append(f"### {m.name}")
            lines.append(f"{m.details}")
            if m.evidence:
                lines.append(f"")
                lines.append(f"Evidence:")
                for e in m.evidence:
                    lines.append(f"- `{e}`")
            lines.append("")

        return "\n".join(lines)


# Type alias for metric collector functions
MetricCollector = Callable[[Path], MetricResult]


class TrustMeter:
    """Collects metrics and produces trust reports.

    Usage:
        meter = TrustMeter()
        meter.register("determinism", collect_determinism, weight=1.0)
        report = meter.measure(Path("./my-project"), threshold=70)
    """

    def __init__(self) -> None:
        self._collectors: list[tuple[str, MetricCollector, float]] = []

    def register(self, name: str, collector: MetricCollector, weight: float = 1.0) -> None:
        self._collectors.append((name, collector, weight))

    def measure(
        self,
        target: Path,
        threshold: float = 70.0,
        phase_gate: str = "",
    ) -> TrustReport:
        metrics: list[MetricResult] = []
        for name, collector, weight in self._collectors:
            result = collector(target)
            # Override weight if caller specified one at registration
            if result.weight != weight:
                result = MetricResult(
                    name=result.name,
                    score=result.score,
                    weight=weight,
                    passed=result.passed,
                    evidence=result.evidence,
                    details=result.details,
                )
            metrics.append(result)

        total_weight = sum(m.weight for m in metrics) or 1.0
        overall = sum(m.weighted for m in metrics) / total_weight

        return TrustReport(
            target=str(target),
            timestamp=_fixed_timestamp(),
            overall_score=overall,
            passed=overall >= threshold and all(m.passed for m in metrics),
            metrics=metrics,
            phase_gate=phase_gate,
        )


def _fixed_timestamp() -> str:
    """UTC ISO timestamp. Deterministic — no timezone guessing."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def file_hash(path: Path) -> str:
    """SHA-256 of a file. Deterministic, local-only."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def dir_hash_tree(root: Path, patterns: list[str] | None = None) -> dict[str, str]:
    """Hash all files under root matching glob patterns. Returns {relative_path: sha256}."""
    tree: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if patterns and not any(p.match(pat) for pat in patterns):
            continue
        tree[rel] = file_hash(p)
    return tree
