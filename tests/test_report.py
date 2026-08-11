"""Tests for the report generator."""

import json
import tempfile
from pathlib import Path

from trust_meter.cli import build_meter
from trust_meter.report import generate_report, FullReport, SpecVerification


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_generate_report_basic():
    d = _make_project({
        "src/calc.py": 'def add(a, b):\n    """Add."""\n    return a + b\n',
        "tests/test_calc.py": "def test_add():\n    assert add(1, 2) == 3\n",
    })
    meter = build_meter()
    report = generate_report(d, meter, phase_gate="Phase 3")

    assert report.passed is True
    assert report.phase_gate == "Phase 3"
    assert len(report.metrics) == 5
    assert report.overall_score > 0


def test_generate_report_with_spec():
    d = _make_project({
        "src/calc.py": 'def add(a, b):\n    """Add."""\n    return a + b\n',
        "tests/test_calc.py": "def test_add():\n    assert add(1, 2) == 3\n",
    })
    spec_file = d / "spec.txt"
    spec_file.write_text(
        '[project]\nname = "test"\nmin_python = "3.9"\n'
        '[assertions]\nmodules = ["calc"]\nrequire_tests = true'
    )

    meter = build_meter()
    report = generate_report(d, meter, spec_path=spec_file)

    assert len(report.spec_verifications) >= 1
    for sv in report.spec_verifications:
        assert sv.passed is True


def test_generate_report_with_spec_failure():
    d = _make_project({"src/calc.py": "x = 1\n"})
    spec_file = d / "spec.txt"
    spec_file.write_text(
        '[project]\nname = "test"\nmin_python = "3.9"\n'
        '[assertions]\nmodules = ["missing_module"]'
    )

    meter = build_meter()
    report = generate_report(d, meter, spec_path=spec_file)

    failed = [sv for sv in report.spec_verifications if not sv.passed]
    assert len(failed) >= 1


def test_report_to_dict():
    d = _make_project({"src/calc.py": "x = 1\n"})
    meter = build_meter()
    report = generate_report(d, meter)

    d_dict = report.to_dict()
    assert "target" in d_dict
    assert "metrics" in d_dict
    assert "evidence_summary" in d_dict
    assert isinstance(d_dict["metrics"], list)


def test_report_to_json():
    d = _make_project({"src/calc.py": "x = 1\n"})
    meter = build_meter()
    report = generate_report(d, meter)

    j = report.to_json()
    parsed = json.loads(j)
    assert "overall_score" in parsed
    assert "metrics" in parsed


def test_report_to_markdown():
    d = _make_project({"src/calc.py": "x = 1\n"})
    meter = build_meter()
    report = generate_report(d, meter, phase_gate="Test Phase")

    md = report.to_markdown()
    assert "# Trust Report" in md
    assert "Test Phase" in md
    assert "Metrics" in md


def test_report_summary_line():
    d = _make_project({"src/calc.py": "x = 1\n"})
    meter = build_meter()
    report = generate_report(d, meter)

    summary = report.summary_line()
    assert "PASS" in summary or "FAIL" in summary
    assert "/100" in summary


def test_report_evidence_summary():
    d = _make_project({
        "src/calc.py": "x = 1\n",
        "src/utils.py": "y = 2\n",
    })
    meter = build_meter()
    report = generate_report(d, meter, run_tests=False)

    assert report.evidence_summary["files_scanned"] >= 2
    assert report.evidence_summary["total_lines"] >= 2
    assert "import_edges" in report.evidence_summary


def test_report_without_spec():
    d = _make_project({"src/calc.py": "x = 1\n"})
    meter = build_meter()
    report = generate_report(d, meter)

    assert len(report.spec_verifications) == 0


def test_report_with_tests():
    d = _make_project({
        "tests/test_add.py": "def test_one():\n    assert 1 + 1 == 2\n",
    })
    meter = build_meter()
    report = generate_report(d, meter, run_tests=True)

    assert "tests_passed" in report.evidence_summary


def test_spec_verification_passed_field():
    sv = SpecVerification(
        kind="module_exists", target="calc",
        expected="true", evidence="found at src/calc.py", passed=True,
    )
    assert sv.passed is True
    assert sv.kind == "module_exists"
