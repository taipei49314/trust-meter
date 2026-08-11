"""Spec engine: parse specification files and emit structured assertions.

A spec file defines what a project SHOULD contain. The spec engine
parses it and produces assertions that the trust-meter can verify.

Spec format (TOML-like, zero dependencies):
```
[project]
name = "my-project"
min_python = "3.9"

[assertions]
modules = ["calculator", "utils"]
require_tests = true
require_docstrings = true
max_function_lines = 50
```
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Assertion:
    """A single verifiable claim about the project."""

    kind: str          # "module_exists", "has_test", "has_docstring", etc.
    target: str        # module name, file path, etc.
    expected: str      # expected value or condition
    evidence: str = "" # filled after verification


@dataclass
class Spec:
    """Parsed specification with project metadata and assertions."""

    name: str
    min_python: str
    assertions: list[Assertion] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "min_python": self.min_python,
            "assertions": [
                {"kind": a.kind, "target": a.target, "expected": a.expected}
                for a in self.assertions
            ],
        }


def parse_spec(text: str) -> Spec:
    """Parse a spec file into a Spec object. Zero external dependencies."""
    name = _extract_string(text, "name", "unnamed")
    min_python = _extract_string(text, "min_python", "3.9")

    assertions: list[Assertion] = []

    # Parse modules list
    modules = _extract_list(text, "modules")
    for mod in modules:
        assertions.append(Assertion("module_exists", mod, "true"))

    # Parse boolean assertions
    if _extract_bool(text, "require_tests", False):
        for mod in modules:
            assertions.append(Assertion("has_test", mod, "true"))

    if _extract_bool(text, "require_docstrings", False):
        for mod in modules:
            assertions.append(Assertion("has_docstring", mod, "true"))

    # Parse numeric assertions
    max_lines = _extract_int(text, "max_function_lines", 0)
    if max_lines > 0:
        assertions.append(Assertion("max_function_lines", "*", str(max_lines)))

    return Spec(name=name, min_python=min_python, assertions=assertions)


def parse_spec_file(path: Path) -> Spec:
    """Parse a spec file from disk."""
    return parse_spec(path.read_text(encoding="utf-8"))


def emit_assertions(spec: Spec) -> list[Assertion]:
    """Return the list of assertions from a parsed spec."""
    return spec.assertions


def verify_assertions(assertions: list[Assertion], target: Path) -> list[Assertion]:
    """Verify assertions against a target directory. Fills in evidence."""
    verified: list[Assertion] = []
    for assertion in assertions:
        result = _verify_one(assertion, target)
        verified.append(result)
    return verified


def _verify_one(assertion: Assertion, target: Path) -> Assertion:
    """Verify a single assertion. Returns a copy with evidence filled in."""
    kind = assertion.kind
    target_name = assertion.target

    if kind == "module_exists":
        found = _find_module(target, target_name)
        return Assertion(
            kind=kind, target=target_name,
            expected="true",
            evidence=f"found at {found}" if found else "not found",
        )

    if kind == "has_test":
        found = _find_test(target, target_name)
        return Assertion(
            kind=kind, target=target_name,
            expected="true",
            evidence=f"test at {found}" if found else "no test found",
        )

    if kind == "has_docstring":
        has = _check_docstring(target, target_name)
        return Assertion(
            kind=kind, target=target_name,
            expected="true",
            evidence="documented" if has else "missing docstrings",
        )

    if kind == "max_function_lines":
        max_allowed = int(assertion.expected)
        violations = _check_function_lengths(target, max_allowed)
        return Assertion(
            kind=kind, target="*",
            expected=str(max_allowed),
            evidence=f"{len(violations)} violation(s)" if violations else "all within limit",
        )

    return Assertion(kind=kind, target=target_name, expected=assertion.expected, evidence="unknown assertion type")


def _find_module(root: Path, name: str) -> str | None:
    """Find a Python module by name in the project."""
    for p in root.rglob("*.py"):
        if p.stem == name:
            return str(p.relative_to(root))
    return None


def _find_test(root: Path, module_name: str) -> str | None:
    """Find a test file for the given module."""
    for p in root.rglob("*.py"):
        if p.name == f"test_{module_name}.py" or p.name == f"{module_name}_test.py":
            return str(p.relative_to(root))
    return None


def _check_docstring(root: Path, module_name: str) -> bool:
    """Check if a module's public functions have docstrings."""
    import ast

    for p in root.rglob("*.py"):
        if p.stem != module_name:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name.startswith("_"):
                    continue
                has_doc = (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)
                )
                if not has_doc:
                    return False
        return True
    return False


def _check_function_lengths(root: Path, max_lines: int) -> list[str]:
    """Find functions exceeding the line limit."""
    import ast

    violations: list[str] = []
    for p in root.rglob("*.py"):
        if "test" in p.stem.lower():
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    length = node.end_lineno - node.lineno + 1
                    if length > max_lines:
                        violations.append(f"{p.stem}::{node.name} ({length} lines)")
    return violations


# Simple TOML-like parser (zero dependencies)

def _extract_string(text: str, key: str, default: str) -> str:
    match = re.search(rf'{key}\s*=\s*"([^"]*)"', text)
    return match.group(1) if match else default


def _extract_bool(text: str, key: str, default: bool) -> bool:
    match = re.search(rf'{key}\s*=\s*(true|false)', text, re.IGNORECASE)
    if match:
        return match.group(1).lower() == "true"
    return default


def _extract_int(text: str, key: str, default: int) -> int:
    match = re.search(rf'{key}\s*=\s*(\d+)', text)
    return int(match.group(1)) if match else default


def _extract_list(text: str, key: str) -> list[str]:
    match = re.search(rf'{key}\s*=\s*\[([^\]]*)\]', text)
    if not match:
        return []
    items = match.group(1)
    return [item.strip().strip('"').strip("'") for item in items.split(",") if item.strip()]
