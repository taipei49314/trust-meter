"""CLI entry point for trust-meter.

Usage:
    trust-meter <target_dir> [--threshold 70] [--phase "Phase 0"] [--json] [--output report.json]

Legacy calls discover .trust-meter.toml automatically. --no-config disables
discovery, while --config reads one strict core config with no fallback.
CLI flags override admitted config values.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

from trust_meter import __version__
from trust_meter.config import (
    Config,
    ConfigError,
    has_disallowed_text_character,
    load_config,
    load_config_exact,
)
from trust_meter.formats import to_junit_xml, to_html
from trust_meter.meter import TrustMeter, TrustReport
from trust_meter.metrics.determinism import collect_determinism
from trust_meter.metrics.locality import collect_locality
from trust_meter.metrics.evidence import collect_evidence
from trust_meter.metrics.reproducibility import collect_reproducibility
from trust_meter.metrics.transparency import collect_transparency
from trust_meter.metrics.architecture import collect_architecture
from trust_meter.metrics.complexity import collect_complexity


JSON_V1_SCHEMA_VERSION = "trust-meter.measure/v1"
BUILTIN_PROFILE = "builtin-static-v1"


@dataclass(frozen=True)
class _RunContext:
    threshold: float
    phase_gate: str
    strict: bool
    config_mode: str
    config_sha256: str | None
    config_byte_length: int


def build_meter() -> TrustMeter:
    """Construct the fixed built-in static profile.

    This path deliberately does not discover plugins and its evidence metric
    parses test source without executing the target test suite.
    """
    meter = TrustMeter()
    meter.register("determinism", collect_determinism, weight=1.0)
    meter.register("locality", collect_locality, weight=1.0)
    meter.register("evidence", collect_evidence, weight=1.0)
    meter.register("reproducibility", collect_reproducibility, weight=1.0)
    meter.register("architecture", collect_architecture, weight=1.0)
    meter.register("complexity", collect_complexity, weight=0.5)
    meter.register("transparency", collect_transparency, weight=0.5)
    return meter


def _format_output(report, args) -> str:
    """Select output format based on CLI flags."""
    if args.junit:
        return to_junit_xml(report)
    if args.html:
        return to_html(report)
    if args.json:
        return report.to_json()
    return report.to_markdown()


def _json_v1_payload(
    report: TrustReport,
    *,
    threshold: float,
    phase_gate: str,
    strict: bool,
    config_mode: str,
    config_sha256: str | None,
    config_byte_length: int,
) -> dict:
    """Build the closed v1 machine result without clock or host path fields."""
    emitted_overall_score = round(report.overall_score, 2)
    threshold_met = emitted_overall_score >= threshold
    all_metrics_passed = all(metric.passed for metric in report.metrics)
    advisory_gate_met = threshold_met and (all_metrics_passed if strict else True)
    return {
        "schema_version": JSON_V1_SCHEMA_VERSION,
        "tool": {"name": "trust-meter", "version": __version__},
        "profile": {
            "name": BUILTIN_PROFILE,
            "analysis": "static_source",
            "collector_plugin_loading": "disabled",
            "collector_target_module_loading": "disabled",
            "collector_target_test_execution": "disabled",
        },
        "configuration": {
            "mode": config_mode,
            "sha256": config_sha256,
            "byte_length": config_byte_length,
            "threshold": threshold,
            "phase_gate": phase_gate,
            "strict": strict,
        },
        "result": {
            "scope": "advisory_structural_measure",
            "overall_score": emitted_overall_score,
            "threshold_met": threshold_met,
            "all_metrics_passed": all_metrics_passed,
            "advisory_gate_met": advisory_gate_met,
            "metrics": [
                {
                    "name": metric.name,
                    "score": round(metric.score, 2),
                    "weight": metric.weight,
                    "passed": metric.passed,
                    "evidence": metric.evidence,
                    "details": metric.details,
                }
                for metric in report.metrics
            ],
        },
        "authority_effect": "none",
    }


def _canonical_json_v1_bytes(payload: dict) -> bytes:
    """Encode the v1 result as compact, key-sorted UTF-8 plus one LF."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return encoded + b"\n"


def _write_machine_stdout(output: bytes) -> None:
    """Write exact LF-terminated bytes even on Windows text-mode stdout."""
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(output)
        buffer.flush()
    else:  # pytest and embedders may replace stdout with a text-only object.
        sys.stdout.write(output.decode("utf-8"))
        sys.stdout.flush()


