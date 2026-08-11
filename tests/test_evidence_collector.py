"""Tests for the evidence collector."""

import tempfile
from pathlib import Path

from trust_meter.evidence import (
    collect_file_evidence, collect_import_graph,
    collect_test_results, collect_evidence_bundle,
    EvidenceBundle, FileEvidence, ImportEdge, RunResult,
)


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_collect_file_evidence():
    d = _make_project({
        "src/calc.py": "def add(a, b):\n    return a + b\n",
        "src/utils.py": "x = 1\n",
    })
    evidence = collect_file_evidence(d)
    assert len(evidence) == 2
    assert evidence[0].path == "src/calc.py"
    assert len(evidence[0].sha256) == 64
    assert evidence[0].lines == 2


def test_collect_file_evidence_skips_pycache():
    d = _make_project({"src/calc.py": "x = 1\n"})
    cache = d / "__pycache__"
    cache.mkdir()
    (cache / "calc.cpython-39.pyc").write_bytes(b"\x00")
    evidence = collect_file_evidence(d)
    assert len(evidence) == 1
    assert evidence[0].path == "src/calc.py"


def test_collect_file_evidence_empty():
    d = _make_project({})
    evidence = collect_file_evidence(d)
    assert len(evidence) == 0


def test_collect_import_graph_stdlib():
    d = _make_project({
        "src/main.py": "import os\nimport sys\nfrom pathlib import Path\n",
    })
    edges = collect_import_graph(d)
    assert len(edges) == 3
    targets = {e.target for e in edges}
    assert "os" in targets
    assert "sys" in targets
    assert "pathlib" in targets


def test_collect_import_graph_local():
    d = _make_project({
        "src/main.py": "import calc\nfrom utils import helper\n",
        "src/calc.py": "x = 1\n",
        "src/utils.py": "def helper(): pass\n",
    })
    edges = collect_import_graph(d)
    targets = {e.target for e in edges}
    assert "calc" in targets
    assert "utils" in targets


def test_collect_import_graph_empty():
    d = _make_project({})
    edges = collect_import_graph(d)
    assert len(edges) == 0


def test_collect_test_results():
    d = _make_project({
        "tests/test_add.py": "def test_one():\n    assert 1 + 1 == 2\n",
    })
    result = collect_test_results(d, timeout=30)
    assert result.passed >= 1
    assert result.failed == 0
    assert result.success is True


def test_collect_test_results_with_failure():
    d = _make_project({
        "tests/test_fail.py": "def test_bad():\n    assert 1 + 1 == 3\n",
    })
    result = collect_test_results(d, timeout=30)
    assert result.failed >= 1
    assert result.success is False


def test_test_result_properties():
    r = RunResult(command="pytest", returncode=0, passed=5, failed=0, errors=0, output="ok")
    assert r.success is True

    r2 = RunResult(command="pytest", returncode=1, passed=3, failed=2, errors=0, output="fail")
    assert r2.success is False

    r3 = RunResult(command="pytest", returncode=-1, passed=0, failed=0, errors=1, output="err")
    assert r3.success is False


def test_evidence_bundle_structure():
    d = _make_project({
        "src/calc.py": "import os\ndef add(a, b):\n    return a + b\n",
    })
    bundle = collect_evidence_bundle(d, run_tests=False)
    assert bundle.target == str(d)
    assert len(bundle.files) >= 1
    assert len(bundle.imports) >= 1
    assert bundle.test_result is None


def test_evidence_bundle_with_tests():
    d = _make_project({
        "tests/test_add.py": "def test_one():\n    assert 1 + 1 == 2\n",
    })
    bundle = collect_evidence_bundle(d, run_tests=True)
    assert bundle.test_result is not None
    assert bundle.test_result.passed >= 1


def test_evidence_bundle_to_json():
    d = _make_project({"src/calc.py": "x = 1\n"})
    bundle = collect_evidence_bundle(d, run_tests=False)
    j = bundle.to_json()
    assert '"target"' in j
    assert '"sha256"' in j


def test_file_evidence_deterministic():
    """Same file should always produce the same hash."""
    d = _make_project({"src/calc.py": "x = 1\n"})
    e1 = collect_file_evidence(d)
    e2 = collect_file_evidence(d)
    assert e1[0].sha256 == e2[0].sha256
    assert e1[0].lines == e2[0].lines


def test_import_graph_line_numbers():
    d = _make_project({
        "src/main.py": "\n\nimport os\nimport sys\n",
    })
    edges = collect_import_graph(d)
    os_edge = next(e for e in edges if e.target == "os")
    sys_edge = next(e for e in edges if e.target == "sys")
    assert os_edge.line == 3
    assert sys_edge.line == 4
