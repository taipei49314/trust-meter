# trust-meter

Measure before you trust. Deterministic, local-first, evidence-backed trust scoring.

[![Trust Meter CI](https://github.com/taipei49314/trust-meter/actions/workflows/trust.yml/badge.svg)](https://github.com/taipei49314/trust-meter/actions/workflows/trust.yml)

## Status

```
415 tests, 752 assertions, 0 warnings
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
415 tests passed in 4.23s

test_architecture.py     18 passed
test_baseline.py         14 passed
test_batch.py            10 passed
test_blind_spots.py      52 passed
test_cli.py               7 passed
test_compare.py           8 passed
test_complexity.py       17 passed
test_config.py           17 passed
test_determinism.py      22 passed
test_diff.py             13 passed
test_evidence.py          6 passed
test_evidence_collector  14 passed
test_file_trust.py       14 passed
test_formats.py          16 passed
test_git_trust.py        10 passed
test_hooks.py            11 passed
test_ignore.py           18 passed
test_locality.py          5 passed
test_meter.py            14 passed
test_module_trust.py     15 passed
test_plugins.py          12 passed
test_remediation.py      19 passed
test_report.py           11 passed
test_reproducibility.py   6 passed
test_self_audit.py        1 passed
test_spec.py             19 passed
test_transparency.py      8 passed
test_trending.py         16 passed
test_watch.py             9 passed
test_api.py              12 passed
```

## License

MIT
