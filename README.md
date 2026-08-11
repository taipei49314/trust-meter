# trust-meter

Measure before you trust. Deterministic, local-first, evidence-backed trust scoring.

## What it does

Scores a codebase across 5 dimensions:

| Metric | What it checks |
|--------|---------------|
| **determinism** | No random, no network, no dynamic imports in production code |
| **locality** | No remote dependencies, no hardcoded URLs |
| **evidence** | Test coverage, assertion density, no empty tests |
| **reproducibility** | No env vars, no timestamps, deterministic ordering |
| **transparency** | Docstrings, function length, no TODO/FIXME in comments |

## Usage

```bash
# Score a project
python -m trust_meter.cli /path/to/project

# JSON output
python -m trust_meter.cli /path/to/project --json

# Phase gate (blocks if score < threshold)
python -m trust_meter.cli /path/to/project --phase "Phase 1" --threshold 80

# Strict mode (all metrics must individually pass)
python -m trust_meter.cli /path/to/project --strict

# Write report to file
python -m trust_meter.cli /path/to/project --output report.md
```

## Philosophy

- **Deterministic** — Same input, same output. Always.
- **Local-first** — No network. No cloud. No accounts.
- **Evidence-backed** — Every score has machine-parseable evidence.
- **Self-auditing** — The tool measures itself before measuring you.
