"""Module-level trust: per-module trust scoring.

Analyzes each Python module individually and produces a trust score
based on: has test, has docstring, function count, function length,
import count, and determinism.

Usage:
    from trust_meter.module_trust import analyze_modules
    modules = analyze_modules(Path("."))
    for m in modules:
        print(f"{m.name}: {m.score:.0f}/100")
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", "node_modules", ".tox"}
MAX_FUNCS = 20
MAX_FUNC_LINES = 50
MAX_IMPORTS = 15


@dataclass
class ModuleScore:
    """Trust score for a single module."""

    name: str
    path: str
    score: float
    has_test: bool
    has_docstrings: bool
    func_count: int
    max_func_lines: int
    import_count: int
    issues: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.score >= 70 and self.has_test

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "score": round(self.score, 1),
            "passed": self.passed,
            "has_test": self.has_test,
            "has_docstrings": self.has_docstrings,
            "func_count": self.func_count,
            "max_func_lines": self.max_func_lines,
            "import_count": self.import_count,
            "issues": self.issues,
        }


def _is_source(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if any(d in rel.split("/") for d in SKIP_DIRS):
        return False
    if "test" in rel.lower():
        return False
    if path.name == "__init__.py":
        return False
    return path.suffix == ".py"


def _find_test(module_name: str, root: Path) -> bool:
    for p in root.rglob("*.py"):
        if p.name == f"test_{module_name}.py" or p.name == f"{module_name}_test.py":
            return True
    return False


def _analyze_module(path: Path, root: Path) -> ModuleScore:
    name = path.stem
    rel = path.relative_to(root).as_posix()
    has_test = _find_test(name, root)

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except Exception:
        return ModuleScore(
            name=name, path=rel, score=0, has_test=has_test,
            has_docstrings=False, func_count=0, max_func_lines=0,
            import_count=0, issues=["parse error"],
        )

    funcs: list[ast.FunctionDef] = []
    imports = 0
    documented = 0
    total_public = 0

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(node)
            if not node.name.startswith("_"):
                total_public += 1
                has_doc = (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                )
                if has_doc:
                    documented += 1
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports += 1

    max_lines = 0
    for f in funcs:
        if hasattr(f, "end_lineno") and f.end_lineno:
            length = f.end_lineno - f.lineno + 1
            max_lines = max(max_lines, length)

    has_docstrings = (total_public == 0) or (documented == total_public)

    # Score calculation
    score = 100.0
    issues: list[str] = []

    if not has_test:
        score -= 30
        issues.append("no test file")

    if not has_docstrings:
        score -= 15
        missing = total_public - documented
        issues.append(f"{missing} missing docstring(s)")

    if max_lines > MAX_FUNC_LINES:
        score -= 10
        issues.append(f"function exceeds {MAX_FUNC_LINES} lines")

    if imports > MAX_IMPORTS:
        score -= 5
        issues.append(f"{imports} imports (max {MAX_IMPORTS})")

    if len(funcs) > MAX_FUNCS:
        score -= 5
        issues.append(f"{len(funcs)} functions (max {MAX_FUNCS})")

    score = max(0.0, min(100.0, score))

    return ModuleScore(
        name=name, path=rel, score=score, has_test=has_test,
        has_docstrings=has_docstrings, func_count=len(funcs),
        max_func_lines=max_lines, import_count=imports, issues=issues,
    )


def analyze_modules(root: Path) -> list[ModuleScore]:
    """Analyze all Python modules and return per-module trust scores."""
    modules: list[ModuleScore] = []
    for py_file in sorted(root.rglob("*.py")):
        if _is_source(py_file, root):
            modules.append(_analyze_module(py_file, root))
    return modules


def modules_summary(modules: list[ModuleScore]) -> dict:
    """Produce summary statistics from module scores."""
    if not modules:
        return {"count": 0, "avg_score": 0, "passed": 0, "failed": 0}

    scores = [m.score for m in modules]
    return {
        "count": len(modules),
        "avg_score": round(sum(scores) / len(scores), 1),
        "min_score": round(min(scores), 1),
        "max_score": round(max(scores), 1),
        "passed": sum(1 for m in modules if m.passed),
        "failed": sum(1 for m in modules if not m.passed),
    }


def modules_to_json(modules: list[ModuleScore], indent: int = 2) -> str:
    """Export module scores as JSON."""
    return json.dumps({
        "modules": [m.to_dict() for m in modules],
        "summary": modules_summary(modules),
    }, indent=indent, ensure_ascii=False)


def modules_to_markdown(modules: list[ModuleScore]) -> str:
    """Export module scores as markdown table."""
    lines = [
        "# Module Trust Scores",
        "",
        "| Module | Score | Test | Docs | Funcs | Issues |",
        "|--------|-------|------|------|-------|--------|",
    ]
    for m in modules:
        test = "YES" if m.has_test else "NO"
        docs = "YES" if m.has_docstrings else "NO"
        issues = "; ".join(m.issues) if m.issues else "none"
        lines.append(f"| {m.name} | {m.score:.0f} | {test} | {docs} | {m.func_count} | {issues} |")

    summary = modules_summary(modules)
    lines.append("")
    lines.append(f"**Total:** {summary['count']} modules | "
                 f"**Avg:** {summary['avg_score']} | "
                 f"**Passed:** {summary['passed']} | "
                 f"**Failed:** {summary['failed']}")

    return "\n".join(lines)
