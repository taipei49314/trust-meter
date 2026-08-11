"""CLI entry point for trust-meter.

Usage:
    trust-meter <target_dir> [--threshold 70] [--phase "Phase 0"] [--json] [--output report.json]

Config file (.trust-meter.toml) is loaded automatically from the target directory.
CLI flags override config file values.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from trust_meter.config import load_config
from trust_meter.meter import TrustMeter
from trust_meter.metrics.determinism import collect_determinism
from trust_meter.metrics.locality import collect_locality
from trust_meter.metrics.evidence import collect_evidence
from trust_meter.metrics.reproducibility import collect_reproducibility
from trust_meter.metrics.transparency import collect_transparency
from trust_meter.metrics.architecture import collect_architecture


def build_meter() -> TrustMeter:
    """Construct a meter with all default metrics."""
    meter = TrustMeter()
    meter.register("determinism", collect_determinism, weight=1.0)
    meter.register("locality", collect_locality, weight=1.0)
    meter.register("evidence", collect_evidence, weight=1.0)
    meter.register("reproducibility", collect_reproducibility, weight=1.0)
    meter.register("architecture", collect_architecture, weight=1.0)
    meter.register("transparency", collect_transparency, weight=0.5)
    return meter


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: measure a directory and report trust score."""
    parser = argparse.ArgumentParser(
        prog="trust-meter",
        description="Measure before you trust. Deterministic, evidence-backed trust scoring.",
    )
    parser.add_argument("target", type=Path, help="Directory to measure")
    parser.add_argument("--threshold", type=float, default=None, help="Minimum score to pass")
    parser.add_argument("--phase", type=str, default=None, help="Phase gate label for report")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")
    parser.add_argument("--output", type=Path, default=None, help="Write report to file")
    parser.add_argument("--strict", action="store_true", help="All metrics must individually pass")

    args = parser.parse_args(argv)

    if not args.target.is_dir():
        print(f"Error: {args.target} is not a directory", file=sys.stderr)
        return 1

    # Load config (CLI flags override config)
    config = load_config(args.target)
    threshold = args.threshold if args.threshold is not None else config.threshold
    phase_gate = args.phase if args.phase is not None else config.phase_gate
    strict = args.strict or config.strict

    meter = build_meter()
    report = meter.measure(args.target, threshold=threshold, phase_gate=phase_gate)

    if strict:
        report.passed = report.passed and all(m.passed for m in report.metrics)

    output = report.to_json() if args.json else report.to_markdown()

    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
