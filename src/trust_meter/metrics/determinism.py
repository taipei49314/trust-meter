"""Determinism metric: AST-based analysis of non-deterministic patterns.

Two-layer analysis:
1. AST layer — finds actual function calls to forbidden modules
2. Regex layer — catches patterns AST might miss (attribute chains, etc.)

Forbidden categories:
- random: random.randint, random.choice, etc.
- entropy: os.urandom, secrets.*
- network: requests.get, httpx, urllib, socket
- dynamic_import: __import__, importlib.import_module
- timestamp: time.time, datetime.now (without tz)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from trust_meter.meter import MetricResult

SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", "node_modules", ".tox"}
SKIP_FILES = {"conftest.py"}

# Modules whose function calls are forbidden
FORBIDDEN_MODULES: dict[str, tuple[str, str]] = {
    # module_name: (category, explanation)
    "random": ("random", "random module call"),
    "os": ("entropy", "os.urandom call"),
    "secrets": ("entropy", "secrets module usage"),
    "requests": ("network", "HTTP request via requests"),
    "httpx": ("network", "HTTP request via httpx"),
    "urllib": ("network", "URL open via urllib"),
    "urllib.request": ("network", "URL open via urllib.request"),
    "socket": ("network", "socket operation"),
    "importlib": ("dynamic_import", "importlib usage"),
}

# Specific function calls that are forbidden (module.func)
FORBIDDEN_CALLS: dict[tuple[str, str], tuple[str, str]] = {
    # (module, function): (category, explanation)
    ("random", "randint"): ("random", "random.randint"),
    ("random", "random"): ("random", "random.random"),
    ("random", "choice"): ("random", "random.choice"),
    ("random", "shuffle"): ("random", "random.shuffle"),
    ("random", "sample"): ("random", "random.sample"),
    ("random", "uniform"): ("random", "random.uniform"),
    ("random", "randrange"): ("random", "random.randrange"),
    ("os", "urandom"): ("entropy", "os.urandom"),
    ("os", "getenv"): ("env_var", "os.getenv reads environment"),
    ("os", "environ"): ("env_var", "os.environ reads environment"),
    ("requests", "get"): ("network", "requests.get"),
    ("requests", "post"): ("network", "requests.post"),
    ("requests", "put"): ("network", "requests.put"),
    ("requests", "delete"): ("network", "requests.delete"),
    ("urllib.request", "urlopen"): ("network", "urllib.request.urlopen"),
    ("socket", "connect"): ("network", "socket.connect"),
    ("socket", "bind"): ("network", "socket.bind"),
    ("importlib", "import_module"): ("dynamic_import", "importlib.import_module"),
    ("time", "time"): ("timestamp", "time.time"),
    ("datetime", "now"): ("timestamp", "datetime.now"),
    ("datetime", "utcnow"): ("timestamp", "datetime.utcnow"),
}

# Bare name calls that are always forbidden
FORBIDDEN_BARE: dict[str, tuple[str, str]] = {
    "__import__": ("dynamic_import", "bare __import__ call"),
}


def _is_production(path: Path, root: Path) -> bool:
    """Heuristic: not a test file, not an example, not a metrics module."""
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


class _DeterminismVisitor(ast.NodeVisitor):
    """AST visitor that finds non-deterministic function calls."""

    def __init__(self) -> None:
        self.violations: list[tuple[int, str, str]] = []  # (line, category, detail)
        self._aliases: dict[str, str] = {}  # local_name -> real_module

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            real = alias.name
            local = alias.asname or alias.name
            self._aliases[local] = real
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            for alias in node.names:
                real_name = alias.name
                local = alias.asname or alias.name
                # Store as "module.function" for from-imports
                self._aliases[local] = f"{node.module}.{real_name}"
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self._check_call(node)
        self.generic_visit(node)

    def _check_call(self, node: ast.Call) -> None:
        func = node.func

        # Case 1: bare name call — func(id)
        if isinstance(func, ast.Name):
            name = func.id
            if name in FORBIDDEN_BARE:
                cat, detail = FORBIDDEN_BARE[name]
                self.violations.append((node.lineno, cat, detail))
            # Check if it's an alias to a forbidden function
            if name in self._aliases:
                resolved = self._aliases[name]
                parts = resolved.rsplit(".", 1)
                if len(parts) == 2:
                    mod, func_name = parts
                    # Try exact match first, then parent module
                    for candidate in [(mod, func_name), (mod.split(".")[0], func_name)]:
                        if candidate in FORBIDDEN_CALLS:
                            cat, detail = FORBIDDEN_CALLS[candidate]
                            self.violations.append((node.lineno, cat, detail))
                            break

        # Case 2: attribute call — obj.method()
        elif isinstance(func, ast.Attribute):
            attr = func.attr
            # Check if obj is a known module alias
            if isinstance(func.value, ast.Name):
                obj_name = func.value.id
                real_module = self._aliases.get(obj_name, obj_name)
                # Try exact module match, then parent module (e.g. datetime.datetime -> datetime)
                key = (real_module, attr)
                parent_key = (real_module.split(".")[0], attr)
                matched = False
                for candidate in [key, parent_key]:
                    if candidate in FORBIDDEN_CALLS:
                        cat, detail = FORBIDDEN_CALLS[candidate]
                        self.violations.append((node.lineno, cat, detail))
                        matched = True
                        break
                if not matched and real_module in FORBIDDEN_MODULES and attr in (
                    "get", "post", "put", "delete", "patch", "head",
                    "connect", "bind", "listen", "urlopen",
                    "randint", "random", "choice", "shuffle", "sample",
                    "urandom", "import_module", "now", "utcnow", "time",
                    "token_hex", "token_bytes", "token_urlsafe",
                ):
                    cat, detail = FORBIDDEN_MODULES[real_module]
                    self.violations.append((node.lineno, cat, f"{real_module}.{attr}"))

            # Case 3: chained attribute — urllib.request.urlopen
            elif isinstance(func.value, ast.Attribute) and isinstance(func.value.value, ast.Name):
                obj_name = func.value.value.id
                mid = func.value.attr
                real_module = self._aliases.get(obj_name, obj_name)
                full_module = f"{real_module}.{mid}"
                key = (full_module, attr)
                if key in FORBIDDEN_CALLS:
                    cat, detail = FORBIDDEN_CALLS[key]
                    self.violations.append((node.lineno, cat, detail))


def _analyze_file_ast(text: str) -> list[tuple[int, str, str]]:
    """Use AST to find non-deterministic calls. Returns (line, category, detail)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    visitor = _DeterminismVisitor()
    visitor.visit(tree)
    return visitor.violations


