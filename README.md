# trust-meter

Measure before you trust. Deterministic, local-first, evidence-backed trust scoring.

[![Trust Meter CI](https://github.com/taipei49314/trust-meter/actions/workflows/trust.yml/badge.svg)](https://github.com/taipei49314/trust-meter/actions/workflows/trust.yml)

## Status

```
573 tests, 960 assertion tokens, 0 warnings
100% module coverage, 100% documented
Self-audit: 100/100 (7 metrics)
Python support: 3.11+
CI contract: source tests on 3.11–3.14 across Ubuntu 24.04 and Windows 2025
Source version: 0.2.1 release candidate, prepared before publication
Publication evidence: exact v0.2.1 tag, subject commit, Release state, and attached assets
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

For development from a checkout:

```bash
pip install -e .
```

The `0.2.1` source tree is a release candidate prepared before publication; a
version string or this README is never publication evidence. Verify an actual
GitHub Release, exact tag and target commit, and attached asset digests. PyPI is
not a publication channel for this release.

`v0.2.0` is retained only as a quarantined, abandoned, unpublished candidate.
Its timeless status and pre-mutation failure boundary are recorded in
`.github/RELEASE_CANDIDATE_HISTORY.md`; it is not a public release.

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
The repository's closed schema is
`schemas/trust-meter-measure-v1.schema.json`.

## Packaging and CI boundary

The repository-root schema remains canonical. Its `$id` is the exact future
immutable `v0.2.1` release-asset URL. The wheel contains a byte-for-byte copy at
`trust_meter/schemas/trust-meter-measure-v1.schema.json`. The controlled GitHub
release workflow promotes those same root bytes as the manually attached
`trust-meter-measure-v1.schema.json`. Candidate checks bind the URL string and
bytes without requiring the future URL to resolve; after publication, a human
must anonymously fetch and hash the attachment.

CI separates source verification from distribution verification:

- source tests run directly from `src/` on Ubuntu 24.04 and Windows 2025 with
  Python 3.11 through 3.14 and the fully hash-locked `requirements/test.txt`
  dependency closure;
- one Ubuntu 24.04 job builds the canonical wheel and sdist once with the
  hash-locked `requirements/build.txt` backend closure;
- the standard-library archive verifier checks safe member paths, wheel RECORD
  hashes and sizes, package metadata, Python floor, version, LICENSE, and schema;
- the sdist is rebuilt into an ephemeral wheel from a fresh backend environment
  using only the hash-checked local wheelhouse while a Linux network namespace
  denies network access; the rebuilt wheel is verified but is not published;
- Ubuntu 24.04/Python 3.11 and Windows 2025/Python 3.14 jobs download the same
  canonical wheel, install it with `--no-index --no-deps`, and exercise it from
  outside the checkout with `PYTHONPATH` and `PYTHONHOME` removed; and
- the stable `Required` job aggregates all source, build, verifier, and installed
  asset jobs for branch protection.

These checks qualify package construction and the installed CLI surface. They do
not upgrade the measurement's authority: machine output remains advisory and
`authority_effect` remains `none`.

### Controlled GitHub release boundary

`.github/workflows/release.yml` is a promotion workflow, not another builder. It
is manual (`workflow_dispatch`) and must itself be dispatched from `master`. Its
five inputs are the exact version, full subject commit SHA, successful post-merge
Trust Meter CI run ID, a draft GitHub Release ID when the selected mode requires
one, and `rehearsal`, `draft-rehearsal`, `dry-run`, or `upload-draft`. The workflow
is deliberately locked to `0.2.1` / `v0.2.1`.

Every mode starts with the same read-only `prepare` job. Its only token grants
are `actions: read` and `contents: read`. That job binds all of the following:

- the trusted control SHA, requested subject SHA, and live `master` SHA are
  identical; there is no control/source split;
- the subject is the latest attempt of a successful `master` push run of
  `.github/workflows/trust.yml`, with exactly the expected 12 successful jobs;
- that run has one unique, unexpired, SHA-256-addressed `release-dist` Actions
  artifact whose run, branch, and subject SHA match;
- the promoted wheel and sdist pass the repository's archive verifier against a
  non-executed checkout of the identical subject source;
- source metadata, runtime version, duplicate-key-free schema `$id`, and the
  canonical LF-only `RELEASE_NOTES-v0.2.1.md` match the exact `0.2.1` contract;
  and
- the resulting prepared artifact is rebound by ID, digest, positive size,
  workflow run, branch, and subject SHA.

`prepare` never reads a tag or any GitHub Release endpoint. This matters because
a `contents: read` workflow token can read public Release state but does not have
the push capability required to see an unpublished private draft. GitHub API
failures report only a validated method/path, status, bounded GitHub `message`,
and bounded `X-Accepted-GitHub-Permissions`; tokens and response bodies are not
logged.

Every mode except `rehearsal` then enters the same protected `github-release`
environment job with `actions: read` and `contents: write`. That job checks out no
repository. It downloads only the prepared artifact by exact ID, with digest
mismatch configured as an error, and rebinds the control/subject SHA, live
`master`, CI attempt and artifact ID/digest, prepared artifact
ID/digest/size/run/branch/head SHA, canonical notes digest, and exact draft
ID/title/body/target/unpublished state.

- `draft-rehearsal` performs only GET operations, requires an exact empty draft,
  and deliberately does not read or require a tag. It proves private-draft
  visibility before the non-replaceable tag is created.
- `dry-run` also performs only GET operations and requires the exact empty draft,
  then additionally binds a lightweight tag directly to the subject or one
  annotated tag that peels directly and unambiguously to it.
- `upload-draft` additionally requires that exact tag. Only its upload step maps
  `TRUST_METER_RELEASE_APPROVAL`; the preceding protected GET gate cannot see that
  secret. It accepts an empty draft or an already complete exact asset set.

The exact manually attached release asset set is:

- `trust_meter-0.2.1-py3-none-any.whl`
- `trust_meter-0.2.1.tar.gz`
- `trust-meter-measure-v1.schema.json`
- `SHA256SUMS.txt`

The ledger contains LF-only, sorted lowercase SHA-256 rows for the wheel, sdist,
and schema, not for itself. The prepared Actions artifact is retained for seven
days and can still expire or be deleted.

Uploads are create-only: any partial, duplicate, extra, renamed, or mismatched
draft asset fails closed. A partial upload failure is not automatically retryable;
an administrator must discard that draft and create a new empty one before a new
run. After upload, all four assets are downloaded through the GitHub API without
forwarding authorization across the asset redirect and are rehashed. The final
gate fully rebinds live `master`, CI, prepared artifact, tag, notes, exact draft
metadata/state, and asset identities after those downloads. The release stays a
draft and the successful handoff is labeled `READY_FOR_HUMAN_PUBLICATION`; the
workflow never creates or publishes a Release, changes draft metadata or state,
mutates a tag, or publishes to PyPI.

GitHub also displays generated source-code zip and tar archives. They are not API
release attachments and are not the verified sdist; the canonical sdist is
`trust_meter-0.2.1.tar.gz`. The tagged release-notes file is the canonical notes
record. The GitHub body is an exactly checked navigation copy, not immutable
authority.

For a real upload to be authorized, repository administrators must independently
verify protected `master` and `v*` tag rulesets, required reviewers on the
`github-release` environment, and immutable releases. For this release, the
`TRUST_METER_RELEASE_APPROVAL` secret value must be the exact release-scoped kill
switch `taipei49314/trust-meter:v0.2.1:upload-draft`. Until those settings and all
exact subject, tag, draft, CI-run, prepared-artifact, and notes gates pass, no
upload is authorized.

The workflow deliberately does not use an administration token and therefore
does not query or prove the ruleset or immutable-release settings. Environment
approval and the release-scoped secret are manual preconditions and a kill
switch, not evidence that repository governance is configured or that the secret
has the intended scope. The final workflow read also cannot close the interval
before a human clicks Publish. Immediately before publication, a human must
separately recheck governance, tag/subject, title, canonical notes body, draft
state, exact attached asset IDs/digests, and anonymous downloads.

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
573 tests passed (Python 3.11, Windows hash-locked local verification)

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
test_github_release.py     16 passed
test_hooks.py              11 passed
test_ignore.py             18 passed
test_locality.py            6 passed
test_meter.py              15 passed
test_module_trust.py       15 passed
test_plugins.py            12 passed
test_release_artifacts.py  13 passed
test_release_bundle.py     11 passed
test_release_candidate.py   5 passed
test_release_promotion.py  45 passed
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

[MIT](LICENSE)
