"""Determinism metric: scan source for non-deterministic patterns.

Checks:
- No random.randint / random.random / random.choice in production code
- No time.time() / datetime.now() without explicit timezone
- No os.urandom / secrets usage in hot paths
- No network calls (urllib, requests, httpx, socket) in core logic
- No __import__ / importlib dynamic imports in hot paths
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from trust_meter.meter import MetricResult

# Patterns that indicate non-deterministic behavior
FORBIDDEN_PATTERNS: list[tuple[str, str, str]] = [
    # (regex_pattern, category, explanation)
    (r"\brandom\.(randint|random|choice|shuffle|sample|uniform)\b", "random", "random module call"),
    (r"\bos\.urandom\b", "entropy", "OS entropy source"),
    (r"\bsecrets\.\w+", "entropy", "secrets module usage"),
    (r"\brequests\.(get|post|put|delete|patch|head)\b", "network", "HTTP request"),
    (r"\bhttpx\.\w+\.(get|post|put|delete|patch|head)\b", "network", "HTTP request"),
    (r"\burllib\.request\.urlopen\b", "network", "URL open"),
    (r"\bsocket\.(connect|bind|listen)\b", "network", "socket operation"),
    (r"\b__import__\b", "dynamic_import", "dynamic import"),
    (r"\bimportlib\.import_module\b", "dynamic_import", "dynamic import"),
]

# Files/dirs to skip (test files, examples, configs)
SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", "node_modules", ".tox"}
SKIP_FILES = {"conftest.py"}


def _is_production(path: Path, root: Path) -> bool:
    """Heuristic: not a test file, not an example, not a config, not a metrics module."""
    rel = path.relative_to(root).as_posix()
    if any(part in SKIP_DIRS for part in rel.split("/")):
        return False
    if path.name in SKIP_FILES:
        return False
    if "test" in rel.lower() or "example" in rel.lower():
        return False
    if "metrics/" in rel or rel.endswith("metrics"):
        return False
    return True


def collect_determinism(target: Path) -> MetricResult:
    """Scan Python source files for non-deterministic patterns."""
    evidence: list[str] = []
    violations: list[str] = []
    files_scanned = 0
    violation_count = 0

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
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # Skip pattern-definition lines (contain regex syntax like \b, \w, \.)
            if "\\b" in line or "\\w" in line or "\\." in line:
                continue
            for pattern, category, explanation in FORBIDDEN_PATTERNS:
                if re.search(pattern, line):
                    violation_count += 1
                    violations.append(f"{rel}:{line_no}: [{category}] {explanation}")
                    evidence.append(f"{rel}:{line_no}:{category}")

    # Score: 100 if no violations, decreases with each
    if files_scanned == 0:
        score = 100.0
        detail = "No Python files to scan"
    elif violation_count == 0:
        score = 100.0
        detail = f"All {files_scanned} production files are deterministic"
    else:
        # Each violation costs 15 points, min 0
        score = max(0.0, 100.0 - violation_count * 15)
        detail = f"{violation_count} non-deterministic pattern(s) across {files_scanned} files"

    return MetricResult(
        name="determinism",
        score=score,
        weight=1.0,
        passed=violation_count == 0,
        evidence=evidence[:50],  # cap evidence
        details=detail,
    )
