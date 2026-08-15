# trust-meter

Measure before you trust. Deterministic, local-first, evidence-backed trust scoring.

[![Trust Meter CI](https://github.com/taipei49314/trust-meter/actions/workflows/trust.yml/badge.svg)](https://github.com/taipei49314/trust-meter/actions/workflows/trust.yml)

## Status

```
483 tests, 833 assertion tokens, 0 warnings
100% module coverage, 100% documented
Self-audit: 100/100 (7 metrics)
CI: Python 3.9 / 3.10 / 3.11 / 3.12 — all green
```

## What it does

Scores a codebase across 7 dimensions:

| Metric | Weight | What it checks |
|--------|--------|---------------|
| **determinism** | 1.0 | AST-based: no random, no network, no dynamic imports |
| **locality** | 1.0 | No remote dependencies, no hardcoded URLs |
| **evidence** | 1.0 | Test coverage, assertion density, no empty tests |
| **reproducibility** | 1.0 | No env vars, no timestamps, deterministic ordering |
| **architecture** | 1.0 | No circular dependencies, coupling analysis, chain depth |
| **complexity** | 0.5 | Cyclomatic complexity per function (max 10) |
| **transparency** | 0.5 | Docstrings, function length, no TODO/FIXME |

## Install

```bash
pip install -e .
```

## Usage

```bash
# Basic scan (markdown output)
python -m trust_meter.cli .

# JSON output
python -m trust_meter.cli . --json

# Closed machine JSON (requires an explicit config boundary)
python -m trust_meter.cli . --json-v1 --no-config

# Or bind one strict config file by the bytes read and reported SHA-256
python -m trust_meter.cli . --json-v1 --config ./measurement.toml

# Package version
python -m trust_meter.cli --version

# JUnit XML for CI
python -m trust_meter.cli . --junit

# HTML report
python -m trust_meter.cli . --html --output report.html

# Phase gate with threshold
python -m trust_meter.cli . --phase "Phase 1" --threshold 80

# Strict mode (all metrics must individually pass)
python -m trust_meter.cli . --strict

# Write report to file
python -m trust_meter.cli . --output report.md
```

## Features

| Feature | Description |
|---------|-------------|
| **7 metrics** | determinism, locality, evidence, reproducibility, architecture, complexity, transparency |
| **AST analysis** | Real function call detection (import aliases, from-imports, instance methods) |
| **Spec engine** | TOML-like spec files with structured assertion verification |
| **Evidence collector** | File hashes, import graph, test runner |
| **Report generator** | JSON, Markdown, JUnit XML, HTML output |
| **Diff trust** | Compare trust scores between commits |
| **Baseline management** | Save/compare trust snapshots over time |
| **Trending** | Track scores with sparkline visualization |
| **Module trust** | Per-module trust scores |
| **File trust** | Per-file trust scores |
| **Comparison mode** | Side-by-side directory comparison |
| **Batch mode** | Scan multiple directories at once |
| **Watch mode** | Auto re-run on file changes |
| **Git integration** | Commit info, history, trust tags |
| **Pre-commit hook** | Auto-block commits on trust failure |
| **Plugin system** | Custom metrics via `.trust-meter/plugins/` |
| **Config file** | `.trust-meter.toml` for per-project settings |
| **.trustignore** | gitignore-style pattern exclusion |
| **Remediation hints** | Actionable fix suggestions per metric |
| **Trust API** | Clean programmatic interface |

## Config

Create `.trust-meter.toml` in your project root:

```toml
[trust-meter]
threshold = 80.0
phase_gate = "Phase 1"
strict = true

[skip]
patterns = ["vendor/*", "generated/*"]

[weights]
determinism = 1.0
complexity = 0.5

[limits]
max_function_lines = 50
max_imports_per_module = 15
```

Legacy invocations with neither `--no-config` nor `--config` keep the original
behavior of searching the target and its ancestors for `.trust-meter.toml`.
The legacy parser retains its historical `skip`, `weights`, and `limits`
surface, but the current core CLI does not apply those fields; they must not be
treated as effective measurement inputs.
`--no-config` performs no such discovery. `--config FILE` reads only the named
regular file, with no fallback, and accepts only the core-effective
`[trust-meter]` keys `threshold`, `phase_gate`, and `strict`. It rejects
malformed, unknown, duplicate, non-finite, non-UTF-8, or oversized input.
Full-line `#` comments are admitted. The bounded scalar grammar does not accept
inline comments, escapes, or trailing commas. Machine phase labels admit an
ordinary ASCII space but reject non-ASCII whitespace and every Unicode general
category C character.

## Machine contract v1

`--json-v1` is additive; the legacy `--json` shape is unchanged. Machine v1:

- requires exactly one of `--no-config` or `--config FILE`;
- accepts only `[trust-meter]` `threshold`, `phase_gate`, and `strict` from an
  exact config, because those are the config values the built-in core applies;
- emits compact key-sorted UTF-8 JSON with one LF and schema version
  `trust-meter.measure/v1`;
- excludes the wall-clock timestamp and target path from the canonical result;
- uses the fixed `builtin-static-v1` collectors, which do not discover plugins,
  import target modules, or execute the target test suite;
- fixes metric order and weights to determinism, locality, evidence,
  reproducibility, and architecture at `1.0`, followed by complexity and
  transparency at `0.5`; and
- reports advisory measurements only, with `authority_effect` fixed to `none`.

For machine v1, non-strict `advisory_gate_met` and exit status use only the
threshold comparison; strict mode additionally requires every metric to pass.
Both component facts remain separate in JSON. This is new protocol behavior;
the legacy output and exit semantics are unchanged. `overall_score` is rounded
to two decimal places before the machine threshold comparison, so the emitted
score and `threshold_met` cannot contradict one another.
Architecture file, node, dependency, and cycle traversal is sorted before
machine evidence is emitted, removing set and discovery order from that metric.

The collector contract does not prove that Python interpreter startup,
`sitecustomize`, user-site packages, or the host runtime are isolated. A caller
such as Evidence Workbench must qualify and contain that runtime separately;
until then, execution remains fail closed there.

The exact reader compares the pre-open path identity and state with the opened
handle, verifies the handle around the read, and checks the path again after
the read. The exact-config digest identifies the same bytes that were parsed;
these checks reduce leaf-swap exposure but do not prove immutable path identity
across operating-system races, including Windows systems without `O_NOFOLLOW`.
The published closed schema is
`schemas/trust-meter-measure-v1.schema.json`.

## Custom Metrics

Create `.trust-meter/plugins/my_check.py`:

```python
from trust_meter.meter import MetricResult

def collect_my_check(target):
    # Your custom analysis here
    return MetricResult(
        name="my_check",
        score=100.0,
        weight=1.0,
        passed=True,
        evidence=[],
        details="All good",
    )
```

## Git Hook

```bash
# Install pre-commit hook
python -m trust_meter.hooks install

# Uninstall
python -m trust_meter.hooks uninstall

# Check status
python -m trust_meter.hooks status
```

## API

```python
from trust_meter.api import TrustAPI

api = TrustAPI()

# Quick score
score = api.score(Path("."))
print(score.overall)    # 100.0
print(score.passed)     # True
print(score.failures)   # []

# Full report
report = api.full_report(Path("."))

# Remediation hints
hints = api.hints(Path("."))

# Compare two projects
diff = api.compare(Path("project_a"), Path("project_b"))
```

## Philosophy

- **Deterministic** — Same input, same output. Always.
- **Local-first** — No network. No cloud. No accounts. Zero external dependencies.
- **Evidence-backed** — Every score has machine-parseable evidence.
- **Self-auditing** — The tool measures itself before measuring you.
- **Every phase gated** — Trust meter runs before each step forward.

## Test Results

```
483 tests passed (Python 3.11, Windows local verification)

test_api.py                12 passed
test_architecture.py       19 passed
test_baseline.py           14 passed
test_batch.py              10 passed
test_blind_spots.py        52 passed
test_cli.py                41 passed
test_compare.py             8 passed
test_complexity.py         17 passed
test_config.py             49 passed
test_determinism.py        22 passed
test_diff.py               13 passed
test_evidence.py            6 passed
test_evidence_collector.py 14 passed
test_file_trust.py         14 passed
test_formats.py            16 passed
test_git_trust.py          10 passed
test_hooks.py              11 passed
test_ignore.py             18 passed
test_locality.py            6 passed
test_meter.py              15 passed
test_module_trust.py       15 passed
test_plugins.py            12 passed
test_remediation.py        19 passed
test_report.py             11 passed
test_reproducibility.py     6 passed
test_self_audit.py          1 passed
test_spec.py               19 passed
test_transparency.py        8 passed
test_trending.py           16 passed
test_watch.py               9 passed
```

## License

MIT
