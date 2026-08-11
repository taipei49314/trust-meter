"""Remediation hints: actionable fix suggestions for trust violations.

When a metric fails, this module generates specific instructions
on how to fix the issue.

Usage:
    hints = generate_hints(report)
    for hint in hints:
        print(f"  {hint.category}: {hint.suggestion}")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from trust_meter.meter import MetricResult, TrustReport


@dataclass
class Hint:
    """A single remediation suggestion."""

    metric: str
    category: str
    severity: str  # "critical", "warning", "info"
    evidence: str
    suggestion: str

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.suggestion}"


def generate_hints(report: TrustReport) -> list[Hint]:
    """Generate remediation hints from a trust report."""
    hints: list[Hint] = []

    for metric in report.metrics:
        if metric.passed:
            continue
        hints.extend(_hints_for_metric(metric))

    return hints


def hints_markdown(hints: list[Hint]) -> str:
    """Format hints as markdown."""
    if not hints:
        return "No issues found. All metrics passed."

    lines = ["## Remediation Hints", ""]

    critical = [h for h in hints if h.severity == "critical"]
    warnings = [h for h in hints if h.severity == "warning"]
    infos = [h for h in hints if h.severity == "info"]

    if critical:
        lines.append("### Critical")
        lines.append("")
        for h in critical:
            lines.append(f"- **{h.metric}**: {h.suggestion}")
            if h.evidence:
                lines.append(f"  - Evidence: `{h.evidence}`")
        lines.append("")

    if warnings:
        lines.append("### Warnings")
        lines.append("")
        for h in warnings:
            lines.append(f"- **{h.metric}**: {h.suggestion}")
            if h.evidence:
                lines.append(f"  - Evidence: `{h.evidence}`")
        lines.append("")

    if infos:
        lines.append("### Info")
        lines.append("")
        for h in infos:
            lines.append(f"- **{h.metric}**: {h.suggestion}")

    return "\n".join(lines)


def _hints_for_metric(metric: MetricResult) -> list[Hint]:
    """Generate hints for a single failed metric."""
    name = metric.name
    hints: list[Hint] = []

    if name == "determinism":
        hints.extend(_determinism_hints(metric))
    elif name == "locality":
        hints.extend(_locality_hints(metric))
    elif name == "evidence":
        hints.extend(_evidence_hints(metric))
    elif name == "reproducibility":
        hints.extend(_reproducibility_hints(metric))
    elif name == "architecture":
        hints.extend(_architecture_hints(metric))
    elif name == "transparency":
        hints.extend(_transparency_hints(metric))

    return hints


def _determinism_hints(m: MetricResult) -> list[Hint]:
    hints: list[Hint] = []
    for ev in m.evidence:
        if "random" in ev:
            hints.append(Hint(
                metric="determinism", category="random",
                severity="critical", evidence=ev,
                suggestion="Replace random.randint/choice/sample with a deterministic alternative or seed the RNG explicitly.",
            ))
        elif "network" in ev:
            hints.append(Hint(
                metric="determinism", category="network",
                severity="critical", evidence=ev,
                suggestion="Remove network calls from production code. Use local data or pass data via arguments.",
            ))
        elif "dynamic_import" in ev:
            hints.append(Hint(
                metric="determinism", category="dynamic_import",
                severity="warning", evidence=ev,
                suggestion="Replace __import__/importlib with static imports for deterministic behavior.",
            ))
        elif "timestamp" in ev:
            hints.append(Hint(
                metric="determinism", category="timestamp",
                severity="warning", evidence=ev,
                suggestion="Pass timestamps as function arguments instead of reading wall-clock time directly.",
            ))
        elif "entropy" in ev:
            hints.append(Hint(
                metric="determinism", category="entropy",
                severity="warning", evidence=ev,
                suggestion="os.urandom/secrets produce non-deterministic output. Use a seeded PRNG if reproducibility is needed.",
            ))
    return hints


def _locality_hints(m: MetricResult) -> list[Hint]:
    hints: list[Hint] = []
    for ev in m.evidence:
        if "URL" in ev or "url" in ev.lower():
            hints.append(Hint(
                metric="locality", category="url",
                severity="warning", evidence=ev,
                suggestion="Move hardcoded URLs to configuration. The codebase should run without network access.",
            ))
        else:
            hints.append(Hint(
                metric="locality", category="dependency",
                severity="critical", evidence=ev,
                suggestion="Remove remote-only dependencies. Use stdlib alternatives or bundle data locally.",
            ))
    return hints


def _evidence_hints(m: MetricResult) -> list[Hint]:
    hints: list[Hint] = []
    for ev in m.evidence:
        if ev.startswith("untested:"):
            module = ev.split(":")[1]
            hints.append(Hint(
                metric="evidence", category="coverage",
                severity="critical", evidence=ev,
                suggestion=f"Create tests/test_{module}.py with test functions covering {module}.py.",
            ))
        elif "empty_test" in ev:
            hints.append(Hint(
                metric="evidence", category="empty_test",
                severity="warning", evidence=ev,
                suggestion="Add assertions to empty test functions. A test without assertions proves nothing.",
            ))
    return hints


def _reproducibility_hints(m: MetricResult) -> list[Hint]:
    hints: list[Hint] = []
    for ev in m.evidence:
        if "env_var" in ev:
            hints.append(Hint(
                metric="reproducibility", category="env",
                severity="warning", evidence=ev,
                suggestion="Pass environment values as function arguments instead of reading them from the system environment.",
            ))
        elif "timestamp" in ev:
            hints.append(Hint(
                metric="reproducibility", category="timestamp",
                severity="warning", evidence=ev,
                suggestion="Inject timestamps as dependencies rather than reading wall clock time.",
            ))
        elif "ordering" in ev:
            hints.append(Hint(
                metric="reproducibility", category="ordering",
                severity="warning", evidence=ev,
                suggestion="Use sorted() on directory listings and glob results for deterministic ordering.",
            ))
    return hints


def _architecture_hints(m: MetricResult) -> list[Hint]:
    hints: list[Hint] = []
    for ev in m.evidence:
        if ev.startswith("cycle:"):
            cycle = ev.split(":")[1]
            hints.append(Hint(
                metric="architecture", category="cycle",
                severity="critical", evidence=ev,
                suggestion=f"Break the circular dependency: {cycle.replace('->', ' → ')}. Extract shared code into a third module.",
            ))
        elif "coupling" in ev:
            parts = ev.split(":")
            hints.append(Hint(
                metric="architecture", category="coupling",
                severity="warning", evidence=ev,
                suggestion=f"Reduce imports in {parts[1]} (currently {parts[2]}). Consider splitting into smaller modules.",
            ))
    return hints


def _transparency_hints(m: MetricResult) -> list[Hint]:
    hints: list[Hint] = []
    for ev in m.evidence:
        if "missing docstring" in ev:
            hints.append(Hint(
                metric="transparency", category="docstring",
                severity="info", evidence=ev,
                suggestion="Add a one-line docstring to the public function/class.",
            ))
        elif "exceeds" in ev and "lines" in ev:
            hints.append(Hint(
                metric="transparency", category="length",
                severity="warning", evidence=ev,
                suggestion="Split the function into smaller, focused functions (max 50 lines each).",
            ))
        elif "TODO" in ev or "FIXME" in ev or "HACK" in ev:
            hints.append(Hint(
                metric="transparency", category="todo",
                severity="info", evidence=ev,
                suggestion="Resolve the TODO/FIXME or convert it to a tracked issue.",
            ))
    return hints
