"""Reproducibility metric: verify outputs are deterministic.

Checks:
- No timestamp-dependent output patterns
- No environment variable reads in hot paths
- Deterministic file ordering (sorted, not os.listdir)
- No floating-point comparison without tolerance
"""

from __future__ import annotations

import re
from pathlib import Path

from trust_meter.meter import MetricResult

SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", "node_modules", ".tox"}

# Patterns that threaten reproducibility
THREATS: list[tuple[str, str, str]] = [
    (r"\bos\.environ\b", "env_var", "reads environment variable"),
    (r"\bos\.getenv\b", "env_var", "reads environment variable"),
    (r"\bos\.listdir\b", "ordering", "non-deterministic directory listing"),
    (r"\bglob\.glob\b", "ordering", "glob may return unsorted results"),
    (r"\btime\.time\b", "timestamp", "wall-clock timestamp"),
    (r"\bdatetime\.now\b", "timestamp", "current datetime"),
    (r"\bdatetime\.utcnow\b", "timestamp", "current UTC datetime"),
    (r"\bfloat\(\s*['\"]", "float_parse", "float from string (locale-dependent)"),
    (r"==\s*\d+\.\d+|[\d\.]+\s*==", "float_compare", "exact float comparison"),
]


def _is_production(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if any(d in rel.split("/") for d in SKIP_DIRS):
        return False
    if "test" in rel.lower() or "example" in rel.lower() or "conftest" in rel.lower():
        return False
    if "metrics/" in rel:
        return False
    return True


def collect_reproducibility(target: Path) -> MetricResult:
    """Scan for patterns that break reproducibility."""
    evidence: list[str] = []
    violations: list[str] = []
    files_scanned = 0

    for py_file in sorted(target.rglob("*.py")):
        if not _is_production(py_file, target):
            continue
        files_scanned += 1
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        rel = py_file.relative_to(target).as_posix()
        for line_no, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Skip pattern-definition lines (contain regex syntax like \b, \w, \.)
            if "\\b" in line or "\\w" in line or "\\." in line:
                continue
            for pattern, category, explanation in THREATS:
                if re.search(pattern, line):
                    violations.append(f"{rel}:{line_no}: [{category}] {explanation}")
                    evidence.append(f"{rel}:{line_no}:{category}")

    violation_count = len(violations)

    if files_scanned == 0:
        score = 100.0
        detail = "No Python files to scan"
    elif violation_count == 0:
        score = 100.0
        detail = f"All {files_scanned} files are reproducible"
    else:
        score = max(0.0, 100.0 - violation_count * 10)
        detail = f"{violation_count} reproducibility threat(s) in {files_scanned} files"

    return MetricResult(
        name="reproducibility",
        score=score,
        weight=1.0,
        passed=violation_count == 0,
        evidence=evidence[:50],
        details=detail,
    )
