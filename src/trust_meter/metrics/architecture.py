"""Architecture metric: analyze import graph structure.

Checks:
- No circular dependencies (cycles in import graph)
- Module coupling (max imports per module)
- Dependency depth (longest chain)

Uses the import graph from evidence collector.
"""

from __future__ import annotations

import ast
from pathlib import Path

from trust_meter.meter import MetricResult

SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", "node_modules", ".tox"}
MAX_IMPORTS_PER_MODULE = 15
MAX_CHAIN_DEPTH = 10


def _is_production(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if any(d in rel.split("/") for d in SKIP_DIRS):
        return False
    if "test" in rel.lower() or "example" in rel.lower():
        return False
    return True


def _build_local_import_graph(target: Path) -> dict[str, set[str]]:
    """Build import graph with only local modules (not stdlib/external)."""
    # First pass: collect all local module names
    local_modules: set[str] = set()
    for py_file in sorted(target.rglob("*.py")):
        if _is_production(py_file, target):
            local_modules.add(py_file.stem)

    # Second pass: build graph with only local imports
    graph: dict[str, set[str]] = {}
    for py_file in sorted(target.rglob("*.py")):
        if not _is_production(py_file, target):
            continue
        module = py_file.stem
        if module not in graph:
            graph[module] = set()

        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target_mod = alias.name.split(".")[0]
                    if target_mod in local_modules and target_mod != module:
                        graph[module].add(target_mod)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    target_mod = node.module.split(".")[0]
                    if target_mod in local_modules and target_mod != module:
                        graph[module].add(target_mod)

    return graph


def _find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Find all simple cycles using DFS. Returns list of cycles."""
    cycles: list[list[str]] = []
    visited: set[str] = set()
    rec_stack: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in sorted(graph.get(node, set())):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_stack:
                # Found a cycle — extract it
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                # Normalize: start with smallest element
                min_idx = cycle[:-1].index(min(cycle[:-1]))
                normalized = cycle[min_idx:-1] + cycle[:min_idx] + [cycle[min_idx]]
                if normalized not in cycles:
                    cycles.append(normalized)

        path.pop()
        rec_stack.discard(node)

    for node in sorted(graph):
        if node not in visited:
            dfs(node)

    cycles.sort()
    return cycles


def _max_coupling(graph: dict[str, set[str]]) -> tuple[str, int]:
    """Find the module with the most outgoing imports."""
    if not graph:
        return ("", 0)
    max_count = max(len(dependencies) for dependencies in graph.values())
    max_mod = min(module for module in graph if len(graph[module]) == max_count)
    return (max_mod, max_count)


def _max_chain_depth(graph: dict[str, set[str]]) -> int:
    """Find the longest dependency chain using DFS."""
    memo: dict[str, int] = {}

    def depth(node: str, visiting: set[str]) -> int:
        if node in memo:
            return memo[node]
        if node in visiting:
            return 0  # cycle, don't recurse
        visiting.add(node)
        max_d = 0
        for dep in sorted(graph.get(node, set())):
            max_d = max(max_d, depth(dep, visiting) + 1)
        visiting.discard(node)
        memo[node] = max_d
        return max_d

    return max(depth(node, set()) for node in sorted(graph)) if graph else 0


def _compute_arch_score(cycles: list, max_count: int, depth: int) -> float:
    """Compute architecture score from analysis results."""
    score = 100.0
    score -= len(cycles) * 20
    if max_count > MAX_IMPORTS_PER_MODULE:
        score -= (max_count - MAX_IMPORTS_PER_MODULE) * 3
    if depth > MAX_CHAIN_DEPTH:
        score -= (depth - MAX_CHAIN_DEPTH) * 5
    return max(0.0, min(100.0, score))


def collect_architecture(target: Path) -> MetricResult:
    """Analyze import graph architecture."""
    graph = _build_local_import_graph(target)

    if not graph:
        return MetricResult(
            name="architecture", score=100.0, weight=1.0,
            passed=True, evidence=[], details="No local modules to analyze",
        )

    evidence: list[str] = []
    cycles = _find_cycles(graph)
    for cycle in cycles:
        evidence.append(f"cycle:{'->'.join(cycle)}")

    max_mod, max_count = _max_coupling(graph)
    if max_count > MAX_IMPORTS_PER_MODULE:
        evidence.append(f"coupling:{max_mod}:{max_count}")

    chain_depth = _max_chain_depth(graph)
    if chain_depth > MAX_CHAIN_DEPTH:
        evidence.append(f"depth:{chain_depth}")

    score = _compute_arch_score(cycles, max_count, chain_depth)
    details = " | ".join([
        f"{len(graph)} modules",
        f"{sum(len(v) for v in graph.values())} edges",
        f"{len(cycles)} cycle(s)",
        f"max coupling: {max_mod}({max_count})",
        f"max depth: {chain_depth}",
    ])

    return MetricResult(
        name="architecture", score=score, weight=1.0,
        passed=len(cycles) == 0,
        evidence=evidence[:50], details=details,
    )
