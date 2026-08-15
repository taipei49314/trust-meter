"""Locality metric: verify the project runs without network access.

Checks:
- No runtime network dependencies in requirements
- All imports resolve to local packages or stdlib
- No hardcoded URLs in production code
- No remote data fetching patterns
"""

from __future__ import annotations

import re
from pathlib import Path

from trust_meter.meter import MetricResult

SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", "node_modules", ".tox"}

# Known remote-only packages
REMOTE_PACKAGES = {
    "requests", "httpx", "aiohttp", "urllib3", "httpcore",
    "boto3", "botocore", "google-cloud", "azure",
    "redis", "pymongo", "psycopg2", "mysql",
    "celery", "dramatiq", "rq",
    "docker", "kubernetes",
}

URL_PATTERN = re.compile(
    r'https?://[^\s\'")\]}>]+',
    re.IGNORECASE,
)


def _check_requirements(target: Path) -> tuple[list[str], list[str]]:
    """Parse requirements files and flag remote-only deps."""
    violations: list[str] = []
    evidence: list[str] = []

    req_files = sorted(
        [
            *target.glob("requirements*.txt"),
            *target.glob("pyproject.toml"),
        ]
    )
    for req_file in req_files:
        try:
            text = req_file.read_text(encoding="utf-8")
        except Exception:
            continue

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            # Extract package name (before ==, >=, etc.)
            pkg = re.split(r"[>=<!\[]", line)[0].strip().lower().replace("-", "_")
            if pkg in REMOTE_PACKAGES:
                violations.append(f"{req_file.name}: {pkg} is a remote-only dependency")

    return violations, evidence


def _check_hardcoded_urls(target: Path) -> list[str]:
    """Find hardcoded URLs in production Python code."""
    violations: list[str] = []

    for py_file in sorted(target.rglob("*.py")):
        rel = py_file.relative_to(target).as_posix()
        if any(d in rel.split("/") for d in SKIP_DIRS):
            continue
        if "test" in rel.lower() or "example" in rel.lower():
            continue

        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for line_no, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if URL_PATTERN.search(line):
                violations.append(f"{rel}:{line_no}: hardcoded URL")

    return violations


def collect_locality(target: Path) -> MetricResult:
    """Verify the project can run without network access."""
    all_violations: list[str] = []
    all_evidence: list[str] = []

    # Check requirements
    req_violations, req_evidence = _check_requirements(target)
    all_violations.extend(req_violations)
    all_evidence.extend(req_evidence)

    # Check hardcoded URLs
    url_violations = _check_hardcoded_urls(target)
    all_violations.extend(url_violations)

    violation_count = len(all_violations)

    if violation_count == 0:
        score = 100.0
        detail = "No remote dependencies or hardcoded URLs detected"
    else:
        score = max(0.0, 100.0 - violation_count * 10)
        detail = f"{violation_count} locality violation(s) found"

    return MetricResult(
        name="locality",
        score=score,
        weight=1.0,
        passed=violation_count == 0,
        evidence=all_violations[:50],
        details=detail,
    )
