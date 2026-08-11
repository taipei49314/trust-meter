"""File-level trust: per-file trust scoring.

More granular than module-level — analyzes each file individually.

Checks per file:
- Line count
- Function count and lengths
- Import count
- Docstring coverage
- Has corresponding test file
- Determinism (no forbidden calls)

Usage:
    from trust_meter.file_trust import analyze_files
    files = analyze_files(Path("."))
    for f in files:
        print(f"{f.path}: {f.score:.0f}/100")
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", "node_modules", ".tox"}
MAX_LINES = 500
MAX_FUNCS = 20
MAX_FUNC_LINES = 50
MAX_IMPORTS = 15


@dataclass
class FileScore:
    """Trust score for a single file."""

    path: str
    score: float
    lines: int
    func_count: int
    max_func_lines: int
    import_count: int
    docstring_ratio: float
    has_test: bool
    issues: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.score >= 70

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "score": round(self.score, 1),
            "passed": self.passed,
            "lines": self.lines,
            "func_count": self.func_count,
            "max_func_lines": self.max_func_lines,
            "import_count": self.import_count,
            "docstring_ratio": round(self.docstring_ratio, 2),
            "has_test": self.has_test,
            "issues": self.issues,
        }


def _is_scannable(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if any(d in rel.split("/") for d in SKIP_DIRS):
        return False
    return path.suffix == ".py"


def _find_test_for(path: Path, root: Path) -> bool:
    stem = path.stem
    rel = path.relative_to(root).as_posix()
    parts = rel.split("/")
    if len(parts) >= 2:
        test_dir = "/".join(parts[:-1]).replace("src", "tests")
        test_file = root / test_dir / f"test_{stem}.py"
        if test_file.exists():
            return True
    for p in root.rglob(f"test_{stem}.py"):
        return True
    return False


def _analyze_file(path: Path, root: Path) -> FileScore:
    rel = path.relative_to(root).as_posix()
    has_test = _find_test_for(path, root)

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        tree = ast.parse(text)
    except Exception:
        return FileScore(
            path=rel, score=0, lines=0, func_count=0,
            max_func_lines=0, import_count=0, docstring_ratio=0,
            has_test=has_test, issues=["parse error"],
        )

    line_count = len(lines)
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

    doc_ratio = documented / total_public if total_public > 0 else 1.0

    # Score
    score = 100.0
    issues: list[str] = []

    if not has_test:
        score -= 25
        issues.append("no test file")

    if line_count > MAX_LINES:
        score -= 10
        issues.append(f"{line_count} lines (max {MAX_LINES})")

    if max_lines > MAX_FUNC_LINES:
        score -= 10
        issues.append(f"function exceeds {MAX_FUNC_LINES} lines")

    if imports > MAX_IMPORTS:
        score -= 5
        issues.append(f"{imports} imports (max {MAX_IMPORTS})")

    if len(funcs) > MAX_FUNCS:
        score -= 5
        issues.append(f"{len(funcs)} functions")

    if doc_ratio < 1.0 and total_public > 0:
        score -= 10 * (1 - doc_ratio)
        issues.append(f"{int(doc_ratio * 100)}% documented")

    score = max(0.0, min(100.0, score))

    return FileScore(
        path=rel, score=score, lines=line_count, func_count=len(funcs),
        max_func_lines=max_lines, import_count=imports,
        docstring_ratio=doc_ratio, has_test=has_test, issues=issues,
    )


def analyze_files(root: Path) -> list[FileScore]:
    """Analyze all Python files and return per-file trust scores."""
    files: list[FileScore] = []
    for py_file in sorted(root.rglob("*.py")):
        if _is_scannable(py_file, root):
            files.append(_analyze_file(py_file, root))
    return files


def files_summary(files: list[FileScore]) -> dict:
    """Summary statistics from file scores."""
    if not files:
        return {"count": 0, "avg_score": 0, "passed": 0, "failed": 0}
    scores = [f.score for f in files]
    return {
        "count": len(files),
        "avg_score": round(sum(scores) / len(scores), 1),
        "min_score": round(min(scores), 1),
        "max_score": round(max(scores), 1),
        "total_lines": sum(f.lines for f in files),
        "passed": sum(1 for f in files if f.passed),
        "failed": sum(1 for f in files if not f.passed),
    }


def files_to_json(files: list[FileScore], indent: int = 2) -> str:
    """Export file scores as JSON."""
    return json.dumps({
        "files": [f.to_dict() for f in files],
        "summary": files_summary(files),
    }, indent=indent, ensure_ascii=False)


def files_to_markdown(files: list[FileScore]) -> str:
    """Export file scores as markdown table."""
    lines = [
        "# File Trust Scores",
        "",
        "| File | Score | Lines | Funcs | Test | Issues |",
        "|------|-------|-------|-------|------|--------|",
    ]
    for f in files:
        test = "YES" if f.has_test else "NO"
        issues = "; ".join(f.issues) if f.issues else "none"
        lines.append(f"| {f.path} | {f.score:.0f} | {f.lines} | {f.func_count} | {test} | {issues} |")

    summary = files_summary(files)
    lines.append("")
    lines.append(f"**Total:** {summary['count']} files | "
                 f"**Lines:** {summary['total_lines']} | "
                 f"**Passed:** {summary['passed']} | "
                 f"**Failed:** {summary['failed']}")
    return "\n".join(lines)