def _validate_json_v1_request(parser: argparse.ArgumentParser, args) -> None:
    if not args.json_v1:
        return
    if not (args.no_config or args.config is not None):
        parser.error("--json-v1 requires exactly one of --no-config or --config FILE")
    if args.json or args.junit or args.html:
        parser.error("--json-v1 cannot be combined with legacy output format flags")
    if args.output is not None:
        parser.error("--json-v1 writes canonical bytes to stdout and cannot use --output")


def _validate_machine_values(threshold: float, phase_gate: str) -> None:
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 100.0:
        raise ConfigError("machine threshold must be finite and between 0 and 100")
    if len(phase_gate) > 128 or has_disallowed_text_character(
        phase_gate, allowed_whitespace=" "
    ):
        raise ConfigError("machine phase gate is invalid")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trust-meter",
        description="Measure before you trust. Deterministic, evidence-backed trust scoring.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("target", type=Path, help="Directory to measure")
    parser.add_argument("--threshold", type=float, default=None, help="Minimum score to pass")
    parser.add_argument("--phase", type=str, default=None, help="Phase gate label for report")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument(
        "--json-v1",
        action="store_true",
        help="Output the closed builtin-static-v1 machine contract",
    )
    parser.add_argument("--junit", action="store_true", help="Output JUnit XML for CI")
    parser.add_argument("--html", action="store_true", help="Output HTML report")
    parser.add_argument("--output", type=Path, default=None, help="Write report to file")
    parser.add_argument("--strict", action="store_true", help="All metrics must individually pass")
    config_group = parser.add_mutually_exclusive_group()
    config_group.add_argument(
        "--no-config",
        action="store_true",
        help="Use defaults without target or ancestor config discovery",
    )
    config_group.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="FILE",
        help="Load one bounded strict UTF-8 core config with no discovery fallback",
    )
    return parser


def _select_config(args) -> tuple[Config, str, str | None, int]:
    """Resolve one config source without changing legacy discovery semantics."""
    if args.no_config:
        return Config(), "none", None, 0
    if args.config is not None:
        exact = load_config_exact(args.config)
        return exact.config, "exact_file", exact.sha256, exact.byte_length
    return load_config(args.target), "legacy_auto", None, 0


def _prepare_run(args) -> _RunContext:
    config, mode, sha256, byte_length = _select_config(args)
    threshold = args.threshold if args.threshold is not None else config.threshold
    phase_gate = args.phase if args.phase is not None else config.phase_gate
    strict = args.strict or config.strict
    if args.json_v1:
        _validate_machine_values(threshold, phase_gate)
        if threshold == 0:
            threshold = 0.0
    return _RunContext(
        threshold, phase_gate, strict, mode, sha256, byte_length
    )


def _emit_machine_result(report: TrustReport, context: _RunContext) -> int:
    payload = _json_v1_payload(
        report,
        threshold=context.threshold,
        phase_gate=context.phase_gate,
        strict=context.strict,
        config_mode=context.config_mode,
        config_sha256=context.config_sha256,
        config_byte_length=context.config_byte_length,
    )
    try:
        output = _canonical_json_v1_bytes(payload)
    except (TypeError, ValueError) as error:
        print(f"Error: machine result is not finite canonical JSON: {error}", file=sys.stderr)
        return 2
    _write_machine_stdout(output)
    return 0 if payload["result"]["advisory_gate_met"] else 1


def _emit_legacy_result(report: TrustReport, args, strict: bool) -> int:
    if strict:
        report.passed = report.passed and all(metric.passed for metric in report.metrics)
    output = _format_output(report, args)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output)
    return 0 if report.passed else 1


def _run(args, context: _RunContext) -> int:
    report = build_meter().measure(
        args.target,
        threshold=context.threshold,
        phase_gate=context.phase_gate,
    )
    if args.json_v1:
        return _emit_machine_result(report, context)
    return _emit_legacy_result(report, args, context.strict)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: measure a directory and report trust score."""
    parser = _build_parser()

    args = parser.parse_args(argv)
    _validate_json_v1_request(parser, args)

    if not args.target.is_dir():
        print(f"Error: {args.target} is not a directory", file=sys.stderr)
        return 2 if args.json_v1 else 1

    try:
        context = _prepare_run(args)
    except ConfigError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return _run(args, context)


if __name__ == "__main__":
    sys.exit(main())
