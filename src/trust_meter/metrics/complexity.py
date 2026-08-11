"""Complexity metric: cyclomatic complexity analysis.

Measures cyclomatic complexity per function:
- Each if/elif/for/while/try/except/with/and/or adds 1
- Base complexity is 1 per function
- Functions with complexity > 10 are flagged
- Files with average complexity > 7 are flagged

Usage:
    from trust_meter.metrics.complexity import collect_complexity
    result = collect_complexity(Path("."))
"""

from __future__ import annotations

import ast
from pathlib import Path

from trust_meter.meter import MetricResult

SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", "node_modules", ".tox"}
MAX_FUNC_COMPLEXITY = 10
MAX_AVG_COMPLEXITY = 7


def _is_production(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if any(d in rel.split("/") for d in SKIP_DIRS):
        return False
    if "test" in rel.lower() or "example" in rel.lower():
        return False
    if "metrics/" in rel or rel.endswith("metrics"):
        return False
    return True


def _function_complexity(node: ast.AST) -> int:
    """Calculate cyclomatic complexity for a function AST node."""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.IfExp)):
            complexity += 1
        elif isinstance(child, ast.For):
            complexity += 1
        elif isinstance(child, ast.While):
            complexity += 1
        elif isinstance(child, ast.Try):
            complexity += 1
        elif isinstance(child, ast.ExceptHandler):
            complexity += 1
        elif isinstance(child, ast.With):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            # Each and/or adds 1
            complexity += len(child.values) - 1
        elif isinstance(child, ast.Assert):
            complexity += 1
    return complexity


def _analyze_file(path: Path, root: Path) -> list[tuple[str, int, int]]:
    """Analyze a file for function complexities. Returns (func_name, complexity, line)."""
    results: list[tuple[str, int, int]] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return results

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_") and node.name != "__init__":
                continue
            cc = _function_complexity(node)
            results.append((node.name, cc, node.lineno))
    return results


def collect_complexity(target: Path) -> MetricResult:
    """Analyze cyclomatic complexity across the codebase."""
    evidence: list[str] = []
    high_complexity: list[str] = []
    all_complexities: list[int] = []
    files_scanned = 0

    for py_file in sorted(target.rglob("*.py")):
        if not _is_production(py_file, target):
            continue
        files_scanned += 1
        rel = py_file.relative_to(target).as_posix()
        funcs = _analyze_file(py_file, target)

        for name, cc, line in funcs:
            all_complexities.append(cc)
            if cc > MAX_FUNC_COMPLEXITY:
                high_complexity.append(f"{rel}:{line}: {name} (cc={cc})")
                evidence.append(f"{rel}:{line}:{name}:cc{cc}")

    if files_scanned == 0:
        return MetricResult(
            name="complexity", score=100.0, weight=1.0,
            passed=True, evidence=[], details="No files to analyze",
        )

    avg_cc = sum(all_complexities) / len(all_complexities) if all_complexities else 0
    max_cc = max(all_complexities) if all_complexities else 0

    # Score
    score = 100.0
    score -= len(high_complexity) * 10
    if avg_cc > MAX_AVG_COMPLEXITY:
        score -= (avg_cc - MAX_AVG_COMPLEXITY) * 5
    score = max(0.0, min(100.0, score))

    passed = len(high_complexity) == 0 and avg_cc <= MAX_AVG_COMPLEXITY

    details = " | ".join([
        f"{len(all_complexities)} functions",
        f"avg cc={avg_cc:.1f}",
        f"max cc={max_cc}",
        f"{len(high_complexity)} high",
    ])

    return MetricResult(
        name="complexity", score=score, weight=1.0,
        passed=passed, evidence=evidence[:50], details=details,
    )
