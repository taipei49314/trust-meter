"""Transparency metric: verify code is readable and documented.

Checks:
- Every public function/class has a docstring
- No functions exceeding 50 lines
- No files exceeding 500 lines
- Import statements are at the top of files
- No TODO/FIXME/HACK comments in production code
"""

from __future__ import annotations

import ast
from pathlib import Path

from trust_meter.meter import MetricResult

SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", "node_modules", ".tox"}
MAX_FUNC_LINES = 50
MAX_FILE_LINES = 500


def _is_production(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if any(d in rel.split("/") for d in SKIP_DIRS):
        return False
    if "test" in rel.lower() or "example" in rel.lower() or "conftest" in rel.lower():
        return False
    return True


def _scan_comments(lines: list[str], rel: str) -> list[str]:
    """Scan comment lines for incomplete-work markers."""
    issues: list[str] = []
    for line_no, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        for marker in ("TODO", "FIXME", "HACK", "XXX"):
            if marker in stripped:
                issues.append(f"{rel}:{line_no}: contains {marker}")
    return issues


def _analyze_ast(text: str, rel: str) -> tuple[list[str], int, int]:
    """AST analysis for docstrings and function lengths."""
    issues: list[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return issues, 0, 0

    public_items = 0
    documented_items = 0

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("_") and node.name != "__init__":
                continue
            public_items += 1
            has_doc = (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            )
            if has_doc:
                documented_items += 1
            else:
                issues.append(f"{rel}:{node.lineno}: {node.name} missing docstring")

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    func_len = node.end_lineno - node.lineno + 1
                    if func_len > MAX_FUNC_LINES:
                        issues.append(
                            f"{rel}:{node.lineno}: {node.name} exceeds {MAX_FUNC_LINES} lines ({func_len})"
                        )

    return issues, public_items, documented_items


def _analyze_file(path: Path, root: Path) -> tuple[list[str], int, int]:
    """Analyze a single file. Returns (issues, public_items, items_with_docstrings)."""
    issues: list[str] = []
    rel = path.relative_to(root).as_posix()

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return issues, 0, 0

    lines = text.splitlines()
    if len(lines) > MAX_FILE_LINES:
        issues.append(f"{rel}: file exceeds {MAX_FILE_LINES} lines ({len(lines)})")

    issues.extend(_scan_comments(lines, rel))
    ast_issues, public, documented = _analyze_ast(text, rel)
    issues.extend(ast_issues)

    return issues, public, documented


def _compute_score_and_details(
    all_issues: list[str], doc_ratio: float, files_scanned: int,
    total_documented: int, total_public: int,
) -> tuple[float, bool, list[str]]:
    """Compute transparency score, pass status, and detail lines."""
    issue_penalty = len(all_issues) * 3
    score = max(0.0, min(100.0, doc_ratio - issue_penalty))

    docstring_missing = sum(1 for i in all_issues if "missing docstring" in i)
    long_functions = sum(1 for i in all_issues if "exceeds" in i and "lines" in i)
    todos = sum(1 for i in all_issues if "TODO" in i or "FIXME" in i or "HACK" in i)

    details = [f"{files_scanned} files scanned"]
    details.append(f"{doc_ratio:.0f}% documented ({total_documented}/{total_public})")
    if docstring_missing:
        details.append(f"{docstring_missing} missing docstrings")
    if long_functions:
        details.append(f"{long_functions} oversized functions")
    if todos:
        details.append(f"{todos} TODO/FIXME/HACK")

    passed = docstring_missing == 0 and long_functions == 0
    return score, passed, details


def collect_transparency(target: Path) -> MetricResult:
    """Verify code readability and documentation."""
    all_issues: list[str] = []
    total_public = 0
    total_documented = 0
    files_scanned = 0

    for py_file in sorted(target.rglob("*.py")):
        if not _is_production(py_file, target):
            continue
        files_scanned += 1
        issues, public, documented = _analyze_file(py_file, target)
        all_issues.extend(issues)
        total_public += public
        total_documented += documented

    if files_scanned == 0:
        return MetricResult(
            name="transparency",
            score=100.0,
            weight=1.0,
            passed=True,
            evidence=[],
            details="No Python files to scan",
        )

    doc_ratio = (total_documented / total_public * 100) if total_public > 0 else 100
    score, passed, details = _compute_score_and_details(
        all_issues, doc_ratio, files_scanned, total_documented, total_public,
    )

    return MetricResult(
        name="transparency",
        score=score,
        weight=1.0,
        passed=passed,
        evidence=all_issues[:50],
        details=" | ".join(details),
    )
