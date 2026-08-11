"""Evidence metric: verify test coverage and assertion density.

Checks:
- Test files exist
- Every source module has a corresponding test
- Assertion density (assert statements per test function)
- No empty test functions
"""

from __future__ import annotations

import ast
from pathlib import Path

from trust_meter.meter import MetricResult

SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", "node_modules", ".tox"}


def _find_source_modules(target: Path) -> set[str]:
    """Find all production Python modules (excluding tests)."""
    modules: set[str] = set()
    for py_file in sorted(target.rglob("*.py")):
        rel = py_file.relative_to(target).as_posix()
        parts = rel.split("/")
        if any(d in parts for d in SKIP_DIRS):
            continue
        if "test" in rel.lower() or "conftest" in rel.lower():
            continue
        if py_file.name == "__init__.py":
            continue
        # Strip .py extension for matching
        modules.add(py_file.stem)
    return modules


def _find_test_files(target: Path) -> list[Path]:
    """Find all test files."""
    tests: list[Path] = []
    for py_file in sorted(target.rglob("*.py")):
        rel = py_file.relative_to(target).as_posix()
        if any(d in rel.split("/") for d in SKIP_DIRS):
            continue
        if py_file.name.startswith("test_") or py_file.name.endswith("_test.py"):
            tests.append(py_file)
        elif "tests/" in rel or "test/" in rel:
            tests.append(py_file)
    return tests


def _analyze_test_file(test_file: Path) -> tuple[int, int, int, list[str]]:
    """Analyze a test file: (test_count, assert_count, empty_tests, empty_names)."""
    try:
        tree = ast.parse(test_file.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return 0, 0, 0, []

    test_count = 0
    assert_count = 0
    empty_tests = 0
    empty_names: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                test_count += 1
                # Count assert statements in this function
                func_asserts = sum(
                    1 for child in ast.walk(node)
                    if isinstance(child, (ast.Assert, ast.Raise))
                )
                assert_count += func_asserts
                if func_asserts == 0:
                    empty_tests += 1
                    empty_names.append(node.name)

    return test_count, assert_count, empty_tests, empty_names


def _find_tested_modules(test_files: list[Path]) -> set[str]:
    """Extract module names that tests reference (test_foo -> foo)."""
    tested: set[str] = set()
    for tf in test_files:
        name = tf.stem
        if name.startswith("test_"):
            tested.add(name[5:])
        elif name.endswith("_test"):
            tested.add(name[:-5])
    return tested


def _check_coverage(
    source_modules: set[str], tested_modules: set[str]
) -> tuple[float, set[str]]:
    """Check module test coverage. Returns (coverage_ratio, untested_modules)."""
    untested = source_modules - tested_modules
    ratio = (len(source_modules) - len(untested)) / len(source_modules) * 100
    return ratio, untested


def _check_assertions(
    test_files: list[Path],
) -> tuple[int, int, int, float, list[str]]:
    """Analyze test assertions. Returns (tests, asserts, empty, density, evidence)."""
    total_tests = 0
    total_asserts = 0
    total_empty = 0
    evidence: list[str] = []

    for tf in test_files:
        tc, ac, et, en = _analyze_test_file(tf)
        total_tests += tc
        total_asserts += ac
        total_empty += et
        for name in en:
            evidence.append(f"empty_test:{tf.stem}::{name}")

    density = total_asserts / total_tests if total_tests > 0 else 0.0
    return total_tests, total_asserts, total_empty, density, evidence


def _evidence_score(coverage: float, empty: int, density: float, has_tests: bool) -> float:
    """Compute final evidence score from component metrics."""
    score = coverage
    if empty > 0:
        score -= empty * 5
    if density < 1.0 and has_tests:
        score -= 10
    return max(0.0, min(100.0, score))


def collect_evidence(target: Path) -> MetricResult:
    """Verify test coverage and assertion density."""
    evidence: list[str] = []
    issues: list[str] = []

    source_modules = _find_source_modules(target)
    test_files = _find_test_files(target)
    tested_modules = _find_tested_modules(test_files)

    if not source_modules:
        return MetricResult(
            name="evidence", score=100.0, weight=1.0,
            passed=True, evidence=[], details="No source modules found to test",
        )

    coverage_ratio, untested = _check_coverage(source_modules, tested_modules)
    for mod in sorted(untested):
        issues.append(f"no test for module: {mod}")
        evidence.append(f"untested:{mod}")

    total_tests, total_asserts, total_empty, density, empty_ev = _check_assertions(test_files)
    evidence.extend(empty_ev)

    if total_tests > 0 and density < 1.0:
        issues.append(f"low assertion density: {density:.1f} asserts/test")
    if total_empty > 0:
        issues.append(f"{total_empty} empty test function(s)")

    score = _evidence_score(coverage_ratio, total_empty, density, total_tests > 0)
    details = " | ".join([
        f"{len(source_modules)} source modules", f"{len(test_files)} test files",
        f"{total_tests} test functions", f"{total_asserts} assertions",
        f"{coverage_ratio:.0f}% module coverage",
    ])

    return MetricResult(
        name="evidence", score=score, weight=1.0,
        passed=len(untested) == 0 and total_empty == 0,
        evidence=evidence[:50], details=details,
    )
