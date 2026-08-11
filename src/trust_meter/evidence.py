"""Evidence collector: gather structured proof from a codebase.

Collects:
- File hash tree (SHA-256 of every source file)
- Import graph (module dependency relationships)
- Test execution results (via subprocess)
- Spec verification results

All evidence is machine-parseable and deterministic.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

from trust_meter.meter import file_hash, dir_hash_tree


@dataclass
class FileEvidence:
    """Hash evidence for a single file."""

    path: str
    sha256: str
    lines: int


@dataclass
class ImportEdge:
    """A single import relationship."""

    source: str
    target: str
    line: int


@dataclass
class RunResult:
    """Result of running a test suite."""

    command: str
    returncode: int
    passed: int
    failed: int
    errors: int
    output: str

    @property
    def success(self) -> bool:
        return self.returncode == 0 and self.failed == 0 and self.errors == 0


@dataclass
class EvidenceBundle:
    """Complete evidence collection for a codebase."""

    target: str
    files: list[FileEvidence] = field(default_factory=list)
    imports: list[ImportEdge] = field(default_factory=list)
    test_result: RunResult | None = None
    spec_verified: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "files": [asdict(f) for f in self.files],
            "imports": [asdict(i) for i in self.imports],
            "test_result": asdict(self.test_result) if self.test_result else None,
            "spec_verified": self.spec_verified,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def collect_file_evidence(target: Path) -> list[FileEvidence]:
    """Hash all Python source files and count lines."""
    evidence: list[FileEvidence] = []
    for py_file in sorted(target.rglob("*.py")):
        rel = py_file.relative_to(target).as_posix()
        if "__pycache__" in rel or ".git" in rel:
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
            lines = len(text.splitlines())
            evidence.append(FileEvidence(
                path=rel,
                sha256=file_hash(py_file),
                lines=lines,
            ))
        except Exception:
            continue
    return evidence


def collect_import_graph(target: Path) -> list[ImportEdge]:
    """Build import dependency graph from Python source files."""
    edges: list[ImportEdge] = []

    for py_file in sorted(target.rglob("*.py")):
        rel = py_file.relative_to(target).as_posix()
        if "__pycache__" in rel or ".git" in rel:
            continue

        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue

        source_module = py_file.stem
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    edges.append(ImportEdge(
                        source=source_module,
                        target=alias.name.split(".")[0],
                        line=node.lineno,
                    ))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    edges.append(ImportEdge(
                        source=source_module,
                        target=node.module.split(".")[0],
                        line=node.lineno,
                    ))

    return edges


def collect_test_results(target: Path, timeout: int = 60) -> RunResult:
    """Run pytest and capture results."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(target), "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(target),
        )
        output = result.stdout + result.stderr
        passed = output.count(" PASSED")
        failed = output.count(" FAILED")
        errors = output.count(" ERROR")

        return RunResult(
            command=f"{sys.executable} -m pytest {target} -v",
            returncode=result.returncode,
            passed=passed,
            failed=failed,
            errors=errors,
            output=output[-2000:],  # cap output
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            command=f"pytest {target}",
            returncode=-1,
            passed=0, failed=0, errors=1,
            output="TIMEOUT",
        )
    except Exception as e:
        return RunResult(
            command=f"pytest {target}",
            returncode=-1,
            passed=0, failed=0, errors=1,
            output=str(e),
        )


def collect_evidence_bundle(target: Path, run_tests: bool = False) -> EvidenceBundle:
    """Collect all evidence for a codebase."""
    bundle = EvidenceBundle(target=str(target))

    bundle.files = collect_file_evidence(target)
    bundle.imports = collect_import_graph(target)

    if run_tests:
        bundle.test_result = collect_test_results(target)

    return bundle