# Regex fallback for instance method calls AST can't resolve
_INSTANCE_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\.\s*connect\s*\("), "network", "socket.connect on instance"),
    (re.compile(r"\.\s*bind\s*\("), "network", "socket.bind on instance"),
    (re.compile(r"\.\s*listen\s*\("), "network", "socket.listen on instance"),
]


def _analyze_file_regex(text: str, rel: str) -> list[tuple[int, str, str]]:
    """Regex fallback for patterns AST misses (instance methods)."""
    violations: list[tuple[int, str, str]] = []
    has_socket_import = "import socket" in text
    if not has_socket_import:
        return violations

    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for pattern, category, detail in _INSTANCE_PATTERNS:
            if pattern.search(line):
                violations.append((line_no, category, detail))
    return violations


def collect_determinism(target: Path) -> MetricResult:
    """Scan Python source files for non-deterministic patterns using AST analysis."""
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
        ast_violations = _analyze_file_ast(text)
        regex_violations = _analyze_file_regex(text, rel)

        for line_no, category, detail in ast_violations + regex_violations:
            violation_count += 1
            violations.append(f"{rel}:{line_no}: [{category}] {detail}")
            evidence.append(f"{rel}:{line_no}:{category}")

    if files_scanned == 0:
        score = 100.0
        detail = "No Python files to scan"
    elif violation_count == 0:
        score = 100.0
        detail = f"All {files_scanned} production files are deterministic"
    else:
        score = max(0.0, 100.0 - violation_count * 15)
        detail = f"{violation_count} non-deterministic call(s) across {files_scanned} files"

    return MetricResult(
        name="determinism",
        score=score,
        weight=1.0,
        passed=violation_count == 0,
        evidence=evidence[:50],
        details=detail,
    )
